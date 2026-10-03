# Training v0.2 Experiment A — Frozen

Status: **FROZEN** on 2026-10-01T12:35:01+08:00 (`V0_2_EXPERIMENT_A_FROZEN`). External experiment version is **0.2 Experiment A**. The unchanged Dataset Schema v0.1 requires `dataset_version=0.1`; this schema field is not the external experiment version.

This frozen packet contains 16 approved Scenarios and 16 approved, human-authored Samples across 8 Families. All retain **SILVER** trust; no record was promoted to GOLD. Scenarios are business-validated and approved. Samples are surface-reviewed and approved. All records remain active, and all Samples remain **unassigned**. The manifest records `training_eligible=true` as governance readiness, while export remains blocked until split assignment. No split was assigned, no export or training was run, and no API, Teacher, or Experiment B/C work was started.

Independent terminal review: [`EXPERIMENT_A_INDEPENDENT_REVIEW.md`](EXPERIMENT_A_INDEPENDENT_REVIEW.md), verdict `V0_2_EXPERIMENT_A_READY_FOR_FREEZE`. The maintainer explicitly accepted that review and authorized this freeze in the current user request. Reviewer identity is recorded as an independent Codex review, not as a human reviewer.

The packet contains 6 intentional reviewed `NORMALIZED_DUPLICATE` contrasts and 11 pairwise comparisons. Expected Fact→Visible Source remains 102/102 with 0 missing. The future holdout policy is frozen with its existing closure, validation, and sealed-test principles unchanged; no holdout assignment occurred.

The manifest retains `frozen_reference_sha=55fb28a7c0660462e5842e2eb5c71cfa763e5801`. All 30 Frozen v0.1 source hashes match `source_hashes.json`. Pre/post content hashes and explicit Scenario/Sample non-governance deep-equality results are in [`freeze_report.json`](freeze_report.json); final artifact hashes are in [`freeze_hashes.json`](freeze_hashes.json).

Frozen dataset files must not be regenerated or edited in place. A guard smoke test caught and corrected a missed builder invocation; the deterministic pre-freeze records were restored by matching their recorded hashes and the original freeze timestamp was preserved. Final negative tests confirm both builder and finalizer refuse the frozen directory without changing any checked artifact. Any future change requires a new dataset version and fresh review.
