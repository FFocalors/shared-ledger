# v0.2 Experiment C Training Setup

This isolated setup changes only the model-visible system Contract guide. Its source remains the frozen Canonical Training Dataset v0.1 and Frozen v0.1 training configuration. This directory prepares data only; no training or inference run was performed.

## Guide and frozen sources

The old system instruction was one general sentence (32 tokens with the local Qwen3.5-4B tokenizer). The new guide is 394 tokens, an increase of 362 tokens; including each sample's unchanged context, the full system input also rises by exactly 362 tokens per row. The guide is in `system_guide.txt`; the scoped coverage review and deliberate omissions are in `contract_coverage.json`. The review covers the experiment's routing, schema discipline, grounding and safety summary; it is not a claim of complete Contract coverage. The guide preserves user-provided operation parameters while requiring authoritative server results for balance, debt, limits, FX, and computed settlement facts. It summarizes routing, clarification, trusted confirmation, deferred scope, D4, unresolved decisions, and the closed six-type JSON output contract. Exact per-type keys and slots, enabled intent/tool mappings, and detailed business invariants remain in the frozen schema/catalogs and Contract/runtime. Lookup budgets and error recovery remain runtime/Gateway responsibilities.

The guide does not explicitly teach proposal invalidation after page, Activity, object, server-state, or `financial_version` changes, nor proposal expiry. Its requirements to use current visible facts and obtain a trusted Gateway recheck do not fully cover this rule from the model's perspective. The frozen Contract requires stale proposals to be invalidated; the runtime must enforce that lifecycle. This remains a documented instruction gap and was not added to the guide in this experiment.

The token increase is material: this setup changes instruction content and clarity, and cannot isolate a benefit caused by reducing prompt length.

The unchanged serialization suffix starts with `\n\n運行時上下文（JSON）：`; the JSON context remains byte-identical to the v0.1 row. Conversations, history packing, and compact Ground Truth JSON are identical for each sample. The validator checks this exact paired equality across all 244 assigned samples.

## Setup and verification

Run from repository root:

```powershell
& D:\AI\.venv\Scripts\python.exe scripts\ai_training_setup\experiment_c_export.py
& D:\AI\.venv\Scripts\python.exe scripts\ai_training_setup\validate_experiment_c.py
```

The actual local LLaMA-Factory 0.9.6.dev0 loader, ShareGPT converter, `qwen3_5_nothink` template and supervised processor validate all four frozen split exports. The checks assert 171 train, 24 validation, 37 test, 12 hard_test, six unassigned excluded, exact Ground Truth, zero metadata leakage, history round-trip, and only the final assistant answer contributes to loss (`train_on_prompt=false`, `mask_history=true`). All 244 examples must fit the unchanged 2,048-token cutoff. `validation_report.json` records source hashes, token counts, mask checks, and full-system token differences.

`qlora.yaml` retains every v0.1 training parameter; only `dataset_dir` and isolated `output_dir` paths differ. `smoke.yaml` is carried as a separate reference with its data and run paths isolated; it was not run. No model training or inference was started.

The Experiment C exporter and validator are separate from the Frozen v0.1 files. `manifest.json` records hashes of frozen source files and generated artifacts.
