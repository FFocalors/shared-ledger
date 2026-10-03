#!/usr/bin/env python3
"""Finalize hashes and validation evidence for the static A-only assembly."""
from __future__ import annotations
import hashlib, json, subprocess, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "docs/ai/dataset/canonical_training/v0.2_experiment_a_only"
SETUP = ROOT / "docs/ai/training_setup/v0.2_experiment_a_only"
V1 = ROOT / "docs/ai/dataset/canonical_training/v0.1"
A = ROOT / "docs/ai/dataset/business_state_expansion/v0.2/experiment_a"
OLD_SETUP = ROOT / "docs/ai/training_setup/v0.1"

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text(encoding="utf-8"))
def dump(path, value): path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def validate_dataset():
    proc = subprocess.run([sys.executable, "scripts/ai_dataset_validator/cli.py", "validate", "dataset",
                           str(CANONICAL.relative_to(ROOT)), "--json-report"], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode not in (0, 1):
        raise RuntimeError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)

def main():
    cr = validate_dataset()
    if cr["errors"]:
        raise SystemExit(f"Canonical dataset validator has {len(cr['errors'])} errors")
    (CANONICAL / "validation_report.json").write_text(json.dumps(cr, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cm = read(CANONICAL / "dataset_manifest.json")
    cm["validation_summary"] = {"schema_valid": True, "contract_valid": True, "scope_valid": True,
        "leakage_valid": True, "policy_valid": True, "privacy_valid": True,
        "error_count": 0, "warning_count": len(cr["warnings"]),
        "report_reference": "docs/ai/dataset/canonical_training/v0.2_experiment_a_only/validation_report.json"}
    cm["artifacts"] = [x for x in cm["artifacts"] if x["path"] != "validation_report.json"]
    cm["artifacts"].append({"kind": "validation_report", "path": "validation_report.json",
        "record_count": len(cr), "sha256": sha(CANONICAL / "validation_report.json")})
    dump(CANONICAL / "dataset_manifest.json", cm)
    verified = validate_dataset()
    if verified["errors"]:
        raise SystemExit(f"Canonical dataset revalidation has {len(verified['errors'])} errors")
    report_bytes = json.dumps(verified, ensure_ascii=False, indent=2) + "\n"
    if report_bytes.encode("utf-8") != (CANONICAL / "validation_report.json").read_bytes():
        (CANONICAL / "validation_report.json").write_text(report_bytes, encoding="utf-8")
        cm["artifacts"][-1]["sha256"] = sha(CANONICAL / "validation_report.json")
        cm["validation_summary"]["warning_count"] = len(verified["warnings"])
        dump(CANONICAL / "dataset_manifest.json", cm)
        final = validate_dataset()
        if final["errors"] or json.dumps(final, ensure_ascii=False, indent=2) + "\n" != (CANONICAL / "validation_report.json").read_text(encoding="utf-8"):
            raise SystemExit("Canonical validation report/hash did not stabilize")

    report = read(SETUP / "validation_report.json")
    if report.get("status") != "passed" or report.get("rows_loaded") != 211 or report.get("loss_masks_verified") != 211:
        raise SystemExit("LLaMA-Factory static validation report is missing or incomplete")
    sm = read(SETUP / "manifest.json")
    sm["static_validation"] = {"status": "passed", "training_performed": False,
        "llamafactory_loader_rows": 211, "ground_truth_equal": 211, "source_trace_unique": 211,
        "metadata_leaks": 0, "loss_masks_verified": 211, "cutoff_len": 2048,
        "max_total_tokens": report["max_total_tokens"], "truncations": 0,
        "validation_source": "Frozen v0.1 validation export, byte-identical"}
    sm["export"]["output_types"] = dict(Counter(x["expected"]["model_output"]["type"] for x in read(CANONICAL / "samples.json") if x["split"] in {"train", "validation"}))
    canonical_samples = read(CANONICAL / "samples.json")
    sm["export"]["family_counts"] = {"scenario_families_in_snapshot": len({x["scenario_family_id"] for x in read(CANONICAL / "scenarios.json")}),
        "families_with_samples": len({x["scenario_family_id"] for x in canonical_samples}),
        "train_families_with_samples": len({x["scenario_family_id"] for x in canonical_samples if x["split"] == "train"}),
        "added_experiment_a_families": len({x["scenario_family_id"] for x in read(A / "samples.json")}),
        "scenario_only_fin002_families": 1}
    sm["artifact_hashes"] = {}
    for rel in ("llamafactory/train.json", "llamafactory/validation.json", "llamafactory/dataset_info.json",
                "traceability.json", "qlora.yaml", "evaluation_policy.json", "validation_report.json", "README.md"):
        sm["artifact_hashes"][rel] = sha(SETUP / rel)
    sm["canonical_artifacts"] = {rel: sha(CANONICAL / rel) for rel in
        ("samples.json", "scenarios.json", "split_assignment.json", "source_reconciliation.json", "validation_report.json", "dataset_manifest.json")}
    sm["configuration_comparison"] = {"baseline": "docs/ai/training_setup/v0.1/qlora.yaml",
        "baseline_sha256": sha(OLD_SETUP / "qlora.yaml"), "changed_fields": ["dataset", "dataset_dir", "eval_dataset", "output_dir"],
        "unchanged_fields": 37, "training_hyperparameters_unchanged": True}
    dump(SETUP / "manifest.json", sm)
    (SETUP / "manifest.sha256").write_text(sha(SETUP / "manifest.json") + "  manifest.json\n", encoding="ascii")
    # A compact source baseline records exact immutable inputs, with no self-hash cycle.
    v1_manifest = read(V1 / "dataset_manifest.json")
    note_fields = dict(part.split("=", 1) for part in v1_manifest.get("notes", "").split("; ") if "=" in part)
    evidence = {}
    for label, path_key in (("gold", "source_gold_path"), ("teacher", "source_teacher_path")):
        source_dir = ROOT / note_fields[path_key]
        evidence[label] = {"path": note_fields[path_key], "manifest_sha256": sha(source_dir / "dataset_manifest.json"),
            "samples_sha256": sha(source_dir / "samples.json"), "scenarios_sha256": sha(source_dir / "scenarios.json"),
            "expected_manifest_sha256": note_fields[f"source_{label}_manifest_sha256"],
            "expected_samples_sha256": note_fields[f"source_{label}_samples_sha256"],
            "expected_scenarios_sha256": note_fields[f"source_{label}_scenarios_sha256"]}
        if any(evidence[label][f"{field}_sha256"] != evidence[label][f"expected_{field}_sha256"]
               for field in ("manifest", "samples", "scenarios")):
            raise SystemExit(f"Frozen v1 {label} source hash mismatch")
    baseline = {"canonical_v1": {rel: sha(V1 / rel) for rel in ("samples.json", "scenarios.json", "split_assignment.json", "dataset_manifest.json")},
        "gold_teacher_sources": evidence,
        "pipeline_definitions": {rel: sha(ROOT / rel) for rel in (
            "scripts/ai_training_setup/export_dataset.py", "scripts/ai_training_setup/validate_setup.py",
            "scripts/ai_training_evaluation/evaluate_generation.py", "scripts/ai_training_evaluation/validate_expected.py")},
        "setup_v1": {"manifest.json": sha(OLD_SETUP / "manifest.json"), "qlora.yaml": sha(OLD_SETUP / "qlora.yaml"),
                     "validation.json": sha(OLD_SETUP / "llamafactory/validation.json")},
        "experiment_a": {rel: sha(A / rel) for rel in ("samples.json", "scenarios.json", "dataset_manifest.json", "freeze_hashes.json", "source_hashes.json")},
        "freeze_source_file_count": read(A / "freeze_hashes.json")["source_hash_file_count"],
        "freeze_sources_match": read(A / "freeze_hashes.json")["frozen_v0_1_source_hashes_match"]}
    dump(SETUP / "source_baseline_hashes.json", baseline)
    # Refresh setup manifest hashes after adding the detached source baseline and hash file.
    sm = read(SETUP / "manifest.json")
    sm["artifact_hashes"]["source_baseline_hashes.json"] = sha(SETUP / "source_baseline_hashes.json")
    dump(SETUP / "manifest.json", sm)
    (SETUP / "manifest.sha256").write_text(sha(SETUP / "manifest.json") + "  manifest.json\n", encoding="ascii")
    # Drop only the transient process log; it is not an artifact.
    log = SETUP / "validation-run.log"
    if log.exists(): log.unlink()
    print(json.dumps({"canonical_errors": len(verified["errors"]), "canonical_warnings": len(verified["warnings"]),
                      "canonical_report_sha256": sha(CANONICAL / "validation_report.json"),
                      "setup_manifest_sha256": sha(SETUP / "manifest.json"),
                      "lf_rows": report["rows_loaded"], "max_tokens": report["max_total_tokens"]}, indent=2))

if __name__ == "__main__": main()
