# Canonical Training Dataset v0.1

This frozen assembly combines 95 Gold Seed and 155 Teacher Dataset Samples (250 total) from the two byte-verified frozen sources. It contains 53 Families with samples; FIN-002 contributes zero, and the 17 rejected Teacher candidates are excluded. The original `sample_id`, Ground Truth, Surface Form, Context, trust and Teacher provenance are preserved. Only `split` and the existing `source.source_reference` trace are changed in this assembly copy.

## Split policy and deterministic assignment

The frozen Dataset Schema §16 and Validation Rules §12 specify 70/10/15/5 by `scenario_family_id`, with `split_group_id` as the immutable closure key. No existing source document specifies a seed. This assembly derives a fixed seed as SHA-256 of `canonical-training-v0.1|34ffd94d9c5ccbb17e6632b8689194c4be53f7275db828e983f6d6540b406dee|5d2ca222d8ee4a87ae9e17cdaa0dd22dbfa8bf6835458e34e3be6c9292e4c4d9` and applies `sha256_seeded_balanced_swap_annealing_v1`. Assignment balances family counts and per-sample Task, output type, difficulty, challenge tags, Scope and source type while retaining whole Families. The 52 active Families are assigned 36/5/8/3 across train/validation/test/hard_test; the six pending-policy samples in the single pending Family remain `unassigned`, as required by the frozen rules. Sample counts per split are recorded in `coverage_report.json` and the manifest.

## Traceability and frozen inputs

Every assembled Sample keeps its source `sample_id`; `split_assignment.json` maps it to source Dataset path, frozen source sample SHA-256, source sample ID, Scenario, Family, split group and assigned split. `source.source_reference` carries the same assembly origin while preserving the exact original source reference. `scenarios.json` is a byte-for-byte reference snapshot; Canonical Ground Truth remains governed by the frozen Gold Scenario artifact.

- Gold source: `docs/ai/dataset/gold_seed/v0.1/p0`; scenarios `b4ba7f406f017cd28c7c6885827717ae246b8f4dfb794a76fe00db5f9db59815`, samples `34ffd94d9c5ccbb17e6632b8689194c4be53f7275db828e983f6d6540b406dee`.
- Teacher source: `docs/ai/dataset/teacher/v0.1`; scenarios `b4ba7f406f017cd28c7c6885827717ae246b8f4dfb794a76fe00db5f9db59815`, samples `5d2ca222d8ee4a87ae9e17cdaa0dd22dbfa8bf6835458e34e3be6c9292e4c4d9`.
- Fixed assignment seed: `9be1655ffe2c0904fb738c7f5be94e603bcfa3c2f4f71e30c970a9879073404e`; method `sha256_seeded_balanced_swap_annealing_v1`; frozen at `2026-09-29T22:51:12+08:00`.

Both trust levels remain unchanged (GOLD and SILVER); all included records are reviewed and approved. Pending policy stays unassigned. The assignment is for dataset partitioning only; no chat-template export, tokenization, training, or quantization occurred. Semantic-group variants remain within their Family/split and their review warnings are preserved. After freeze, changes require a new dataset version.

## Validation

Run `python scripts/ai_dataset_validator/cli.py validate dataset docs/ai/dataset/canonical_training/v0.1`. `coverage_report.json` records Task/output/difficulty/challenge/source coverage, split counts, and exact/normalized/near-duplicate review results.
