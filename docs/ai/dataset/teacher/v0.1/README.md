# Teacher Dataset v0.1

This is the frozen formal Teacher-generated dataset, separate from both the frozen Gold Seed and generator run directories. It contains 155 retained Samples across 53 eligible Families; FIN-002 is excluded (zero samples). All records are SILVER, surface-reviewed, lifecycle-approved, `example_only=false`, and remain `split=unassigned`. Manifest governance declares `training_eligible=true`; no split assignment, export, or model training has taken place.

## Authority and provenance

Canonical Ground Truth remains the frozen Gold P0 Scenario dataset at `../gold_seed/v0.1/p0/`. `scenarios.json` here is a byte-for-byte read-only snapshot for standalone validation, not a new authority. The Gold scenario SHA-256 is `b4ba7f406f017cd28c7c6885827717ae246b8f4dfb794a76fe00db5f9db59815`; the frozen Gold sample SHA-256 remains `34ffd94d9c5ccbb17e6632b8689194c4be53f7275db828e983f6d6540b406dee`.

The 155 Samples derive from source run `fullgen-20260929T082701Z-ff76470a` (21 retained Pilot candidates from `pilot-20260929T074620Z-c314cc93` plus 134 retained full-generation candidates), using provider `opencode`, model `deepseek-v4.1-flash`, prompt `surface-variant-v1.0.0`. Every Sample preserves its per-call Teacher provenance and locked Expected output. The source run's `human_quality_review.json` documents review of 172 candidates: 155 retained, 17 rejected (15 near-duplicates; 2 task-direction/added-fact issues). Rejected records remain only in the source run audit and are not copied here.

Approval records the existing owner-authorized governance transition for the independently reviewed Teacher pool; it does not promote SILVER to GOLD. Surface review evidence is in `scripts/ai_teacher_generator/runs/full-generation-v0.1/fullgen-20260929T082701Z-ff76470a/human_quality_review.json`; batch and generation evidence is in the same run's `quality_report.json` and `batch_manifest.json`.

## Freeze policy

Frozen on 2026-09-29. Do not edit these records in place or allow Teacher output to modify the canonical Scenario/Expected Ground Truth. Any correction or expansion requires a new Teacher Dataset version, a new manifest and artifact hashes, and fresh validation/review. FIN-002 remains unrepresented because no server-side suggestion is available. The manifest marks the dataset training-eligible, while all splits remain unassigned; this dataset is not an export or training run.

## Validation

Run `python scripts/ai_dataset_validator/cli.py validate dataset docs/ai/dataset/teacher/v0.1`. The freeze validation has 0 errors and 84 `SEMANTIC_GROUP_REVIEW` warnings; these warnings are retained as review diagnostics from the existing semantic-group deduplication rule, and the source `human_quality_review.json` records all-pool near-duplicate screening.
