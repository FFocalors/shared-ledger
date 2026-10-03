# Shared Ledger Training Setup v0.1

This directory prepares the frozen Canonical Training Dataset v0.1 for LLaMA-Factory SFT. It exports the four assigned splits only: 171 train, 24 validation, 37 test, and 12 hard_test (244 total). The six `unassigned` samples are omitted; FIN-002 has no sample and remains excluded. The frozen dataset and split assignment are read-only inputs.

## Model and local framework

- LLaMA-Factory: `D:\AI\LlamaFactory`, source version `0.9.6.dev0`.
- Python: `D:\AI\.venv`, Python 3.11.15; Transformers 5.8.0.
- Model/tokenizer: `D:\AI\models\Qwen3.5-4B`.
- Template: `qwen3_5_nothink`; SFT format: LLaMA-Factory ShareGPT.

The inspected source path is `src/llamafactory/data/template.py:2426-2438`: the `qwen3_5_nothink` template formats system/user/assistant messages with the Qwen `<|im_start|>` / `<|im_end|>` tokens. `src/llamafactory/data/parser.py:93-130` reads `dataset_info.json` and maps its `formatting`, columns, and role tags. `src/llamafactory/data/converter.py:135-184`'s `SharegptDatasetConverter` requires user/assistant-alternating messages and splits the last assistant message as the response. It rejects adjacent same-role turns at lines 161-174. `src/llamafactory/data/processor/supervised.py:52-105` masks prompt source labels to `IGNORE_INDEX` when `train_on_prompt=false`; with `mask_history=true`, it also masks earlier assistant responses and supervises only the last response. These behaviors were exercised through the actual converter and `SupervisedDatasetProcessor` for all 244 exported rows.

The model's bundled tokenizer chat template adds an empty `<think>…</think>` block (four tokens) that the LLaMA-Factory `qwen3_5_nothink` encoder does not add. Token counts below use the encoder actually used by LLaMA-Factory training, and the validator records the tokenizer-template comparison separately. For this dataset, that comparison is consistently +4 tokens/sample; it does not change target JSON content.

## Model-visible serialization

Each LLaMA-Factory row has only `system` and `conversations`; training IDs, family/split IDs, lifecycle, trust, source/provenance, timestamps, and review notes live in the separate `traceability.json`, never in model input. The system begins with a short Android shared-ledger instruction, then a compact JSON object containing allowlisted runtime context: client locale/platform, UI state, visible page state, relevant user role, recent actions, pending/confirmed conversation state, enabled tools, verified result IDs, confirmation policy, and runtime tool results. Request IDs, fixture timestamps, commit hashes, and training metadata are omitted. Conversation messages follow in original order, then the current user message, then the frozen `expected.model_output` serialized as compact JSON.

The canonical data has 24 samples with prior conversation history; six histories contain consecutive user turns. LLaMA-Factory's built-in ShareGPT converter cannot represent adjacent same-role messages. The export therefore packs only each contiguous same-role run into a versioned `<|shared_ledger_turn_block_v1|>` JSON block. The JSON preserves every original `role` and `content` exactly, with source turn ranges in `traceability.json`; it is reversible and round-trip asserted for all 244 samples. No turn text is summarized, corrected, or dropped. Earlier assistant messages remain in assistant role where the source sequence alternates; `mask_history=true` ensures no historical assistant content contributes to loss.

## Validation and token lengths

Run from the repository root:

```powershell
& D:\AI\.venv\Scripts\python.exe scripts\ai_training_setup\export_dataset.py
& D:\AI\.venv\Scripts\python.exe scripts\ai_training_setup\validate_setup.py
& D:\AI\.venv\Scripts\python.exe -m unittest discover -s scripts\ai_training_setup\tests -v
```

`validation_report.json` records full per-sample checks, frozen source hashes, and input/target/total length percentiles by split and output type. The current LLaMA-Factory-template total length distribution is p50 450, p90 1,053, p95 1,071, p99 1,185, max 1,193 tokens. All 244 examples fit in 2,048 tokens with 855 tokens of observed headroom at the maximum; `cutoff_len: 2048` is the recommended initial setting. The longest records are JSON proposals; target p99/max is reported by output type in the validation report. No truncation occurred during the check.

The 244 serialized rows load through the framework parser and processor with 100% traceability, exact parsed Ground Truth equality, no training metadata leak, and all 244 loss masks verified. Source SHA-256 hashes in `manifest.json` must continue to match the frozen Canonical files.

## Configuration drafts

`smoke.yaml` is the 8-row smoke configuration that was executed after separate authorization: 4-bit bitsandbytes NF4, double quantization, LoRA rank 8, batch 1, accumulation 1, cutoff 2,048, and one epoch. The run used a copy with an isolated output directory and retained checkpoints at optimizer steps 4 and 8. `qlora.yaml` remains a conservative 8 GB starting draft (NF4, LoRA rank 8, batch 1, accumulation 16, gradient checkpointing, cutoff 2,048); its save/evaluation interval is now 11 update steps, matching the estimated 11 updates per epoch for 171 train rows at accumulation 16 over three epochs. It uses only train and validation; test and hard_test remain held out.

## Files

- `llamafactory/train.json`, `validation.json`, `test.json`, `hard_test.json`: model-visible rows only.
- `llamafactory/dataset_info.json`: local ShareGPT dataset registration.
- `traceability.json`: one-to-one row-to-source trace, exact target hash, and history round-trip evidence.
- `manifest.json`: source hashes, split counts, export configuration, validation result, and artifact hashes.
- `validation_report.json`: tokenizer/loss-mask and per-split/output token statistics.
- `smoke.yaml`, `qlora.yaml`: the authorized smoke configuration and conservative multi-epoch QLoRA draft. The smoke result and hardware observations are recorded above; the multi-epoch draft was not run.

The smoke completed 8/8 optimizer steps in 75.79 seconds (3.47, 11.40, 10.02, 4.12, 13.99, 9.19, 3.76, and 3.82 seconds). Training loss was 1.4014; evaluation loss was 2.1615 at step 4 and 2.1139 at step 8. Finite losses, non-zero gradients, 16,232,448 LoRA trainable parameters (0.3563% of 4,555,497,984 parameters per LLaMA-Factory), and checkpoints at steps 4/8 confirmed the training path. An isolated resume from checkpoint-4 restored global step 4, optimizer state, and scheduler state and completed step 5; this was a resume check, not an extension of the smoke dataset run. A separate 4-bit NF4 adapter reload then generated 48 tokens using the actual setup system/context and `qwen3_5_nothink` template. `hf_device_map` was unset (no dispatched CPU/disk map); all 1,219 parameter tensors were on `cuda:0`, with zero CPU tensors.

## Smoke hardware observations

On the 8 GB RTX 4060, `nvidia-smi` observed up to 7,872 MiB dedicated memory in use (86 MiB free), while PyTorch reported peak allocated 7,100,336,640 bytes and peak reserved 12,738,101,248 bytes. The PyTorch reserved figure is allocator accounting and can exceed physical dedicated memory under Windows WDDM; it must not be interpreted as dedicated or shared GPU usage. RAM available fell from 9.83 GB at training start to a 4.43 GB minimum; pagefile use rose from 4.39 GB to 4.94 GB. No OOM occurred. A post-run WDDM adapter counter sample showed 92.3 MiB shared usage while idle (not a training peak). This run therefore establishes functional feasibility but leaves little dedicated-memory headroom; preserve batch size 1, gradient checkpointing, and NF4 for a later smoke-reviewed run. No formal multi-epoch QLoRA run was started.

The frozen source is `docs/ai/dataset/canonical_training/v0.1`; changes to it require its own versioned governance process. This setup export is reproducible from the source and script and must be regenerated, not edited by hand, if its inputs change.