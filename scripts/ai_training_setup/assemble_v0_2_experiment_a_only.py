#!/usr/bin/env python3
"""Assemble the frozen v1 corpus plus approved Experiment A samples into a new snapshot."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "docs/ai/dataset/canonical_training/v0.1"
A = ROOT / "docs/ai/dataset/business_state_expansion/v0.2/experiment_a"
OUT = ROOT / "docs/ai/dataset/canonical_training/v0.2_experiment_a_only"
SETUP = ROOT / "docs/ai/training_setup/v0.2_experiment_a_only"
OLD_SETUP = ROOT / "docs/ai/training_setup/v0.1"
EXPORTER = ROOT / "scripts/ai_training_setup/export_dataset.py"

sys.path.insert(0, str(EXPORTER.parent))
from export_dataset import export_record  # noqa: E402


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stats(scenarios, samples):
    return {
        "splits": dict(Counter(s.get("split", "unassigned") for s in samples)),
        "tasks": dict(Counter(s.get("task", {}).get("primary", "unknown") for s in samples)),
        "scopes": dict(Counter(s.get("scope", {}).get("ai_scope", "unknown") for s in samples)),
        "sources": dict(Counter("manual" if s.get("source", {}).get("surface_form_type") == "human_authored" else s.get("source", {}).get("surface_form_type", "unknown") for s in samples)),
        "trust": {k: sum(s.get("trust", {}).get("level") == k for s in samples) for k in ("GOLD", "SILVER", "SYNTHETIC_UNVERIFIED")},
        "difficulty": {k: sum(s.get("difficulty") == k for s in samples) for k in ("easy", "normal", "hard", "ood")},
        "lifecycle": {k: sum(s.get("dataset_metadata", {}).get("lifecycle_status") == k for s in samples) for k in ("draft", "generated", "validated", "reviewed", "approved", "rejected", "deprecated")},
    }


def main():
    if OUT.exists() or SETUP.exists():
        raise SystemExit("Refusing to overwrite an existing A-only dataset or setup directory.")
    v1_samples, v1_scenarios = read(V1 / "samples.json"), read(V1 / "scenarios.json")
    a_samples, a_scenarios = read(A / "samples.json"), read(A / "scenarios.json")
    v1_assignment = read(V1 / "split_assignment.json")
    a_manifest = read(A / "dataset_manifest.json")
    if len(v1_samples) != 250 or len(a_samples) != 16 or any(x.get("split") != "unassigned" for x in a_samples):
        raise SystemExit("Frozen input counts or original Experiment A split state changed.")
    if a_manifest.get("status") != "frozen" or len(a_manifest.get("artifacts", [])) == 0:
        raise SystemExit("Experiment A source is not a frozen, manifested Dataset.")

    samples = copy.deepcopy(v1_samples)
    for sample in copy.deepcopy(a_samples):
        sample["split"] = "train"
        samples.append(sample)
    if len({s["sample_id"] for s in samples}) != 266:
        raise SystemExit("Sample IDs are not unique across the assembled corpus.")
    split_by_scenario = {}
    for sample in samples:
        prior = split_by_scenario.setdefault(sample["scenario_id"], sample["split"])
        if prior != sample["split"]:
            raise SystemExit(f"A scenario crosses splits: {sample['scenario_id']}")
    scenarios = copy.deepcopy(v1_scenarios) + copy.deepcopy(a_scenarios)
    if len({s["scenario_id"] for s in scenarios}) != 70:
        raise SystemExit("Scenario IDs are not unique or scenario count is wrong.")
    for scenario in scenarios:
        scenario["split"] = split_by_scenario.get(scenario["scenario_id"], "unassigned")
    stat = stats(scenarios, samples)
    expected_splits = {"train": 187, "validation": 24, "test": 37, "hard_test": 12, "unassigned": 6}
    if {key: stat["splits"].get(key, 0) for key in expected_splits} != expected_splits:
        raise SystemExit(f"Unexpected split totals: {stat['splits']}")
    OUT.mkdir(parents=True)
    dump(OUT / "samples.json", samples)
    dump(OUT / "scenarios.json", scenarios)

    v1_split = {x["sample_id"]: x for x in v1_assignment}
    a_hashes = {x["path"]: x["sha256"] for x in a_manifest["artifacts"]}
    assignment = []
    reconciliation = []
    a_sample_ids = {sample["sample_id"] for sample in a_samples}
    for sample in samples:
        sid = sample["sample_id"]
        is_a = sid in a_sample_ids
        if is_a:
            source = {"source_dataset": "docs/ai/dataset/business_state_expansion/v0.2/experiment_a",
                      "source_dataset_manifest_sha256": sha(A / "dataset_manifest.json"),
                      "source_samples_sha256": a_hashes["samples.json"],
                      "source_scenarios_sha256": a_hashes["scenarios.json"], "source_sample_id": sid}
        else:
            source = copy.deepcopy(v1_split[sid])
            source["split"] = sample["split"]
            source = {key: source[key] for key in ("source_dataset", "source_dataset_manifest_sha256", "source_samples_sha256", "source_scenarios_sha256", "source_sample_id")}
        record = {**source, "sample_id": sid, "scenario_id": sample["scenario_id"],
                  "scenario_family_id": sample["scenario_family_id"], "split_group_id": sample["split_group_id"],
                  "split": sample["split"], "policy_status": sample.get("policy_status", "active")}
        assignment.append(record)
        reconciliation.append({"source_sample_id": sid, "source_dataset": source["source_dataset"],
                               "source_samples_sha256": source["source_samples_sha256"],
                               "scenario_id": sample["scenario_id"], "scenario_family_id": sample["scenario_family_id"],
                               "split_group_id": sample["split_group_id"], "split": sample["split"]})
    dump(OUT / "split_assignment.json", assignment)
    dump(OUT / "source_reconciliation.json", reconciliation)

    old_manifest = read(V1 / "dataset_manifest.json")
    manifest = copy.deepcopy(old_manifest)
    manifest.update({"status": "validated",
                     "scenario_count": len(scenarios), "scenario_family_count": len({s["scenario_family_id"] for s in scenarios}),
                     "sample_count": len(samples), "split_statistics": {key: stat["splits"].get(key, 0) for key in expected_splits},
                     "task_statistics": stat["tasks"], "scope_statistics": {k: stat["scopes"].get(k, 0) for k in ("CORE", "SUPPORTED_BUT_GATED", "DEFERRED")},
                     "source_statistics": stat["sources"], "trust_statistics": stat["trust"],
                     "difficulty_statistics": stat["difficulty"], "lifecycle_statistics": stat["lifecycle"]})
    manifest["artifacts"] = [
        {"kind": "scenario", "path": "scenarios.json", "record_count": len(scenarios), "sha256": sha(OUT / "scenarios.json")},
        {"kind": "sample", "path": "samples.json", "record_count": len(samples), "sha256": sha(OUT / "samples.json")},
        {"kind": "validation_report", "path": "split_assignment.json", "record_count": len(assignment), "sha256": sha(OUT / "split_assignment.json")},
        {"kind": "validation_report", "path": "source_reconciliation.json", "record_count": len(reconciliation), "sha256": sha(OUT / "source_reconciliation.json")},
    ]
    manifest["validation_summary"] = {"schema_valid": False, "contract_valid": False, "scope_valid": False,
        "leakage_valid": False, "policy_valid": False, "privacy_valid": False, "error_count": 0,
        "warning_count": 0, "report_reference": "canonical_training/v0.2_experiment_a_only/validation_report.json"}
    manifest["notes"] = ("Training v0.2 Experiment A-only additive assembly. Frozen Canonical Training v0.1 records and split assignments are copied; "
        "approved frozen Experiment A Samples are assigned to train only in this new version. No resplitting. "
        "All validation/test/hard_test samples remain historical v0.1 diagnostic-only and are excluded from this training setup. "
        "Six original unassigned samples remain excluded; FIN-002 has no Samples. "
        "A-only families/split groups/semantic states are train-only. Dataset schema_version and dataset_version remain 0.1 under frozen schema constraints. "
        "training_eligible=true means static dataset readiness only; no training has been performed. Source snapshot provenance is in source_reconciliation.json.")
    dump(OUT / "dataset_manifest.json", manifest)

    # Export with the frozen serializer; no external metadata enters model-visible rows.
    old_train = read(OLD_SETUP / "llamafactory/train.json")
    old_val_bytes = (OLD_SETUP / "llamafactory/validation.json").read_bytes()
    train_rows = list(old_train)
    trace_rows = [copy.deepcopy(x) for x in read(OLD_SETUP / "traceability.json") if x["split"] == "train"]
    trace_rows += [copy.deepcopy(x) for x in read(OLD_SETUP / "traceability.json") if x["split"] == "validation"]
    a_export_traces = []
    for sample in a_samples:
        row, trace = export_record(sample)
        train_rows.append(row)
        a_export_traces.append({**trace, "sample_id": sample["sample_id"], "scenario_id": sample["scenario_id"],
                                "scenario_family_id": sample["scenario_family_id"], "split_group_id": sample["split_group_id"],
                                "split": "train", "source_dataset": "docs/ai/dataset/business_state_expansion/v0.2/experiment_a",
                                "source_samples_sha256": a_hashes["samples.json"]})
    dump(SETUP / "llamafactory/train.json", train_rows)
    (SETUP / "llamafactory/validation.json").write_bytes(old_val_bytes)
    trace_rows += a_export_traces
    dump(SETUP / "traceability.json", trace_rows)
    info = {
      "sharedledger_a_only_train": {"file_name": "train.json", "formatting": "sharegpt", "columns": {"messages": "conversations", "system": "system"}, "tags": {"role_tag": "role", "content_tag": "content", "user_tag": "user", "assistant_tag": "assistant"}},
      "sharedledger_a_only_validation": {"file_name": "validation.json", "formatting": "sharegpt", "columns": {"messages": "conversations", "system": "system"}, "tags": {"role_tag": "role", "content_tag": "content", "user_tag": "user", "assistant_tag": "assistant"}},
    }
    dump(SETUP / "llamafactory/dataset_info.json", info)
    qlora = (OLD_SETUP / "qlora.yaml").read_text(encoding="utf-8")
    qlora = qlora.replace("dataset: sharedledger_train", "dataset: sharedledger_a_only_train")
    qlora = qlora.replace("dataset_dir: D:/project/Android/shared-ledger/docs/ai/training_setup/v0.1/llamafactory", f"dataset_dir: {SETUP.as_posix()}/llamafactory")
    qlora = qlora.replace("eval_dataset: sharedledger_validation", "eval_dataset: sharedledger_a_only_validation")
    qlora = qlora.replace("output_dir: D:/AI/runs/shared-ledger/qwen3.5-4b-qlora-v0.1", "output_dir: D:/AI/runs/shared-ledger/qwen3.5-4b-qlora-v0.2-experiment-a-only")
    dump(SETUP / "qlora.yaml", qlora) if False else (SETUP / "qlora.yaml").write_text(qlora, encoding="utf-8")
    (SETUP / "evaluation_policy.json").write_text(json.dumps({
        "validation": {"use": "model selection", "source": "Frozen v0.1 validation", "count": 24},
        "historical_v0_1_test": {"count": 37, "use": "historical regression/diagnostic only", "sealed_for_selection": True},
        "historical_v0_1_hard_test": {"count": 12, "use": "historical regression/diagnostic only", "sealed_for_selection": True},
        "fresh_generalization_evidence": "not provided by historical v0.1 test/hard_test; no new holdout assignment in this assembly",
        "future_split": "Experiment A's 8 Families, 6 contrast groups and semantic-state closure are assigned train in this version",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    old_setup_manifest = read(OLD_SETUP / "manifest.json")
    setup_manifest = {"training_setup_version": "0.2-experiment-a-only", "canonical_dataset_version": "0.2-experiment-a-only",
        "source": {"canonical_v1": {"path": "docs/ai/dataset/canonical_training/v0.1",
            "manifest_sha256": sha(V1 / "dataset_manifest.json"), "samples_sha256": sha(V1 / "samples.json"),
            "scenarios_sha256": sha(V1 / "scenarios.json"), "split_assignment_sha256": sha(V1 / "split_assignment.json")},
            "experiment_a": {"path": "docs/ai/dataset/business_state_expansion/v0.2/experiment_a",
             "manifest_sha256": sha(A / "dataset_manifest.json"), "samples_sha256": sha(A / "samples.json"),
             "scenarios_sha256": sha(A / "scenarios.json"), "freeze_hashes_sha256": sha(A / "freeze_hashes.json")}},
        "export": {"format": "LLaMA-Factory ShareGPT JSON", "record_count": 211,
            "split_counts": {"train": 187, "validation": 24}, "historical_diagnostic_only_not_exported": {"test": 37, "hard_test": 12},
            "excluded_unassigned_count": 6, "added_experiment_a_samples": 16},
        "serialization": old_setup_manifest["serialization"], "llamafactory_source_version": old_setup_manifest["llamafactory_source_version"],
        "static_validation": {"status": "pending", "training_performed": False}, "artifacts": {}}
    dump(SETUP / "manifest.json", setup_manifest)
    (SETUP / "README.md").write_text("""# Training Setup v0.2 Experiment A-only\n\nThis is a new additive static training-data assembly from frozen Canonical Training v0.1 plus the 16 approved SILVER Samples in frozen Experiment A. The canonical snapshot contains 266 Samples and 70 Scenarios. The six original unassigned Samples remain excluded. Experiment A's 16 Samples are assigned train only in this copy; the source Experiment A folder remains unassigned and unchanged.\n\nThe exported LLaMA-Factory ShareGPT files contain 187 train and 24 validation rows. Validation is byte-identical to v0.1. Historical v0.1 test (37) and hard_test (12) remain in the canonical source snapshot and are diagnostic/regression-only; they are not exported here and must not be used for model selection or presented as fresh generalization evidence. The 8 Experiment A Families and all contrast/semantic-state groups are train-only.\n\nThe `qlora.yaml` preserves all frozen v0.1 training hyperparameters; only dataset registrations/path and isolated output directory differ. Estimated updates naturally change from about 33 to 36 over three epochs because the train split grows from 171 to 187. This package is data-ready only. No model, optimizer, training, inference, API, or Teacher operation was run.\n\n`validation_report.json` records actual local LLaMA-Factory loader, tokenizer/template, cutoff and loss-mask checks; `manifest.json` records source and artifact hashes; `traceability.json` and the canonical `source_reconciliation.json` map every row to its frozen source.\n""", encoding="utf-8")

    print(f"Assembled {len(samples)} samples, {len(scenarios)} scenarios; splits={stat['splits']}; train export={len(train_rows)}; validation bytes={sha_bytes(old_val_bytes)}")


if __name__ == "__main__":
    main()
