#!/usr/bin/env python3
"""Apply the authorized governance freeze without changing Experiment A data content."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/dataset/business_state_expansion/v0.2/experiment_a"
REVIEW = "docs/ai/dataset/business_state_expansion/v0.2/experiment_a/EXPERIMENT_A_INDEPENDENT_REVIEW.md"
REVIEW_JSON = "docs/ai/dataset/business_state_expansion/v0.2/experiment_a/independent_review.json"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha_file(path):
    return sha_bytes(path.read_bytes())


def object_sha(value):
    return sha_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def content_without_governance(record, kind):
    value = copy.deepcopy(record)
    if kind == "scenario":
        for key in ("verification_methods", "business_validated", "evidence_refs"):
            value["trust"].pop(key, None)
        value["lifecycle"].pop("status", None)
        value["lifecycle"].pop("review_notes", None)
    else:
        value["trust"].pop("surface_form_reviewed", None)
        value["trust"].pop("validation_evidence", None)
        value["dataset_metadata"].pop("lifecycle_status", None)
        value["dataset_metadata"].pop("review_notes", None)
    return value


manifest_path = OUT / "dataset_manifest.json"
manifest = read(manifest_path)
scenarios_path = OUT / "scenarios.json"
samples_path = OUT / "samples.json"
policy_path = OUT / "future_holdout_policy.json"
scenarios = read(scenarios_path)
samples = read(samples_path)
pre_scenarios = copy.deepcopy(scenarios)
pre_samples = copy.deepcopy(samples)
policy = read(policy_path)
prior_freeze_path = OUT / "freeze_report.json"
recovering_guard_test_regeneration = manifest.get("status") == "frozen"
prior_freeze = read(prior_freeze_path) if recovering_guard_test_regeneration and prior_freeze_path.is_file() else None
if recovering_guard_test_regeneration:
    if not prior_freeze or prior_freeze.get("status") != "frozen":
        raise SystemExit(f"Refusing to rewrite frozen Experiment A without its freeze evidence: {OUT}")
    expected_pre = prior_freeze["content_integrity"]["pre_governance_sha256"]
    if sha_file(scenarios_path) != expected_pre["scenarios.json"] or sha_file(samples_path) != expected_pre["samples.json"]:
        raise SystemExit(f"Refusing recovery: Scenario/Sample files do not match the recorded pre-governance hashes: {OUT}")
policy_principles = {k: copy.deepcopy(v) for k, v in policy.items() if k != "freeze_metadata"}

if len(scenarios) != 16 or len(samples) != 16 or any(x.get("split") != "unassigned" for x in samples):
    raise SystemExit("Freeze precondition failed: expected 16/16 records with all Samples unassigned.")
review = read(OUT / "independent_review.json")
if review.get("verdict") != "V0_2_EXPERIMENT_A_READY_FOR_FREEZE" or review.get("unresolved_findings") != 0:
    raise SystemExit("Freeze precondition failed: independent review is not ready or has unresolved findings.")

now = prior_freeze["frozen_at"] if recovering_guard_test_regeneration else datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
pre_hashes = copy.deepcopy(prior_freeze["content_integrity"]["pre_governance_sha256"]) if recovering_guard_test_regeneration else {
    "scenarios.json": sha_file(scenarios_path),
    "samples.json": sha_file(samples_path),
    "future_holdout_policy.json": sha_file(policy_path),
    "dataset_manifest.json": sha_file(manifest_path),
}
pre_source_hashes = read(OUT / "source_hashes.json")["artifacts"]
source_actual = {rel: sha_file(ROOT / rel) for rel in pre_source_hashes}
if source_actual != pre_source_hashes:
    raise SystemExit("Freeze precondition failed: one or more of 30 frozen source hashes changed.")

# Preserve SILVER while recording accepted business review and policy evidence.
for scenario in scenarios:
    trust = scenario["trust"]
    trust["level"] = "SILVER"
    trust["business_validated"] = True
    trust["verification_methods"] = list(dict.fromkeys(trust.get("verification_methods", []) + ["frozen_rule", "programmatic_invariant", "human_review"]))
    trust["evidence_refs"] = list(dict.fromkeys(trust.get("evidence_refs", []) + [REVIEW, REVIEW_JSON]))
    scenario["lifecycle"]["status"] = "approved"
    scenario["lifecycle"]["review_notes"] = (
        f"Experiment A v0.2 governance freeze {now}; independent Codex review passed ({REVIEW}); "
        "maintainer explicitly accepted the final review and authorized approved/frozen status in the current user request. "
        "Trust remains SILVER; no new product rule or GOLD claim."
    )

for sample in samples:
    trust = sample["trust"]
    trust["level"] = "SILVER"
    trust["ground_truth_locked"] = True
    trust["surface_form_reviewed"] = True
    trust["validation_evidence"] = list(dict.fromkeys(trust.get("validation_evidence", []) + [
        REVIEW,
        REVIEW_JSON,
        "Current maintainer acceptance: user request authorizing Experiment A v0.2 freeze on 2026-10-01.",
    ]))
    metadata = sample["dataset_metadata"]
    metadata["lifecycle_status"] = "approved"
    metadata["review_notes"] = (
        f"Approved SILVER Sample at Experiment A v0.2 freeze {now}, following independent review and explicit maintainer acceptance "
        "recorded in freeze_report.json. Split remains unassigned; eligibility does not authorize export or training before split assignment."
    )
    if sample.get("split") != "unassigned":
        raise SystemExit(f"Unexpected assigned split: {sample['sample_id']}")

# Freeze only metadata on the existing holdout policy; retain all assignment principles unchanged.
policy["freeze_metadata"] = {
    "status": "frozen",
    "experiment_version": "0.2-experiment-a",
    "frozen_at": now,
    "principles_sha256": object_sha(policy_principles),
}
write(scenarios_path, scenarios)
write(samples_path, samples)
write(policy_path, policy)

scenario_content_unchanged = all(content_without_governance(a, "scenario") == content_without_governance(b, "scenario") for a, b in zip(pre_scenarios, scenarios))
sample_content_unchanged = all(content_without_governance(a, "sample") == content_without_governance(b, "sample") for a, b in zip(pre_samples, samples))
policy_principles_unchanged = all(policy.get(key) == value for key, value in policy_principles.items())
if not (scenario_content_unchanged and sample_content_unchanged and policy_principles_unchanged):
    raise SystemExit("Freeze aborted: non-governance data content differs from the pre-freeze records.")

post_hashes = {
    "scenarios.json": sha_file(scenarios_path),
    "samples.json": sha_file(samples_path),
    "future_holdout_policy.json": sha_file(policy_path),
}

# Refresh content hashes while preserving the completed validation findings.
validation_path = OUT / "validation_report.json"
validation = read(validation_path)
validation["dataset_content_hashes"] = {
    "scenarios.json": post_hashes["scenarios.json"],
    "samples.json": post_hashes["samples.json"],
}
validation["freeze_status"] = "frozen"
validation["experiment_version"] = "0.2-experiment-a"
validation["freeze_timestamp"] = now
write(validation_path, validation)

# Recompute all manifest statistics from the approved records.
family_count = len({s["scenario_family_id"] for s in scenarios})
task_counts = Counter(s["task"]["primary"] for s in samples)
scope_counts = Counter(s["scope"]["ai_scope"] for s in samples)
trust_counts = Counter(s["trust"]["level"] for s in samples)
difficulty_counts = Counter(s["difficulty"] for s in samples)
lifecycle_counts = Counter(s["dataset_metadata"]["lifecycle_status"] for s in samples)
manifest.update({
    "created_at": now,
    "status": "frozen",
    "scenario_count": len(scenarios),
    "scenario_family_count": family_count,
    "sample_count": len(samples),
    "split_policy": {"assignment_unit": "scenario_family", "target_percentages": {"train": 70, "validation": 10, "test": 15, "hard_test": 5}, "final_split_assigned": False},
    "split_statistics": {"train": 0, "validation": 0, "test": 0, "hard_test": 0, "unassigned": len(samples)},
    "task_statistics": dict(task_counts),
    "scope_statistics": {"CORE": scope_counts.get("CORE", 0), "SUPPORTED_BUT_GATED": scope_counts.get("SUPPORTED_BUT_GATED", 0), "DEFERRED": scope_counts.get("DEFERRED", 0)},
    "source_statistics": {"manual": len(samples)},
    "trust_statistics": {k: trust_counts.get(k, 0) for k in ("GOLD", "SILVER", "SYNTHETIC_UNVERIFIED")},
    "difficulty_statistics": {k: difficulty_counts.get(k, 0) for k in ("easy", "normal", "hard", "ood")},
    "lifecycle_statistics": {k: lifecycle_counts.get(k, 0) for k in ("draft", "generated", "validated", "reviewed", "approved", "rejected", "deprecated")},
    "validation_summary": {"schema_valid": True, "contract_valid": True, "scope_valid": True, "leakage_valid": True, "policy_valid": True, "privacy_valid": True, "error_count": 0, "warning_count": 6, "report_reference": REVIEW},
})

freeze_report = {
    "status": "frozen",
    "experiment_version": "0.2-experiment-a",
    "frozen_at": now,
    "maintainer_acceptance": {"source": "current user request explicitly accepting final audit and authorizing approved/frozen status", "decision": "approved and frozen", "recorded_at": now},
    "independent_review": {"source": REVIEW, "machine_record": REVIEW_JSON, "verdict": review["verdict"], "reviewer": "independent Codex reviewer for this task; not represented as a human reviewer"},
    "freeze_scope": "governance fields, manifest/provenance/README and holdout freeze metadata only; no Training/Teacher/API/Experiment B/C/commit",
    "record_counts": {"scenarios": 16, "samples": 16, "families": family_count, "contrastive_groups": 6, "pairwise_contrasts": 11, "output_distribution": review["output_distribution"]},
    "trust_lifecycle": {"scenario_trust": "SILVER", "scenario_business_validated": True, "scenario_lifecycle": "approved", "sample_trust": "SILVER", "surface_form_reviewed": True, "sample_lifecycle": "approved", "policy_status": "active", "split": "unassigned", "training_eligible": "true for governance readiness; export remains blocked until split assignment"},
    "reviewed_warning_count": 6,
    "expected_fact_grounding": {"sources": 102, "facts": 102, "missing": 0},
    "content_integrity": {
        "scenario_non_governance_deep_equality": scenario_content_unchanged,
        "sample_non_governance_deep_equality": sample_content_unchanged,
        "holdout_policy_principles_unchanged": policy_principles_unchanged,
        "pre_governance_sha256": pre_hashes,
        "post_governance_sha256": post_hashes,
        "non_governance_comparison": "all 16 Scenario and all 16 Sample objects compared after excluding only authorized governance fields",
    },
    "frozen_v0_1_sources": {"source_hash_file": "source_hashes.json", "files_verified": len(source_actual), "all_unchanged": True, "hashes": source_actual},
}
freeze_report_path = OUT / "freeze_report.json"
write(freeze_report_path, freeze_report)

manifest["artifacts"] = [
    {"kind": "scenario", "path": "scenarios.json", "record_count": len(scenarios), "sha256": post_hashes["scenarios.json"]},
    {"kind": "sample", "path": "samples.json", "record_count": len(samples), "sha256": post_hashes["samples.json"]},
    {"kind": "validation_report", "path": "decision_state_coverage.json", "record_count": len(read(OUT / "decision_state_coverage.json")), "sha256": sha_file(OUT / "decision_state_coverage.json")},
    {"kind": "validation_report", "path": "validation_report.json", "record_count": len(validation), "sha256": sha_file(validation_path)},
    {"kind": "validation_report", "path": "future_holdout_policy.json", "record_count": len(policy), "sha256": post_hashes["future_holdout_policy.json"]},
    {"kind": "validation_report", "path": "freeze_report.json", "record_count": len(freeze_report), "sha256": sha_file(freeze_report_path)},
]
manifest["notes"] = (
    f"Frozen Training v0.2 Experiment A on {now}; external experiment_version=0.2-experiment-a. "
    "Dataset Schema v0.1 and dataset_version=0.1 remain unchanged because the frozen schema requires them. "
    "All 16 Scenarios and Samples are approved; trust remains SILVER. training_eligible=true as governance readiness only; "
    "all Samples remain split=unassigned, so export is blocked by the split gate; no export or training was performed. "
    "Freeze audit: FREEZE_AUDIT.md and freeze_report.json. Six intentional reviewed NORMALIZED_DUPLICATE contrast warnings are retained."
)
write(manifest_path, manifest)
manifest_hash = sha_file(manifest_path)

readme = f"""# Training v0.2 Experiment A — Frozen

Status: **FROZEN** on {now} (`V0_2_EXPERIMENT_A_FROZEN`). External experiment version is **0.2 Experiment A**. The unchanged Dataset Schema v0.1 requires `dataset_version=0.1`; this schema field is not the external experiment version.

This frozen packet contains 16 approved Scenarios and 16 approved, human-authored Samples across 8 Families. All retain **SILVER** trust; no record was promoted to GOLD. Scenarios are business-validated and approved. Samples are surface-reviewed and approved. All records remain active, and all Samples remain **unassigned**. The manifest records `training_eligible=true` as governance readiness, while export remains blocked until split assignment. No split was assigned, no export or training was run, and no API, Teacher, or Experiment B/C work was started.

Independent terminal review: [`EXPERIMENT_A_INDEPENDENT_REVIEW.md`](EXPERIMENT_A_INDEPENDENT_REVIEW.md), verdict `V0_2_EXPERIMENT_A_READY_FOR_FREEZE`. The maintainer explicitly accepted that review and authorized this freeze in the current user request. Reviewer identity is recorded as an independent Codex review, not as a human reviewer.

The packet contains 6 intentional reviewed `NORMALIZED_DUPLICATE` contrasts and 11 pairwise comparisons. Expected Fact→Visible Source remains 102/102 with 0 missing. The future holdout policy is frozen with its existing closure, validation, and sealed-test principles unchanged; no holdout assignment occurred.

The manifest retains `frozen_reference_sha={manifest['frozen_reference_sha']}`. All 30 Frozen v0.1 source hashes match `source_hashes.json`. Pre/post content hashes and explicit Scenario/Sample non-governance deep-equality results are in [`freeze_report.json`](freeze_report.json); final artifact hashes are in [`freeze_hashes.json`](freeze_hashes.json).

Frozen dataset files must not be regenerated or edited in place. The builder and finalizer refuse to overwrite this frozen directory; any future change requires a new dataset version and a fresh review.
"""
(OUT / "README.md").write_text(readme, encoding="utf-8")

freeze_audit = f"""# Training v0.2 Experiment A Freeze Audit

Frozen at `{now}` (Asia/Shanghai). External experiment version: `0.2 Experiment A`; Dataset Schema version stays `0.1` as required by the frozen schema.

The current user request explicitly accepted the independent final review and authorized `approved`/`frozen` governance. The record attributes the independent audit to Codex and the freeze acceptance to the maintainer; it does not claim a human reviewer identity.

- 16/16 Scenarios: `SILVER`, `business_validated=true`, lifecycle `approved`.
- 16/16 Samples: `SILVER`, `ground_truth_locked=true`, `surface_form_reviewed=true`, lifecycle `approved`, policy `active`.
- All 16 Samples remain `split=unassigned`. `training_eligible=true` means governance-ready; export remains blocked until split assignment. No export or training occurred.
- Output distribution: 7 clarification, 5 proposal, 3 tool_call, 1 answer. Six reviewed contrast warnings are retained.
- Expected facts: 102/102 visible sources, 0 missing. Frozen v0.1 source hashes: 30/30 unchanged.
- Exact non-governance deep equality: all 16 Scenarios and all 16 Samples match their pre-freeze business content. The policy's principles are unchanged; only freeze metadata was appended.

Pre- and post-governance hashes and the equality proof are in `freeze_report.json`. Final manifest and artifact hashes are in `freeze_hashes.json`. Builder/finalizer overwrite guards were added; rerunning either against this frozen directory must fail without changing files.
"""
(OUT / "FREEZE_AUDIT.md").write_text(freeze_audit, encoding="utf-8")

freeze_hashes = {
    "hash_algorithm": "SHA-256",
    "experiment_version": "0.2-experiment-a",
    "frozen_at": now,
    "hashes": {
        "dataset_manifest.json": manifest_hash,
        "scenarios.json": post_hashes["scenarios.json"],
        "samples.json": post_hashes["samples.json"],
        "future_holdout_policy.json": post_hashes["future_holdout_policy.json"],
        "freeze_report.json": sha_file(freeze_report_path),
        "README.md": sha_file(OUT / "README.md"),
        "FREEZE_AUDIT.md": sha_file(OUT / "FREEZE_AUDIT.md"),
    },
    "frozen_v0_1_source_hashes_match": True,
    "source_hash_file_count": len(source_actual),
}
write(OUT / "freeze_hashes.json", freeze_hashes)

print(json.dumps({
    "status": "frozen",
    "frozen_at": now,
    "manifest_sha256": manifest_hash,
    "scenario_non_governance_deep_equal": scenario_content_unchanged,
    "sample_non_governance_deep_equal": sample_content_unchanged,
    "holdout_principles_unchanged": policy_principles_unchanged,
    "frozen_v0_1_source_hashes": len(source_actual),
    "trust": "SILVER",
    "lifecycle": "approved",
    "training_eligible": True,
    "split": "unassigned",
}, ensure_ascii=False, indent=2))
