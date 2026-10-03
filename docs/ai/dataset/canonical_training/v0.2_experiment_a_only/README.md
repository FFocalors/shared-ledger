# Canonical Training v0.2 Experiment A-only

This validated additive snapshot contains 266 Samples and 70 Scenarios. The split counts are 187 train, 24 validation, 37 historical test, 12 historical hard_test, and six unassigned. The 16 approved SILVER Experiment A Samples are assigned to train in this copy only; all eight A Families, their split groups, and their contrastive semantic states remain train-only. The original v0.1 Samples and assignments are preserved. FIN-002 remains a Scenario-only Family with no Sample.

The 24 validation records are the frozen v0.1 validation set. The 37 test and 12 hard_test records are historical regression/diagnostic data only. They are not fresh generalization evidence and are not exported by the companion Training Setup. See [the Training Setup README](../../../training_setup/v0.2_experiment_a_only/README.md) for serialization, configuration, loader validation and evaluation policy. `source_reconciliation.json` maps every Sample to its source; `validation_report.json` records the Dataset Validator result.

## Validator warnings

The final Dataset Validator result is **0 errors and 161 warnings**. There are no cross-split assignment or semantic-leakage errors.

The **155 `SEMANTIC_GROUP_REVIEW` warnings** come from the already frozen v0.1 Gold/Teacher corpus. They mark reviewed Surface siblings with the same semantic group inside a closed Family and split; they do not indicate new exact or near-duplicate records in this assembly. The frozen v0.1 coverage report records zero exact, normalized, and similarity-at-least-0.90 pairs, and says these same-split warnings are retained after review. That disposition is backed by the [Canonical v0.1 coverage report](../v0.1/coverage_report.json), [Canonical v0.1 README](../v0.1/README.md), [Gold Sample review](../../gold_seed/v0.1/P0_GOLD_SAMPLE_REVIEW.md), [Teacher v0.1 review disposition](../../teacher/v0.1/README.md), and the [Teacher human quality review](../../../../../scripts/ai_teacher_generator/runs/full-generation-v0.1/fullgen-20260929T082701Z-ff76470a/human_quality_review.json).

The other **six `NORMALIZED_DUPLICATE` warnings** are the intentional Experiment A contrast pairs, retained after independent review. In each pair the user Surface is intentionally the same or near-identical while a visible Context fact changes the decision. Their final dispositions are recorded in the [Experiment A independent review](../../business_state_expansion/v0.2/experiment_a/EXPERIMENT_A_INDEPENDENT_REVIEW.md) and `independent_review.json`. The Validator has not been weakened and no record keys were changed to suppress warnings.

The schema remains v0.1 as required by the frozen Dataset Schema. This v0.2 Experiment A-only snapshot is validated for data assembly; the companion setup is statically ready. No training has been performed.
