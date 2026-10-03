#!/usr/bin/env python3
"""Frozen-checkpoint A/B diagnostic for authoritative result bodies.

This wrapper reads frozen v0.1 inputs and existing v0.2 fixture packages. It
never edits canonical records or fixtures. B is formed by appending only the
matching receipt to the serialized runtime tool_results array.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/dataset/experiments/v0.2/paired_grounding_diagnostic"
V01 = ROOT / "docs/ai/dataset/canonical_training/v0.1"
SETUP = ROOT / "docs/ai/training_setup/v0.1"
FIXTURE_ROOT = ROOT / "docs/ai/dataset/experiments/v0.2"
STATIC_DIR = FIXTURE_ROOT / "authoritative_result_fixtures"
BACKEND_DIR = FIXTURE_ROOT / "authoritative_backend_receipts"
MODEL = Path(r"D:\AI\models\Qwen3.5-4B")
ADAPTER = Path(r"D:\AI\runs\shared-ledger\training_runs\qlora-v0.1\20260930-143013\train\checkpoints\checkpoint-33")
LLAMAFACTORY = Path(r"D:\AI\LlamaFactory\src")
PYTHON = Path(r"D:\AI\.venv\Scripts\python.exe")
TEMPLATE = "qwen3_5_nothink"
MAX_NEW_TOKENS = 1024
GENERATION = {"max_new_tokens": MAX_NEW_TOKENS, "do_sample": False, "temperature": 0.0,
              "template": TEMPLATE, "enable_thinking": False, "quantization": "bnb_nf4_4bit"}
POSITIVE = {
    "static_primary": "At least two independent static Scenario states improve grounded material/key-fact correctness by >=50 percentage points; at least two distinct business boundaries/fact shapes improve; at least four more of 39 static rows improve than regress on grounded facts; no new material safety issue; and no state regresses by >=50 percentage points.",
    "backend_secondary": "Report separately for two states and nine rows; UUID/legacy ID mismatch remains a confound and cannot count as grounded correctness.",
}
NEGATIVE = "Any new dangerous write/bypass, or net deterioration in grounded factual/business correctness."
WEAK = "All other outcomes, including schema-only gains, unsupported claims, receipt copying without grounded use, or gains explained only by backend ID equivalence."
MARKER = "運行時上下文（JSON）："
META = re.compile(r"(?i)(sample_id|scenario_id|scenario_family_id|split_group_id|gold_seed|teacher_generated|canonical_training|gold_sample|teacher_dataset|training_eligible)")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def load_receipts() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    static = read_json(STATIC_DIR / "result_fixtures.json")["fixtures"]
    backend = read_json(BACKEND_DIR / "backend_result_fixtures.json")["fixtures"]
    static_map = {(x["scenario_id"], x["tool"]): x for x in static}
    backend_map = {(x["scenario_id"], x["tool"]): x for x in backend}
    if len(static_map) != len(static) or len(backend_map) != len(backend):
        raise ValueError("duplicate Scenario/Tool fixture binding")
    return static_map, backend_map


def selected_samples() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    canonical = read_json(V01 / "samples.json")
    by_id = {x["sample_id"]: x for x in canonical}
    static_audit = read_json(STATIC_DIR / "sample_rebuildability.json")["samples"]
    backend_coverage = read_json(BACKEND_DIR / "batch_coverage.json")["sample_coverage"]
    chosen = [x["sample_id"] for x in static_audit if x["rebuildable"]]
    chosen += [x["sample_id"] for x in backend_coverage if x["reconstructable"]]
    if len(chosen) != 48 or len(set(chosen)) != 48:
        raise ValueError(f"expected 48 unique authoritative samples, got {len(chosen)}/{len(set(chosen))}")
    return [by_id[x] for x in chosen], {x["sample_id"]: x for x in canonical}


def original_serialized_rows() -> dict[str, dict[str, Any]]:
    trace = read_json(SETUP / "traceability.json")
    trace_ids = {x["split"]: [] for x in trace}
    for item in trace:
        trace_ids[item["split"]].append(item["sample_id"])
    result: dict[str, dict[str, Any]] = {}
    for split, ids in trace_ids.items():
        rows = read_json(SETUP / "llamafactory" / f"{split}.json")
        if len(rows) != len(ids):
            raise ValueError(f"v0.1 {split} row/trace mismatch")
        result.update(zip(ids, rows))
    return result


def patch_system_receipt(system: str, receipt: dict[str, Any]) -> str:
    if system.count(MARKER) != 1:
        raise ValueError("unexpected frozen serializer context marker")
    prefix, context_text = system.split(MARKER, 1)
    raw_json = context_text.strip()
    context = json.loads(raw_json)
    results = context["runtime_policy"]["tool_results"]
    if results:
        raise ValueError("selected frozen sample already has tool_results")
    context["runtime_policy"]["tool_results"] = [copy.deepcopy(receipt)]
    return prefix + MARKER + compact(context)


def build_pairs() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected, _ = selected_samples()
    static, backend = load_receipts()
    originals = original_serialized_rows()
    pairs = []
    for sample in selected:
        sid, scenario = sample["sample_id"], sample["scenario_id"]
        row_a = copy.deepcopy(originals[sid])
        server = sample["input"]["server_context"]
        candidates = []
        for tool in server.get("enabled_tools", []):
            fixture = static.get((scenario, tool)) or backend.get((scenario, tool))
            if fixture:
                candidates.append(fixture)
        if len(candidates) != 1:
            raise ValueError(f"{sid}: expected one source fixture, got {len(candidates)}")
        fixture = candidates[0]
        receipt = copy.deepcopy(fixture["result"])
        row_b = copy.deepcopy(row_a)
        row_b["system"] = patch_system_receipt(row_a["system"], receipt)
        a_messages = row_a["conversations"][:-1]
        b_messages = row_b["conversations"][:-1]
        if a_messages != b_messages:
            raise ValueError(f"{sid}: conversation changed between A/B")
        if META.search(row_a["system"] + "\n" + "\n".join(m["content"] for m in a_messages)):
            raise ValueError(f"{sid}: metadata leakage in A")
        if META.search(row_b["system"] + "\n" + "\n".join(m["content"] for m in b_messages)):
            raise ValueError(f"{sid}: metadata leakage in B")
        expected_ids = server.get("verified_result_ids", [])
        old_id = fixture.get("legacy_result_id")
        new_id = receipt["result_id"]
        generated_at = server.get("generated_at")
        receipt_observed_at = receipt.get("observed_at")
        timestamp_conflict = bool(generated_at and receipt_observed_at and receipt_observed_at > generated_at)
        backend_mismatch = fixture in backend.values() and old_id != new_id
        if fixture in backend.values() and new_id not in {r["result_id"] for f in backend.values() for r in [f["result"]]}:
            raise ValueError(f"{sid}: backend receipt UUID not bound in fixture package")
        pairs.append({
            "sample_id": sid, "scenario_id": scenario, "split": sample["split"],
            "family_id": sample["scenario_family_id"], "fixture_kind": fixture["provenance"]["kind"] if "provenance" in fixture else "authoritative_backend_receipt",
            "tool": fixture["tool"], "legacy_result_id": old_id, "receipt_result_id": new_id,
            "expected_verified_result_ids": expected_ids, "backend_id_mismatch": backend_mismatch,
            "frozen_context_generated_at": generated_at, "receipt_observed_at_later_than_frozen_context": timestamp_conflict,
            "receipt": receipt, "fixture_provenance": fixture.get("provenance", {
                "kind": "authoritative_backend_receipt", "source_record_sha256": fixture.get("source_record_sha256"),
                "setup_sql_path": fixture.get("setup_sql_path"), "setup_sql_sha256": fixture.get("setup_sql_sha256"),
                "rpc": fixture.get("rpc"), "adapter": fixture.get("adapter"),
                "rollback_verified": fixture.get("rollback_verified"),
            }),
            "fixture": fixture, "A": row_a, "B": row_b,
            "A_serialized_sha256": hashlib.sha256((row_a["system"] + compact(a_messages)).encode("utf-8")).hexdigest(),
            "B_serialized_sha256": hashlib.sha256((row_b["system"] + compact(b_messages)).encode("utf-8")).hexdigest(),
        })
    return pairs, {"count": len(pairs), "unique_sample_ids": len({x["sample_id"] for x in pairs}),
                   "static_count": sum(x["fixture_kind"] == "new_frozen_document_read_fixture" for x in pairs),
                   "backend_count": sum(x["fixture_kind"] != "new_frozen_document_read_fixture" for x in pairs),
                   "backend_id_mismatch_count": sum(x["backend_id_mismatch"] for x in pairs),
                   "scenario_counts": dict(Counter(x["scenario_id"] for x in pairs)),
                   "tool_counts": dict(Counter(x["tool"] for x in pairs)),
                   "split_counts": dict(Counter(x["split"] for x in pairs))}


def source_hashes() -> dict[str, str]:
    paths = [
        V01 / "samples.json", V01 / "scenarios.json", V01 / "split_assignment.json", V01 / "dataset_manifest.json",
        SETUP / "manifest.json", SETUP / "traceability.json", SETUP / "llamafactory" / "train.json",
        SETUP / "llamafactory" / "validation.json", SETUP / "llamafactory" / "test.json", SETUP / "llamafactory" / "hard_test.json",
        ROOT / "docs/ai/AI_MODEL_CONTRACT.md", ROOT / "docs/ai/schema/model_output.schema.json",
        ROOT / "docs/ai/schema/tool_catalog.json", ROOT / "docs/ai/schema/intent_catalog.json",
        STATIC_DIR / "manifest.json", STATIC_DIR / "manifest.sha256", STATIC_DIR / "result_fixtures.json",
        STATIC_DIR / "fixture_registry.json", STATIC_DIR / "sample_rebuildability.json",
        BACKEND_DIR / "manifest.json", BACKEND_DIR / "manifest.sha256", BACKEND_DIR / "backend_result_fixtures.json",
        BACKEND_DIR / "batch_coverage.json", BACKEND_DIR / "result_id_registry.json",
    ]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}


def prepare() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pairs, counts = build_pairs()
    # Do not persist expected outputs in the inference input file. They are
    # joined after generation from the immutable canonical sample file.
    inference_pairs = [{k: v for k, v in row.items() if k not in {"fixture"}} for row in pairs]
    (OUT / "paired_inputs.json").write_text(json.dumps(inference_pairs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "experiment": "Experiment B Paired Grounding Diagnostic",
        "status": "preregistered_before_inference",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checkpoint": str(ADAPTER), "base_model": str(MODEL),
        "generation": GENERATION,
        "sample_selection": "39 rows where frozen source sample_rebuildability.rebuildable=true plus 9 rows where backend batch_coverage.reconstructable=true; unique IDs required.",
        "pair_rule": "A is the exact frozen v0.1 LLaMA-Factory serialized input. B changes only runtime_policy.tool_results by appending the exact authoritative fixture receipt. No verified_result_ids, enabled_tools, user/conversation/context, template or generation field changes.",
        "id_compatibility": "Static fixture IDs match frozen verified_result_ids. Backend receipt IDs are retained verbatim; old-to-new UUID relation is analysis-only and never supplied to the model. Original evaluator canonical ID equality remains authoritative; ID mismatch is an explicit backend confound.",
        "timestamp_limitation": "Receipts retain their actual observed_at values. They postdate the frozen v0.1 server_context.generated_at timestamp; timestamps are not rewritten. This event-time mismatch is an explicit limitation of all B pairs.",
        "prompt_length_limitation": "Record prompt_tokens per inference and report any prompt exceeding the frozen v0.1 cutoff_len=2048; generation parameters remain fixed.",
        "counts": counts,
        "pre_registered_decision": {"positive": POSITIVE, "negative": NEGATIVE, "weak": WEAK},
        "blocked_samples": "The 60 backend-blocked samples are excluded and remain blocked; no reconstruction attempted.",
        "source_hashes": source_hashes(),
        "harness_sha256": sha(Path(__file__)),
        "checkpoint_sha256": {p.name: sha(p) for p in ADAPTER.iterdir() if p.is_file()},
        "pair_build_integrity": {"all_pairs_only_receipt_diff": True, "metadata_leakage": 0},
        "evaluator": "scripts/ai_training_evaluation/evaluate_generation.py:evaluate_one, summarize; raw canonical identifiers remain unchanged.",
    }
    (OUT / "preregistration.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"prepared": counts, "preregistration": str(OUT / 'preregistration.json')}, ensure_ascii=False))


def infer() -> None:
    if not (OUT / "preregistration.json").exists():
        raise SystemExit("run --prepare first")
    sys.path.insert(0, str(LLAMAFACTORY))
    sys.path.insert(0, str(ROOT / "scripts/ai_training_evaluation"))
    import evaluate_generation as evaluator
    from llamafactory.chat import ChatModel

    pairs, _ = build_pairs()
    model = ChatModel({"model_name_or_path": str(MODEL), "trust_remote_code": True,
        "quantization_bit": 4, "quantization_method": "bnb", "quantization_type": "nf4", "double_quantization": True,
        "stage": "sft", "finetuning_type": "lora", "infer_backend": "huggingface", "template": TEMPLATE,
        "enable_thinking": False, "do_sample": False, "temperature": 0.0, "max_new_tokens": MAX_NEW_TOKENS,
        "adapter_name_or_path": str(ADAPTER)})
    schema = evaluator.load_json(evaluator.SCHEMA_PATH)
    catalog = evaluator.load_json(evaluator.CATALOG_PATH)
    intents = evaluator.load_json(evaluator.INTENT_PATH)
    samples = {x["sample_id"]: x for x in read_json(V01 / "samples.json")}
    out_path = OUT / "generation_records.jsonl"
    started = time.perf_counter()
    with out_path.open("w", encoding="utf-8") as out:
        for idx, pair in enumerate(pairs, 1):
            sample = samples[pair["sample_id"]]
            expected = sample["expected"]
            for arm in ("A", "B"):
                row = pair[arm]
                begin = time.perf_counter()
                response = model.chat(row["conversations"][:-1], system=row["system"], max_new_tokens=MAX_NEW_TOKENS,
                                      do_sample=False, temperature=0.0)[0]
                latency = time.perf_counter() - begin
                raw = response.response_text
                parsed, strict_ok, extract_ok, span, duplicate_keys = evaluator.json_parse(raw)
                evaluation = evaluator.evaluate_one(parsed if extract_ok else None, expected, schema, catalog, intents, duplicate_keys)
                record = {
                    "sample_id": pair["sample_id"], "scenario_id": pair["scenario_id"], "split": pair["split"],
                    "output_type": expected["output_type"], "difficulty": sample["difficulty"],
                    "task": sample["task"], "challenge_tags": sample["challenge_tags"],
                    "arm": arm, "fixture_kind": pair["fixture_kind"], "tool": pair["tool"],
                    "legacy_result_id": pair["legacy_result_id"], "receipt_result_id": pair["receipt_result_id"],
                    "authoritative_receipt": pair["receipt"], "fixture_provenance": pair["fixture_provenance"],
                    "expected_verified_result_ids": pair["expected_verified_result_ids"], "backend_id_mismatch": pair["backend_id_mismatch"],
                    "frozen_context_generated_at": pair["frozen_context_generated_at"],
                    "receipt_observed_at_later_than_frozen_context": pair["receipt_observed_at_later_than_frozen_context"],
                    "raw_output": raw, "raw_json_parse_ok": strict_ok, "extractable_json_parse_ok": extract_ok,
                    "json_extract_span": span, "parsed_output": parsed, "expected_output": expected["model_output"],
                    "generation": {**GENERATION, "prompt_tokens": response.prompt_length,
                                   "generated_tokens": response.response_length, "finish_reason": response.finish_reason,
                                   "latency_seconds": latency},
                    "evaluation": evaluation,
                }
                out.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                out.flush()
                print(json.dumps({"pair": idx, "sample_id": pair["sample_id"], "arm": arm,
                                  "tokens": response.response_length, "seconds": round(latency, 2),
                                  "schema": evaluation["schema_valid"], "type": evaluation["actual_type"],
                                  "safe": evaluation["contract_safe"]}, ensure_ascii=False), flush=True)
    print(json.dumps({"inferences": 96, "elapsed_seconds": time.perf_counter() - started,
                      "records": str(out_path)}, ensure_ascii=False))


def score() -> None:
    sys.path.insert(0, str(ROOT / "scripts/ai_training_evaluation"))
    import evaluate_generation as evaluator
    samples = {x["sample_id"]: x for x in read_json(V01 / "samples.json")}
    lines = [json.loads(x) for x in (OUT / "generation_records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    for row in lines:
        sample = samples[row["sample_id"]]
        row["output_type"] = sample["expected"]["output_type"]
        row["difficulty"] = sample["difficulty"]
        row["task"] = sample["task"]
        row["challenge_tags"] = sample["challenge_tags"]
    grouped: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in lines:
        grouped[row["sample_id"]][row["arm"]] = row
    if len(grouped) != 48 or any(set(x) != {"A", "B"} for x in grouped.values()):
        raise ValueError(f"incomplete pairs: {len(grouped)}")
    for arm in ("A", "B"):
        arm_records = [grouped[sid][arm] for sid in grouped]
        (OUT / f"{arm.lower()}_evaluator_summary.json").write_text(json.dumps(evaluator.summarize(arm_records), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pair_reviews = []
    categories = Counter()
    for sid, arms in grouped.items():
        a, b = arms["A"], arms["B"]
        ea, eb = a["evaluation"], b["evaluation"]
        if ea["field_facts_correct"] < eb["field_facts_correct"]: fact = "improved"
        elif ea["field_facts_correct"] > eb["field_facts_correct"]: fact = "regressed"
        else: fact = "unchanged"
        categories[f"fact_{fact}"] += 1
        for metric in ("schema_valid", "type_correct", "normalized_business_structure_match", "contract_safe"):
            categories[f"{metric}_{'improved' if not ea[metric] and eb[metric] else 'regressed' if ea[metric] and not eb[metric] else 'unchanged'}"] += 1
        exp = samples[sid]["expected"]["model_output"]
        def receipt_citation(output: Any, ids: list[str]) -> bool:
            if not isinstance(output, dict): return False
            cited = output.get("evidence_result_ids") or []
            return any(x in cited for x in ids)
        pair_reviews.append({
            "sample_id": sid, "scenario_id": a["scenario_id"], "split": a["split"], "fixture_kind": a["fixture_kind"],
            "tool": a["tool"], "backend_id_mismatch": a["backend_id_mismatch"],
            "expected_type": exp.get("type"), "A": {"raw": a["raw_output"], "parsed": a["parsed_output"], "evaluation": ea},
            "B": {"raw": b["raw_output"], "parsed": b["parsed_output"], "evaluation": eb},
            "changes": {"schema": [ea["schema_valid"], eb["schema_valid"]], "type": [ea["type_correct"], eb["type_correct"]],
                        "business_structure": [ea["normalized_business_structure_match"], eb["normalized_business_structure_match"]],
                        "field_facts": [ea["field_facts_correct"], eb["field_facts_correct"]],
                        "key_facts": [ea["key_facts_correct"], eb["key_facts_correct"]],
                        "safety": [ea["contract_safe"], eb["contract_safe"]]},
            "citation": {"A_legacy_id_cited": receipt_citation(a["parsed_output"], a["expected_verified_result_ids"]),
                         "B_legacy_id_cited": receipt_citation(b["parsed_output"], b["expected_verified_result_ids"]),
                         "B_actual_receipt_id_cited": receipt_citation(b["parsed_output"], [b["receipt_result_id"]])},
            "receipt_copying_review_required": True,
            "unsupported_fact_review_required": True,
            "human_fact_grounding_review": "pending_manual_review",
        })
    (OUT / "pair_reviews.json").write_text(json.dumps(pair_reviews, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"pairs": len(pair_reviews), "transition_counts": dict(sorted(categories.items())),
               "scenario_summary": {}, "backend_id_confounds": sum(x["backend_id_mismatch"] for x in pair_reviews),
               "decision": "pending_manual_fact_grounding_review"}
    for scenario in sorted({x["scenario_id"] for x in pair_reviews}):
        rows = [x for x in pair_reviews if x["scenario_id"] == scenario]
        improve = sum(x["changes"]["key_facts"][1] > x["changes"]["key_facts"][0] for x in rows)
        regress = sum(x["changes"]["key_facts"][1] < x["changes"]["key_facts"][0] for x in rows)
        summary["scenario_summary"][scenario] = {"rows": len(rows), "key_fact_improved_rows": improve,
                                                  "key_fact_regressed_rows": regress,
                                                  "schema_valid_A": sum(x["A"]["evaluation"]["schema_valid"] for x in rows),
                                                  "schema_valid_B": sum(x["B"]["evaluation"]["schema_valid"] for x in rows),
                                                  "unsafe_A": sum(not x["A"]["evaluation"]["contract_safe"] for x in rows),
                                                  "unsafe_B": sum(not x["B"]["evaluation"]["contract_safe"] for x in rows)}
    (OUT / "automated_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "infer", "score"])
    args = parser.parse_args()
    {"prepare": prepare, "infer": infer, "score": score}[args.mode]()


if __name__ == "__main__":
    main()
