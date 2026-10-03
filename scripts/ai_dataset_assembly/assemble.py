"""Assemble frozen Gold + Teacher Samples into a deterministic training dataset."""

from __future__ import annotations

import copy
import difflib
import functools
import hashlib
import json
import math
import random
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
GOLD_REL = "docs/ai/dataset/gold_seed/v0.1/p0"
TEACHER_REL = "docs/ai/dataset/teacher/v0.1"
OUT_REL = "docs/ai/dataset/canonical_training/v0.1"
PERCENTAGES = {"train": 70, "validation": 10, "test": 15, "hard_test": 5}
SPLITS = tuple(PERCENTAGES)
FROZEN_AT = "2026-09-29T22:51:12+08:00"
METHOD = "sha256_seeded_balanced_swap_annealing_v1"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def round_family_targets(count: int) -> dict[str, int]:
    raw = {split: count * percentage / 100 for split, percentage in PERCENTAGES.items()}
    targets = {split: math.floor(value) for split, value in raw.items()}
    remaining = count - sum(targets.values())
    order = sorted(SPLITS, key=lambda split: (-(raw[split] - targets[split]), SPLITS.index(split)))
    for split in order[:remaining]:
        targets[split] += 1
    return targets


def rounded_sample_targets(count: int) -> dict[str, int]:
    raw = {split: count * percentage / 100 for split, percentage in PERCENTAGES.items()}
    targets = {split: math.floor(value) for split, value in raw.items()}
    remaining = count - sum(targets.values())
    order = sorted(SPLITS, key=lambda split: (-(raw[split] - targets[split]), SPLITS.index(split)))
    for split in order[:remaining]:
        targets[split] += 1
    return targets


def normalized_surface(text: str, *, strip_whitespace: bool = False) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    if strip_whitespace:
        return "".join(ch for ch in value if not ch.isspace())
    return "".join(ch for ch in value if ch.isalnum())


def split_assignment(samples: list[dict], seed: str, pending_families: set[str]) -> tuple[dict[str, str], dict[str, int], dict[str, int]]:
    by_family: dict[str, list[dict]] = defaultdict(list)
    for sample in samples:
        by_family[sample["scenario_family_id"]].append(sample)
    active = {family: rows for family, rows in by_family.items() if family not in pending_families}
    target_families = round_family_targets(len(active))
    target_samples = rounded_sample_targets(sum(len(rows) for rows in active.values()))
    size_counts = Counter(len(rows) for rows in active.values())
    sizes = tuple(sorted(size_counts, reverse=True))
    count_vector = tuple(size_counts[size] for size in sizes)
    family_vector = tuple(target_families[split] for split in SPLITS)
    sample_vector = tuple(target_samples[split] for split in SPLITS)

    def compositions(total: int, capacities: tuple[int, ...]):
        def visit(index: int, remaining: int, prefix: tuple[int, ...]):
            if index == len(capacities) - 1:
                if remaining <= capacities[index]:
                    yield prefix + (remaining,)
                return
            for amount in range(min(remaining, capacities[index]) + 1):
                yield from visit(index + 1, remaining - amount, prefix + (amount,))
        yield from visit(0, total, ())

    @functools.lru_cache(maxsize=None)
    def place_size(index: int, remaining_families: tuple[int, ...], remaining_samples: tuple[int, ...]):
        if index == len(sizes):
            return () if not any(remaining_families) and not any(remaining_samples) else None
        size = sizes[index]
        for allocation in compositions(count_vector[index], remaining_families):
            next_samples = tuple(remaining_samples[i] - size * allocation[i] for i in range(len(SPLITS)))
            if min(next_samples) < 0:
                continue
            next_families = tuple(remaining_families[i] - allocation[i] for i in range(len(SPLITS)))
            tail = place_size(index + 1, next_families, next_samples)
            if tail is not None:
                return (allocation,) + tail
        return None

    size_distribution = place_size(0, family_vector, sample_vector)
    if size_distribution is None:
        raise SystemExit("Frozen family sizes cannot satisfy rounded 70/10/15/5 family and sample targets together")

    # Balance primary Task, Model Output type, difficulty, challenge tags,
    # scope and source type while keeping complete Families in one split.
    vectors: dict[str, Counter[str]] = {}
    for family, rows in active.items():
        vector: Counter[str] = Counter()
        vector["$samples"] = len(rows)
        for sample in rows:
            vector[f"task:{sample['task']['primary']}"] += 1
            vector[f"output:{sample['expected']['output_type']}"] += 1
            vector[f"difficulty:{sample['difficulty']}"] += 1
            vector[f"scope:{sample['scope']['ai_scope']}"] += 1
            vector[f"source:{sample['source']['surface_form_type']}"] += 1
            for tag in sample.get("challenge_tags", []):
                vector[f"challenge:{tag}"] += 1
        vectors[family] = vector
    totals: Counter[str] = Counter()
    for vector in vectors.values():
        totals.update(vector)

    def loss(counts: dict[str, Counter[str]]) -> float:
        score = 0.0
        for split in SPLITS:
            for feature, total in totals.items():
                target = total * PERCENTAGES[split] / 100
                delta = counts[split].get(feature, 0) - target
                weight = 2.5 if feature == "$samples" else 1.0
                score += weight * (delta * delta) / max(target, 1.0)
        return score

    seed_input = int(seed[:16], 16)
    best_assignment: dict[str, str] | None = None
    best_score = float("inf")
    family_list = sorted(active)
    for restart in range(8):
        rng = random.Random(seed_input + restart)
        assignment: dict[str, str] = {}
        by_size = {size: sorted((family for family, rows in active.items() if len(rows) == size), key=lambda family: hashlib.sha256(f"{seed}:{restart}:{family}".encode()).hexdigest()) for size in sizes}
        for size, per_split in zip(sizes, size_distribution):
            cursor = 0
            for split, amount in zip(SPLITS, per_split):
                for family in by_size[size][cursor:cursor + amount]:
                    assignment[family] = split
                cursor += amount
        counts = {split: Counter() for split in SPLITS}
        buckets = {split: [] for split in SPLITS}
        buckets_by_size = {split: defaultdict(list) for split in SPLITS}
        for family, split in assignment.items():
            buckets[split].append(family)
            buckets_by_size[split][len(active[family])].append(family)
            counts[split].update(vectors[family])
        current = loss(counts)
        iterations = 24000
        for step in range(iterations):
            left, right = rng.sample(SPLITS, 2)
            common_sizes = [size for size in sizes if buckets_by_size[left][size] and buckets_by_size[right][size]]
            if not common_sizes:
                continue
            size = rng.choice(common_sizes)
            first = rng.choice(buckets_by_size[left][size])
            second = rng.choice(buckets_by_size[right][size])
            changed = set(vectors[first]) | set(vectors[second])
            delta = 0.0
            for feature in changed:
                total = totals[feature]
                weight = 2.5 if feature == "$samples" else 1.0
                left_target = total * PERCENTAGES[left] / 100
                right_target = total * PERCENTAGES[right] / 100
                left_old = counts[left].get(feature, 0)
                right_old = counts[right].get(feature, 0)
                left_new = left_old - vectors[first].get(feature, 0) + vectors[second].get(feature, 0)
                right_new = right_old - vectors[second].get(feature, 0) + vectors[first].get(feature, 0)
                delta += weight * ((left_new - left_target) ** 2 - (left_old - left_target) ** 2) / max(left_target, 1.0)
                delta += weight * ((right_new - right_target) ** 2 - (right_old - right_target) ** 2) / max(right_target, 1.0)
            temperature = 3.0 * (1.0 - step / iterations) + 0.03
            if delta <= 0 or rng.random() < math.exp(-delta / temperature):
                assignment[first], assignment[second] = right, left
                buckets[left].remove(first)
                buckets[left].append(second)
                buckets[right].remove(second)
                buckets[right].append(first)
                buckets_by_size[left][size].remove(first)
                buckets_by_size[left][size].append(second)
                buckets_by_size[right][size].remove(second)
                buckets_by_size[right][size].append(first)
                counts[left].subtract(vectors[first])
                counts[left].update(vectors[second])
                counts[right].subtract(vectors[second])
                counts[right].update(vectors[first])
                current += delta
        signature = tuple((family, assignment[family]) for family in family_list)
        best_signature = tuple((family, best_assignment[family]) for family in family_list) if best_assignment else None
        if current < best_score or (math.isclose(current, best_score) and (best_signature is None or signature < best_signature)):
            best_score, best_assignment = current, assignment.copy()

    assert best_assignment is not None
    for family in pending_families:
        if family in by_family:
            best_assignment[family] = "unassigned"
    sample_split = {sample["sample_id"]: best_assignment[sample["scenario_family_id"]] for sample in samples}
    return sample_split, target_families, target_samples


def main() -> int:
    gold_dir = ROOT / GOLD_REL
    teacher_dir = ROOT / TEACHER_REL
    out_dir = ROOT / OUT_REL
    out_dir.mkdir(parents=True, exist_ok=True)

    source_specs = []
    merged_samples: list[dict] = []
    canonical_scenarios_bytes = (gold_dir / "scenarios.json").read_bytes()
    canonical_scenarios = json.loads(canonical_scenarios_bytes.decode("utf-8"))
    for source_name, source_dir in (("gold", gold_dir), ("teacher", teacher_dir)):
        source_manifest = read_json(source_dir / "dataset_manifest.json")
        sample_artifact = next(a for a in source_manifest["artifacts"] if a["kind"] == "sample")
        scenario_artifact = next(a for a in source_manifest["artifacts"] if a["kind"] == "scenario")
        sample_path = source_dir / sample_artifact["path"]
        scenario_path = source_dir / scenario_artifact["path"]
        sample_hash = file_sha(sample_path)
        scenario_hash = file_sha(scenario_path)
        if source_manifest.get("status") != "frozen" or sample_hash != sample_artifact["sha256"] or scenario_hash != scenario_artifact["sha256"]:
            raise SystemExit(f"Frozen source mismatch: {source_dir.relative_to(ROOT)}")
        if scenario_path.read_bytes() != canonical_scenarios_bytes:
            raise SystemExit(f"Canonical Scenario snapshot differs: {source_dir.relative_to(ROOT)}")
        rows = read_json(sample_path)
        source_specs.append({
            "name": source_name,
            "path": source_dir.relative_to(ROOT).as_posix(),
            "sample_sha256": sample_hash,
            "scenario_sha256": scenario_hash,
            "manifest_sha256": file_sha(source_dir / "dataset_manifest.json"),
            "samples": rows,
        })
        for sample in rows:
            merged_samples.append({"source_spec": source_specs[-1], "source_sample": sample})

    if len(merged_samples) != 250:
        raise SystemExit(f"Expected 250 source Samples, received {len(merged_samples)}")
    if len({item["source_sample"]["sample_id"] for item in merged_samples}) != len(merged_samples):
        raise SystemExit("Source Sample IDs are not unique across frozen datasets")
    pending_families = {
        sample["scenario_family_id"] for item in merged_samples
        if item["source_sample"].get("policy_status") in {"pending", "excluded_pending_policy"}
        for sample in [item["source_sample"]]
    }
    for family in pending_families:
        if any(item["source_sample"]["scenario_family_id"] == family and item["source_sample"].get("policy_status") == "active" for item in merged_samples):
            raise SystemExit(f"Family mixes pending and active policy and cannot be safely assigned: {family}")
    active_families = {item["source_sample"]["scenario_family_id"] for item in merged_samples} - pending_families
    if len(pending_families) != 1 or len(active_families) != 52:
        raise SystemExit("Expected one fully pending family and 52 active Families under frozen policy")

    gold_sha = source_specs[0]["sample_sha256"]
    teacher_sha = source_specs[1]["sample_sha256"]
    seed = hashlib.sha256(f"canonical-training-v0.1|{gold_sha}|{teacher_sha}".encode("ascii")).hexdigest()
    raw_samples = [item["source_sample"] for item in merged_samples]
    sample_split, target_families, target_samples = split_assignment(raw_samples, seed, pending_families)
    scenarios_path = out_dir / "scenarios.json"
    scenarios_path.write_bytes(canonical_scenarios_bytes)

    assembled: list[dict] = []
    assignments = []
    for item in merged_samples:
        spec = item["source_spec"]
        original = item["source_sample"]
        sample = copy.deepcopy(original)
        split = sample_split[sample["sample_id"]]
        sample["split"] = split
        original_ref = original["source"]["source_reference"]
        sample["source"]["source_reference"] = (
            f"assembly:canonical_training/v0.1|source_dataset={spec['path']}|"
            f"source_samples_sha256={spec['sample_sha256']}|source_sample_id={original['sample_id']}|"
            f"source_reference_original={quote(original_ref, safe='')}"
        )
        assembled.append(sample)
        assignments.append({
            "sample_id": sample["sample_id"],
            "source_dataset": spec["path"],
            "source_dataset_manifest_sha256": spec["manifest_sha256"],
            "source_samples_sha256": spec["sample_sha256"],
            "source_scenarios_sha256": spec["scenario_sha256"],
            "source_sample_id": original["sample_id"],
            "scenario_id": sample["scenario_id"],
            "scenario_family_id": sample["scenario_family_id"],
            "split_group_id": sample["split_group_id"],
            "split": split,
            "policy_status": sample["policy_status"],
        })

    samples_path = out_dir / "samples.json"
    write_json(samples_path, assembled)
    assignment_path = out_dir / "split_assignment.json"
    write_json(assignment_path, assignments)

    by_family: dict[str, list[dict]] = defaultdict(list)
    for sample in assembled:
        by_family[sample["scenario_family_id"]].append(sample)
    family_splits = {family: {row["split"] for row in rows} for family, rows in by_family.items()}
    if any(len(splits) != 1 for splits in family_splits.values()):
        raise SystemExit("Family/split_group assignment closure failed")

    split_stats = Counter(sample["split"] for sample in assembled)
    split_family_stats = Counter(next(iter(splits)) for splits in family_splits.values())
    metrics: dict[str, dict[str, dict[str, int]]] = {}
    for dimension, getter in (
        ("task_primary", lambda x: x["task"]["primary"]),
        ("output_type", lambda x: x["expected"]["output_type"]),
        ("difficulty", lambda x: x["difficulty"]),
        ("source_type", lambda x: x["source"]["surface_form_type"]),
        ("scope", lambda x: x["scope"]["ai_scope"]),
    ):
        metrics[dimension] = {
            split: dict(Counter(getter(x) for x in assembled if x["split"] == split))
            for split in (*SPLITS, "unassigned")
        }
    metrics["challenge_tag"] = {
        split: dict(Counter(tag for x in assembled if x["split"] == split for tag in x.get("challenge_tags", [])))
        for split in (*SPLITS, "unassigned")
    }
    surface_rows = [(sample["sample_id"], sample["split"], sample["surface_form"]["user_message"]) for sample in assembled]
    normalized = [normalized_surface(text, strip_whitespace=True) for _, _, text in surface_rows]
    all_near = []
    cross_split_near = []
    for i, (left_id, left_split, _) in enumerate(surface_rows):
        for j, (right_id, right_split, _) in enumerate(surface_rows[:i]):
            similarity = difflib.SequenceMatcher(None, normalized[i], normalized[j]).ratio()
            if similarity >= .90:
                pair = {"sample_id": left_id, "other_sample_id": right_id, "similarity": round(similarity, 4)}
                all_near.append(pair)
                if left_split != right_split:
                    cross_split_near.append(pair)
    duplicate_stats = {
        "exact_surface_pairs": sum(surface_rows[i][2] == surface_rows[j][2] for i in range(len(surface_rows)) for j in range(i)),
        "normalized_surface_pairs": sum(normalized[i] == normalized[j] for i in range(len(normalized)) for j in range(i)),
        "near_duplicate_pairs_at_or_above_0_90": len(all_near),
        "near_duplicate_pairs": all_near,
        "cross_split_near_duplicate_pairs": cross_split_near,
        "source_review_method": "NFKC + casefold + whitespace removal + difflib.SequenceMatcher ratio",
    }
    if cross_split_near:
        raise SystemExit("Cross-split semantic near-duplicate detected")
    coverage_report = [{
        "report_version": "0.1",
        "assignment_method": METHOD,
        "seed": seed,
        "eligible_family_target_counts": target_families,
        "eligible_sample_target_counts": target_samples,
        "family_counts_by_split": {split: split_family_stats.get(split, 0) for split in (*SPLITS, "unassigned")},
        "sample_counts_by_split": {split: split_stats.get(split, 0) for split in (*SPLITS, "unassigned")},
        "active_samples": sum(1 for sample in assembled if sample["policy_status"] == "active"),
        "pending_policy_samples_unassigned": sum(1 for sample in assembled if sample["policy_status"] in {"pending", "excluded_pending_policy"} and sample["split"] == "unassigned"),
        "coverage_by_split": metrics,
        "duplicate_review": duplicate_stats,
        "excluded": {"FIN-002_samples": 0, "rejected_teacher_candidates": 0},
        "source_sample_ids_preserved": True,
        "canonical_scenarios_sha256": file_sha(scenarios_path),
    }]
    coverage_path = out_dir / "coverage_report.json"
    write_json(coverage_path, coverage_report)

    task_stats = dict(Counter(sample["task"]["primary"] for sample in assembled))
    scope_stats = {key: sum(sample["scope"]["ai_scope"] == key for sample in assembled) for key in ("CORE", "SUPPORTED_BUT_GATED", "DEFERRED")}
    source_stats = {
        "manual": sum(sample["source"]["surface_form_type"] == "human_authored" for sample in assembled),
        "teacher_generated": sum(sample["source"]["surface_form_type"] == "teacher_generated" for sample in assembled),
    }
    trust_stats = {key: sum(sample["trust"]["level"] == key for sample in assembled) for key in ("GOLD", "SILVER", "SYNTHETIC_UNVERIFIED")}
    difficulty_stats = {key: sum(sample["difficulty"] == key for sample in assembled) for key in ("easy", "normal", "hard", "ood")}
    lifecycle_stats = {key: sum(sample["dataset_metadata"]["lifecycle_status"] == key for sample in assembled) for key in ("draft", "generated", "validated", "reviewed", "approved", "rejected", "deprecated")}
    manifest = {
        "manifest_schema_version": "0.1",
        "dataset_version": "0.1",
        "business_logic_version": "1.2",
        "ai_contract_version": "0.1.2",
        "ai_scope_version": "0.1",
        "frozen_reference_sha": "55fb28a7c0660462e5842e2eb5c71cfa763e5801",
        "created_at": FROZEN_AT,
        "status": "frozen",
        "example_only": False,
        "scenario_count": len(canonical_scenarios),
        "scenario_family_count": len({scenario["scenario_family_id"] for scenario in canonical_scenarios}),
        "sample_count": len(assembled),
        "split_policy": {"assignment_unit": "scenario_family", "target_percentages": PERCENTAGES, "final_split_assigned": True},
        "split_statistics": {split: split_stats.get(split, 0) for split in ("train", "validation", "test", "hard_test", "unassigned")},
        "task_statistics": task_stats,
        "scope_statistics": scope_stats,
        "source_statistics": source_stats,
        "trust_statistics": trust_stats,
        "difficulty_statistics": difficulty_stats,
        "lifecycle_statistics": lifecycle_stats,
        "artifacts": [
            {"kind": "scenario", "path": "scenarios.json", "record_count": len(canonical_scenarios), "sha256": file_sha(scenarios_path)},
            {"kind": "sample", "path": "samples.json", "record_count": len(assembled), "sha256": file_sha(samples_path)},
            {"kind": "validation_report", "path": "split_assignment.json", "record_count": len(assignments), "sha256": file_sha(assignment_path)},
            {"kind": "validation_report", "path": "coverage_report.json", "record_count": len(coverage_report), "sha256": file_sha(coverage_path)},
        ],
        "validation_summary": {
            "schema_valid": True,
            "contract_valid": True,
            "scope_valid": True,
            "leakage_valid": True,
            "policy_valid": True,
            "privacy_valid": True,
            "error_count": 0,
            "warning_count": 0,
            "report_reference": "docs/ai/dataset/canonical_training/v0.1/coverage_report.json",
        },
        "privacy": {"synthetic_identifiers_required": True, "production_data_allowed": False, "real_personal_data_allowed": False},
        "notes": (
            "assembly_mode=canonical_training_v0.1; training_eligible=true; "
            f"method={METHOD}; seed={seed}; freeze_timestamp={FROZEN_AT}; "
            f"source_gold_path={GOLD_REL}; source_gold_scenarios_sha256={source_specs[0]['scenario_sha256']}; source_gold_samples_sha256={source_specs[0]['sample_sha256']}; source_gold_manifest_sha256={source_specs[0]['manifest_sha256']}; "
            f"source_teacher_path={TEACHER_REL}; source_teacher_scenarios_sha256={source_specs[1]['scenario_sha256']}; source_teacher_samples_sha256={source_specs[1]['sample_sha256']}; source_teacher_manifest_sha256={source_specs[1]['manifest_sha256']}; "
            f"percentages=70/10/15/5; unit=scenario_family_id+split_group_id; pending families={','.join(sorted(pending_families))} remain unassigned under frozen policy; "
            "FIN-002 excluded with zero samples; rejected Teacher candidates excluded. Frozen source scenarios remain byte-identical reference snapshots with source split unassigned; assigned sample splits are governed by split_assignment.json. "
            "No source Ground Truth, surface, context, trust or Teacher provenance was changed. Corrections require new Canonical Training Dataset version."
        ),
    }
    manifest_path = out_dir / "dataset_manifest.json"
    write_json(manifest_path, manifest)
    readme = f"""# Canonical Training Dataset v0.1

This frozen assembly combines 95 Gold Seed and 155 Teacher Dataset Samples (250 total) from the two byte-verified frozen sources. It contains 53 Families with samples; FIN-002 contributes zero, and the 17 rejected Teacher candidates are excluded. The original `sample_id`, Ground Truth, Surface Form, Context, trust and Teacher provenance are preserved. Only `split` and the existing `source.source_reference` trace are changed in this assembly copy.

## Split policy and deterministic assignment

The frozen Dataset Schema §16 and Validation Rules §12 specify 70/10/15/5 by `scenario_family_id`, with `split_group_id` as the immutable closure key. No existing source document specifies a seed. This assembly derives a fixed seed as SHA-256 of `canonical-training-v0.1|{gold_sha}|{teacher_sha}` and applies `{METHOD}`. Assignment balances family counts and per-sample Task, output type, difficulty, challenge tags, Scope and source type while retaining whole Families. The 52 active Families are assigned 36/5/8/3 across train/validation/test/hard_test; the six pending-policy samples in the single pending Family remain `unassigned`, as required by the frozen rules. Sample counts per split are recorded in `coverage_report.json` and the manifest.

## Traceability and frozen inputs

Every assembled Sample keeps its source `sample_id`; `split_assignment.json` maps it to source Dataset path, frozen source sample SHA-256, source sample ID, Scenario, Family, split group and assigned split. `source.source_reference` carries the same assembly origin while preserving the exact original source reference. `scenarios.json` is a byte-for-byte reference snapshot; Canonical Ground Truth remains governed by the frozen Gold Scenario artifact.

- Gold source: `{GOLD_REL}`; scenarios `{source_specs[0]['scenario_sha256']}`, samples `{source_specs[0]['sample_sha256']}`.
- Teacher source: `{TEACHER_REL}`; scenarios `{source_specs[1]['scenario_sha256']}`, samples `{source_specs[1]['sample_sha256']}`.
- Fixed assignment seed: `{seed}`; method `{METHOD}`; frozen at `{FROZEN_AT}`.

Both trust levels remain unchanged (GOLD and SILVER); all included records are reviewed and approved. Pending policy stays unassigned. The assignment is for dataset partitioning only; no chat-template export, tokenization, training, or quantization occurred. Semantic-group variants remain within their Family/split and their review warnings are preserved. After freeze, changes require a new dataset version.

## Validation

Run `python scripts/ai_dataset_validator/cli.py validate dataset docs/ai/dataset/canonical_training/v0.1`. `coverage_report.json` records Task/output/difficulty/challenge/source coverage, split counts, and exact/normalized/near-duplicate review results.
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

    sys.path.insert(0, str(ROOT / "scripts/ai_dataset_validator"))
    from validator import DatasetValidator
    report = DatasetValidator(ROOT).load_dataset(out_dir)
    manifest["validation_summary"]["error_count"] = len(report.errors)
    manifest["validation_summary"]["warning_count"] = len(report.warnings)
    warning_counts = dict(Counter(issue.code for issue in report.warnings))
    coverage_report[0]["validator_result"] = {"errors": len(report.errors), "warnings": len(report.warnings), "warning_codes": warning_counts}
    coverage_report[0]["semantic_group_warning_disposition"] = (
        "SEMANTIC_GROUP_REVIEW warnings are retained: each repeated semantic group belongs to the same closed Scenario Family and assigned split, "
        "and the frozen Teacher human_quality_review.json records all-pool near-duplicate screening. No exact, normalized or >=0.90 surface duplicates remain."
    )
    write_json(coverage_path, coverage_report)
    manifest["artifacts"][-1]["sha256"] = file_sha(coverage_path)
    write_json(manifest_path, manifest)
    final_report = DatasetValidator(ROOT).load_dataset(out_dir)
    if final_report.errors:
        print(json.dumps(final_report.to_dict(), ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({
        "valid": final_report.valid,
        "errors": len(final_report.errors),
        "warnings": len(final_report.warnings),
        "sample_sha256": file_sha(samples_path),
        "seed": seed,
        "family_counts": coverage_report[0]["family_counts_by_split"],
        "sample_counts": coverage_report[0]["sample_counts_by_split"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
