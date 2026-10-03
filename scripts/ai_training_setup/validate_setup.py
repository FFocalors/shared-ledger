#!/usr/bin/env python3
"""Validate the exported LLaMA-Factory dataset and report full tokenizer lengths."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/training_setup/v0.1"
DATA_DIR = OUT / "llamafactory"
CANONICAL = ROOT / "docs/ai/dataset/canonical_training/v0.1"
MODEL = Path(r"D:\AI\models\Qwen3.5-4B")
LLAMA_SRC = Path(r"D:\AI\LlamaFactory\src")
sys.path.insert(0, str(LLAMA_SRC))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stats(values: list[int]) -> dict[str, int]:
    pct = np.percentile(np.asarray(values, dtype=np.int64), [50, 90, 95, 99])
    return {"count": len(values), "p50": int(round(pct[0])), "p90": int(round(pct[1])),
            "p95": int(round(pct[2])), "p99": int(round(pct[3])), "max": max(values)}


def main() -> None:
    from datasets import load_dataset
    from transformers import AutoProcessor
    from llamafactory.data.converter import align_dataset
    from llamafactory.data.parser import get_dataset_list
    from llamafactory.data.processor.supervised import SupervisedDatasetProcessor
    from llamafactory.data.template import get_template_and_fix_tokenizer
    from llamafactory.extras.constants import IGNORE_INDEX

    canonical = read(CANONICAL / "samples.json")
    canonical_manifest = read(CANONICAL / "dataset_manifest.json")
    for artifact in canonical_manifest.get("artifacts", []):
        if artifact.get("path") in {"samples.json", "scenarios.json", "split_assignment.json", "coverage_report.json"}:
            actual = sha(CANONICAL / artifact["path"])
            if actual != artifact["sha256"]:
                raise AssertionError(f"frozen artifact hash mismatch: {artifact['path']}")
    original = {x["sample_id"]: x for x in canonical if x["split"] != "unassigned"}
    trace_rows = read(OUT / "traceability.json")
    traces = {x["sample_id"]: x for x in trace_rows}
    data_args = SimpleNamespace(
        template="qwen3_5_nothink", train_on_prompt=False, tool_format=None, default_system=None,
        enable_thinking=False, preserve_thinking=None, reasoning_effort="low", mask_history=True,
        cutoff_len=8192, streaming=False, preprocessing_num_workers=1, overwrite_cache=True,
    )
    model_processor = AutoProcessor.from_pretrained(str(MODEL), local_files_only=True, trust_remote_code=True)
    tokenizer = model_processor.tokenizer
    template = get_template_and_fix_tokenizer(tokenizer, data_args)
    training_args = SimpleNamespace(local_process_index=0)

    registered = get_dataset_list(
        ["sharedledger_train", "sharedledger_validation", "sharedledger_test", "sharedledger_hard_test"],
        str(DATA_DIR),
    )
    if len(registered) != 4:
        raise AssertionError(f"expected 4 registered splits, found {len(registered)}")
    counts: Counter[str] = Counter()
    lengths: dict[str, list[int]] = defaultdict(list)
    type_lengths: dict[str, list[int]] = defaultdict(list)
    type_input_lengths: dict[str, list[int]] = defaultdict(list)
    type_target_lengths: dict[str, list[int]] = defaultdict(list)
    native_template_lengths: list[int] = []
    aggregate: dict[str, Any] = {}
    history_count = 0
    assistant_history_count = 0
    grouped_count = 0
    loss_checked = 0
    for attr in registered:
        path = DATA_DIR / attr.dataset_name
        raw_rows = load_dataset("json", data_files=str(path), split="train")
        if len(raw_rows) == 0:
            raise AssertionError(f"empty split {attr.dataset_name}")
        aligned = align_dataset(raw_rows, attr, data_args, training_args)
        processor = SupervisedDatasetProcessor(template, tokenizer, model_processor, data_args)
        processed = processor.preprocess_dataset({k: aligned[k] for k in aligned.column_names})
        if len(processed["input_ids"]) != len(raw_rows):
            raise AssertionError(f"processor dropped records in {attr.dataset_name}")
        local: dict[str, list[int]] = defaultdict(list)
        split_name = attr.dataset_name.removesuffix(".json")
        rows = list(raw_rows)
        for idx, row in enumerate(rows):
            candidates = [t for t in trace_rows if t["split"] == split_name and
                          t["canonical_expected_sha256"] == hashlib.sha256(row["conversations"][-1]["content"].encode("utf-8")).hexdigest()]
            if not candidates:
                raise AssertionError(f"no trace for {split_name} row {idx}")
            trace = candidates[0] if len(candidates) == 1 else next(
                (t for t in candidates if t["sample_id"] not in aggregate.get("seen_ids", set())), candidates[0])
            sample_id = trace["sample_id"]
            aggregate.setdefault("seen_ids", set()).add(sample_id)
            source = original.get(sample_id)
            if source is None or source["split"] != split_name:
                raise AssertionError(f"bad source/split trace: {sample_id}/{split_name}")
            target = row["conversations"][-1]["content"]
            if json.loads(target) != source["expected"]["model_output"]:
                raise AssertionError(f"Ground Truth changed: {sample_id}")
            if trace["scenario_id"] != source["scenario_id"] or trace["scenario_family_id"] != source["scenario_family_id"]:
                raise AssertionError(f"trace identity mismatch: {sample_id}")
            if trace["history_roundtrip_verified"] is not True:
                raise AssertionError(f"history roundtrip not verified: {sample_id}")
            visible = row["system"] + "\n" + "\n".join(m["content"] for m in row["conversations"])
            for key in (sample_id, source["scenario_id"], source["scenario_family_id"], source["split_group_id"]):
                if key in visible:
                    raise AssertionError(f"metadata leaked into model input: {sample_id}: {key}")
            messages = [{"role": m["role"], "content": m["content"]} for m in row["conversations"]]
            prompt, response = messages[:-1], messages[-1:]
            encoded_pairs = template.encode_multiturn(tokenizer, prompt + response, row["system"], None)
            input_tokens = sum(len(src) for src, _ in encoded_pairs) + sum(len(tgt) for _, tgt in encoded_pairs[:-1])
            target_tokens = len(encoded_pairs[-1][1])
            total_tokens = input_tokens + target_tokens
            labels = processed["labels"][idx]
            nonignored = [token for token in labels if token != IGNORE_INDEX]
            expected_target = encoded_pairs[-1][1]
            if nonignored != expected_target:
                raise AssertionError(f"loss mask or target mismatch: {sample_id}")
            if len(nonignored) == 0:
                raise AssertionError(f"empty assistant loss: {sample_id}")
            # Official LLaMA-Factory processor uses IGNORE_INDEX for source/system/history under this config.
            loss_checked += 1
            counts[split_name] += 1
            lengths[split_name].append(total_tokens)
            lengths[f"{split_name}_input"].append(input_tokens)
            lengths[f"{split_name}_target"].append(target_tokens)
            type_name = trace["output_type"]
            type_lengths[type_name].append(total_tokens)
            type_input_lengths[type_name].append(input_tokens)
            type_target_lengths[type_name].append(target_tokens)
            local["total"].append(total_tokens)
            if source["surface_form"].get("conversation"):
                history_count += 1
                assistant_history_count += sum(1 for message in source["surface_form"]["conversation"]
                                               if message["role"] == "assistant")
            if any(p.get("reversible_block") for p in trace["packed_turns"]):
                grouped_count += 1
            if tokenizer.chat_template:
                rendered = tokenizer.apply_chat_template(
                    [{"role": "system", "content": row["system"]}] + messages,
                    tokenize=True, add_generation_prompt=False,
                )
                native_template_lengths.append(len(rendered["input_ids"]))
        aggregate[split_name] = {"count": len(rows), "total_tokens": stats(local["total"])}

    if loss_checked != 244 or len(aggregate["seen_ids"]) != 244:
        raise AssertionError(f"expected 244 unique validated samples/loss masks, got {loss_checked}/{len(aggregate['seen_ids'])}")
    if sum(counts.values()) != 244 or counts != Counter({"train": 171, "validation": 24, "test": 37, "hard_test": 12}):
        raise AssertionError(f"split count mismatch: {counts}")
    overall = lengths["train"] + lengths["validation"] + lengths["test"] + lengths["hard_test"]
    overall_input = sum((lengths[f"{split}_input"] for split in ("train", "validation", "test", "hard_test")), [])
    overall_target = sum((lengths[f"{split}_target"] for split in ("train", "validation", "test", "hard_test")), [])
    report = {
        "python": sys.version.split()[0], "transformers": __import__("transformers").__version__,
        "llamafactory": __import__("llamafactory").__version__, "model_tokenizer_path": str(MODEL),
        "template": "qwen3_5_nothink", "dataset_registration_count": len(registered),
        "split_counts": dict(counts), "loss_mask_samples_checked": loss_checked,
        "history_samples": history_count, "samples_with_reversible_turn_blocks": grouped_count,
        "assistant_history_turns_masked": assistant_history_count,
        "token_lengths_total": stats(overall),
        "input_tokens_total": stats(overall_input), "target_tokens_total": stats(overall_target),
        "native_tokenizer_template_total": stats(native_template_lengths),
        "native_vs_llamafactory_template_delta": {
            "samples_with_different_lengths": sum(a != b for a, b in zip(overall, native_template_lengths)),
            "delta_min": min(b - a for a, b in zip(overall, native_template_lengths)),
            "delta_max": max(b - a for a, b in zip(overall, native_template_lengths)),
            "note": "Training config uses the LLaMA-Factory qwen3_5_nothink encoder; the tokenizer's bundled chat_template is measured separately.",
        },
        "token_lengths_by_split": {k: stats(lengths[k]) for k in ("train", "validation", "test", "hard_test")},
        "input_tokens_by_split": {k: stats(lengths[f"{k}_input"]) for k in ("train", "validation", "test", "hard_test")},
        "target_tokens_by_split": {k: stats(lengths[f"{k}_target"]) for k in ("train", "validation", "test", "hard_test")},
        "total_tokens_by_output_type": {k: stats(v) for k, v in sorted(type_lengths.items())},
        "input_tokens_by_output_type": {k: stats(v) for k, v in sorted(type_input_lengths.items())},
        "target_tokens_by_output_type": {k: stats(v) for k, v in sorted(type_target_lengths.items())},
        "max_total_tokens": max(overall), "cutoff_candidates": [2048],
        "excluded_unassigned": 6, "excluded_fin002": 0,
        "frozen_hashes": {p.name: sha(p) for p in [CANONICAL / "samples.json", CANONICAL / "scenarios.json",
                                                       CANONICAL / "split_assignment.json", CANONICAL / "dataset_manifest.json"]},
        "source_code_evidence": {
            "sharegpt_converter": "LLaMA-Factory/src/llamafactory/data/converter.py:SharegptDatasetConverter",
            "supervised_loss_mask": "LLaMA-Factory/src/llamafactory/data/processor/supervised.py:SupervisedDatasetProcessor._encode_data_example",
            "qwen_template": "LLaMA-Factory/src/llamafactory/data/template.py:qwen3_5_nothink",
        },
    }
    aggregate.pop("seen_ids", None)
    report["counts"] = dict(counts)
    report["llamafactory_loader_rows"] = 244
    (OUT / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    export_manifest = read(OUT / "manifest.json")
    export_manifest.setdefault("artifacts", {})["validation_report.json"] = sha(OUT / "validation_report.json")
    export_manifest["validation"] = {
        "rows_loaded": 244, "ground_truth_equal": 244, "traceability_complete": 244,
        "metadata_leakage": 0, "loss_masks_verified": 244, "errors": 0,
        "loss_mask_config": {"train_on_prompt": False, "mask_history": True},
    }
    (OUT / "manifest.json").write_text(json.dumps(export_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
