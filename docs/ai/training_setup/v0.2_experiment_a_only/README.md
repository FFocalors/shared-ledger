# Training Setup v0.2 Experiment A-only

This is a new additive static training-data assembly from frozen Canonical Training v0.1 plus the 16 approved SILVER Samples in frozen Experiment A. The canonical snapshot contains 266 Samples and 70 Scenarios across 62 Scenario Families. Sixty-one Families have Samples; the remaining Scenario-only Family is FIN-002 and has no Sample. The six original unassigned Samples remain excluded. Experiment A's eight Families and 16 Samples are assigned train only in this copy; the source Experiment A folder remains unassigned and unchanged. There are 44 train Families with Samples (36 from v0.1 and 8 from A).

The exported LLaMA-Factory ShareGPT files contain 187 train and 24 validation rows. Validation is byte-identical to v0.1. Historical v0.1 test (37) and hard_test (12) remain in the canonical source snapshot and are diagnostic/regression-only; they are not exported here and must not be used for model selection or presented as fresh generalization evidence. The 8 Experiment A Families and all contrast/semantic-state groups are train-only.

The `qlora.yaml` preserves all frozen v0.1 training hyperparameters; only dataset registrations/path and isolated output directory differ. Estimated updates naturally change from about 33 to 36 over three epochs because the train split grows from 171 to 187. This package is data-ready only. No model, optimizer, training, inference, API, or Teacher operation was run.

`validation_report.json` records actual local LLaMA-Factory loader, tokenizer/template, cutoff and loss-mask checks; `manifest.json` records source and artifact hashes; `traceability.json` and the canonical `source_reconciliation.json` map every row to its frozen source.
