#!/usr/bin/env python3
"""Static, local-only validation of the Experiment A-only SFT export through LLaMA-Factory."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "docs/ai/dataset/canonical_training/v0.2_experiment_a_only"
V1 = ROOT / "docs/ai/dataset/canonical_training/v0.1"
A = ROOT / "docs/ai/dataset/business_state_expansion/v0.2/experiment_a"
SETUP = ROOT / "docs/ai/training_setup/v0.2_experiment_a_only"
DATA_DIR = SETUP / "llamafactory"
OLD_SETUP = ROOT / "docs/ai/training_setup/v0.1"
MODEL = Path(r"D:\AI\models\Qwen3.5-4B")
LLAMA_SRC = Path(r"D:\AI\LlamaFactory\src")
sys.path.insert(0, str(LLAMA_SRC))
sys.path.insert(0, str(ROOT / "scripts/ai_training_setup"))
sys.path.insert(0, str(ROOT / "scripts/ai_dataset_validator"))

from export_dataset import export_record  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def stats(values: list[int]):
    pct = np.percentile(np.asarray(values, dtype=np.int64), [50, 90, 95, 99])
    return {"count": len(values), "p50": int(round(pct[0])), "p90": int(round(pct[1])),
            "p95": int(round(pct[2])), "p99": int(round(pct[3])), "max": max(values)}


def main() -> None:
    from datasets import load_dataset
    from transformers import AutoProcessor
    import llamafactory
    from llamafactory.data.converter import align_dataset
    from llamafactory.data.parser import get_dataset_list
    from llamafactory.data.processor.supervised import SupervisedDatasetProcessor
    from llamafactory.data.template import get_template_and_fix_tokenizer
    from llamafactory.extras.constants import IGNORE_INDEX

    samples = read(CANONICAL / "samples.json")
    by_id = {x["sample_id"]: x for x in samples}
    trace_rows = read(SETUP / "traceability.json")
    old_trace_rows = read(OLD_SETUP / "traceability.json")
    old_train_traces = [x for x in old_trace_rows if x["split"] == "train"]
    old_val_traces = [x for x in old_trace_rows if x["split"] == "validation"]
    a_traces = [x for x in trace_rows if x["split"] == "train" and
                x["sample_id"] in {s["sample_id"] for s in read(A / "samples.json")}]
    seen = set()

    # Preserve immutable source artifacts and the historical v1 assignments byte-for-byte.
    for name in ("samples.json", "scenarios.json", "split_assignment.json"):
        src = V1 / name
        expected = read(CANONICAL / name)
        original = read(src)
        if name == "samples.json":
            old_map = {x["sample_id"]: x for x in expected}
            for row in original:
                copy = old_map[row["sample_id"]]
                if copy != row:
                    raise AssertionError(f"v1 Sample changed in the assembled snapshot: {row['sample_id']}")
        elif name == "scenarios.json":
            old_map = {x["scenario_id"]: x for x in expected}
            for row in original:
                copy = old_map[row["scenario_id"]]
                before = dict(copy)
                before["split"] = row["split"]
                if before != row:
                    raise AssertionError(f"v1 Scenario content changed beyond split snapshot assignment: {row['scenario_id']}")
        else:
            if expected[:len(original)] != original:
                raise AssertionError("v1 split assignments are not an unchanged prefix")
    if (SETUP / "llamafactory/validation.json").read_bytes() != (OLD_SETUP / "llamafactory/validation.json").read_bytes():
        raise AssertionError("v0.1 validation export is not byte-identical")

    old_train = read(OLD_SETUP / "llamafactory/train.json")
    train_rows = read(DATA_DIR / "train.json")
    if train_rows[:len(old_train)] != old_train or len(old_train) != 171 or len(train_rows) != 187:
        raise AssertionError("Frozen v1 train rows are not exactly preserved as the training prefix")
    a_samples = read(A / "samples.json")
    for idx, sample in enumerate(a_samples):
        generated, _ = export_record(sample)
        if train_rows[171 + idx] != generated:
            raise AssertionError(f"A serializer output mismatch for {sample['sample_id']}")

    # Verify only the allowed registration/path changes in the actual YAML config.
    import yaml
    v1_config = yaml.safe_load((OLD_SETUP / "qlora.yaml").read_text(encoding="utf-8"))
    config = yaml.safe_load((SETUP / "qlora.yaml").read_text(encoding="utf-8"))
    allowed = {"dataset", "dataset_dir", "eval_dataset", "output_dir"}
    if set(config) != set(v1_config):
        raise AssertionError("Training configuration key set differs from frozen v0.1")
    changed = {key for key in config if config[key] != v1_config[key]}
    if changed != allowed:
        raise AssertionError(f"Unexpected QLoRA field changes: {sorted(changed ^ allowed)}")
    if (config["dataset"], config["eval_dataset"]) != ("sharedledger_a_only_train", "sharedledger_a_only_validation"):
        raise AssertionError("Wrong A-only dataset registration")
    if config["dataset_dir"] != DATA_DIR.as_posix():
        raise AssertionError("New QLoRA dataset_dir does not point to A-only export")
    if "v0.2-experiment-a-only" not in config["output_dir"]:
        raise AssertionError("Output directory is not isolated to the A-only setup")

    data_args = SimpleNamespace(template="qwen3_5_nothink", train_on_prompt=False, tool_format=None,
        default_system=None, enable_thinking=False, preserve_thinking=None, reasoning_effort="low",
        mask_history=True, cutoff_len=2048, streaming=False, preprocessing_num_workers=1,
        overwrite_cache=True)
    model_processor = AutoProcessor.from_pretrained(str(MODEL), local_files_only=True, trust_remote_code=True)
    tokenizer = model_processor.tokenizer
    template = get_template_and_fix_tokenizer(tokenizer, data_args)
    registered = get_dataset_list(["sharedledger_a_only_train", "sharedledger_a_only_validation"], str(DATA_DIR))
    if len(registered) != 2:
        raise AssertionError(f"Expected two registered datasets, got {len(registered)}")
    training_args = SimpleNamespace(local_process_index=0)
    counts = Counter()
    lengths = defaultdict(list)
    input_lengths = defaultdict(list)
    target_lengths = defaultdict(list)
    rows_loaded = 0
    loss_mask_checked = 0
    metadata_leaks = 0
    target_truncations = 0
    histories = 0
    for attr in registered:
        path = DATA_DIR / attr.dataset_name
        raw = load_dataset("json", data_files=str(path), split="train")
        aligned = align_dataset(raw, attr, data_args, training_args)
        processor = SupervisedDatasetProcessor(template, tokenizer, model_processor, data_args)
        processed = processor.preprocess_dataset({k: aligned[k] for k in aligned.column_names})
        if len(processed["input_ids"]) != len(raw):
            raise AssertionError(f"LLaMA-Factory dropped rows from {attr.dataset_name}")
        split = attr.dataset_name.removesuffix(".json")
        for idx, row in enumerate(raw):
            target_text = row["conversations"][-1]["content"]
            target_sha = hashlib.sha256(target_text.encode("utf-8")).hexdigest()
            if split == "validation":
                trace = old_val_traces[idx]
            elif idx < 171:
                trace = old_train_traces[idx]
            else:
                trace = a_traces[idx - 171]
            if trace["canonical_expected_sha256"] != target_sha:
                raise AssertionError(f"Target hash disagrees with row-order source trace for {split} row {idx}")
            sid = trace["sample_id"]
            seen.add(sid)
            source = by_id.get(sid)
            if not source or source["split"] != split:
                raise AssertionError(f"Invalid source trace/split for {sid}")
            if json.loads(target_text) != source["expected"]["model_output"]:
                raise AssertionError(f"Serialized target differs from canonical Ground Truth: {sid}")
            if trace.get("scenario_id") != source["scenario_id"] or trace.get("scenario_family_id") != source["scenario_family_id"]:
                raise AssertionError(f"Source identity mismatch for {sid}")
            visible = row["system"] + "\n" + "\n".join(m["content"] for m in row["conversations"])
            for key in (sid, source["scenario_id"], source["scenario_family_id"], source["split_group_id"]):
                if key in visible:
                    metadata_leaks += 1
            messages = [{"role": m["role"], "content": m["content"]} for m in row["conversations"]]
            encoded_pairs = template.encode_multiturn(tokenizer, messages, row["system"], None)
            source_count = sum(len(src) for src, _ in encoded_pairs) + sum(len(tgt) for _, tgt in encoded_pairs[:-1])
            expected_target = encoded_pairs[-1][1]
            total = source_count + len(expected_target)
            input_ids = processed["input_ids"][idx]
            labels = processed["labels"][idx]
            unmasked = [token for token in labels if token != IGNORE_INDEX]
            if unmasked != expected_target:
                raise AssertionError(f"Prompt/history mask or assistant target mismatch for {sid}")
            if not unmasked:
                raise AssertionError(f"No supervised target tokens for {sid}")
            if len(input_ids) != total:
                if len(input_ids) < total:
                    target_truncations += 1
                    raise AssertionError(f"The configured 2048 cutoff truncates sample {sid}: {total} tokens")
                raise AssertionError(f"Unexpected LLaMA-Factory/tokenizer length disagreement for {sid}: {len(input_ids)} != {total}")
            if total > 2048:
                raise AssertionError(f"Sample exceeds cutoff 2048: {sid} ({total})")
            counts[split] += 1
            lengths[split].append(total)
            input_lengths[split].append(source_count)
            target_lengths[split].append(len(expected_target))
            loss_mask_checked += 1
            rows_loaded += 1
            histories += bool(source.get("surface_form", {}).get("conversation"))
    if rows_loaded != 211 or loss_mask_checked != 211 or len(seen) != 211:
        raise AssertionError(f"Expected 211 unique source rows and loss masks, got {rows_loaded}/{loss_mask_checked}/{len(seen)}")
    if counts != Counter({"train": 187, "validation": 24}):
        raise AssertionError(f"Wrong LLaMA-Factory loaded split counts: {counts}")
    if metadata_leaks or target_truncations:
        raise AssertionError(f"Metadata leaks={metadata_leaks}, cutoff truncations={target_truncations}")

    report = {
        "status": "passed", "scope": "static local data validation only", "training_performed": False,
        "api_teacher_inference_optimizer_or_model_load": False,
        "python": sys.version.split()[0], "transformers": __import__("transformers").__version__,
        "llamafactory": llamafactory.__version__, "model_tokenizer_path": str(MODEL),
        "tokenizer_loaded_local_only": True, "template": "qwen3_5_nothink", "cutoff_len": 2048,
        "registered_datasets": [x.dataset_name for x in registered], "counts": dict(counts),
        "rows_loaded": rows_loaded, "ground_truth_equal": rows_loaded, "source_trace_unique": rows_loaded,
        "metadata_leaks": metadata_leaks, "loss_masks_verified": loss_mask_checked,
        "mask_config": {"train_on_prompt": False, "mask_history": True},
        "history_rows": sum(1 for x in samples if x["split"] in {"train", "validation"} and x.get("surface_form", {}).get("conversation")),
        "token_lengths_by_split": {k: stats(v) for k, v in lengths.items()},
        "input_tokens_by_split": {k: stats(v) for k, v in input_lengths.items()},
        "target_tokens_by_split": {k: stats(v) for k, v in target_lengths.items()},
        "max_total_tokens": max(max(v) for v in lengths.values()), "truncations": target_truncations,
        "v1_train_serialization_equal": len(old_train), "v1_validation_byte_sha256": sha(SETUP / "llamafactory/validation.json"),
        "experiment_a_serialization_equal": len(a_samples), "qlora_changed_fields": sorted(changed),
        "qlora_unchanged_parameter_count": len(config) - len(changed),
        "source_hashes": {"v1_samples": sha(V1 / "samples.json"), "v1_scenarios": sha(V1 / "scenarios.json"),
            "v1_split_assignment": sha(V1 / "split_assignment.json"), "v1_canonical_manifest": sha(V1 / "dataset_manifest.json"),
            "v1_setup_manifest": sha(OLD_SETUP / "manifest.json"), "v1_setup_qlora": sha(OLD_SETUP / "qlora.yaml"),
            "experiment_a_samples": sha(A / "samples.json"), "experiment_a_scenarios": sha(A / "scenarios.json"),
            "experiment_a_manifest": sha(A / "dataset_manifest.json"), "experiment_a_freeze_hashes": sha(A / "freeze_hashes.json")},
    }
    report_path = SETUP / "validation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
