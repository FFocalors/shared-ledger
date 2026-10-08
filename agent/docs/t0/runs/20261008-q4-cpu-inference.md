# T0 Q4_K_M GGUF CPU inference

Run: `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge`

This records the three fixed Q4_K_M CPU inference runs. The model was previously audited as a 2,708,804,480-byte GGUF with SHA-256 `acfd01df6cbd3c8e1fa4dbe144f5852290689851c4f92d4ab892707d08724b34`. Runtime used the reviewed C API harness built from llama.cpp commit `b9acf138a1e28ce1fc23b5a4fc4b12444b50f7ea`. All runs used the frozen prompt IDs verbatim, context/batch/ubatch 512, two CPU threads, zero GPU layers, last-prompt-token FP32 logits, and greedy generation. The model and prompt sources were local.

The guarded process-tree runs all exited 0 with `guard_reason=null` and `termination_verified=true`. Each raw logits file is a finite little-endian float32 vector of shape `[248320]` (993,360 bytes). The runtime guard kept available physical memory above its 2 GiB floor in every case.

| Case | Input tokens | Start free GiB | Minimum free GiB | Peak private GiB | Peak working set GiB | Generated tokens | Stop | Raw logits SHA-256 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `shared_ledger_explanation` | 34 | 8.383 | 4.779 | 1.073 | 2.698 | 28 | EOS 248046 | `813e0088444182c5c4e3227ae0af188e3b53cb68946e95682c3b9e05ba1bfa88` |
| `short_arithmetic` | 36 | 8.259 | 5.560 | 1.073 | 2.699 | 3 | EOS 248046 | `ec91b6305a616bd1c0b1039eb1f308e877a9de02c139ca2e4de08bc0ce41d52c` |
| `agent_answerdecision_json` | 69 | 13.167 | 10.567 | 1.073 | 2.705 | 23 | EOS 248046 | `d8813563fdbb11f38a42f41f47d5ceee032a8d158c9e293b42b3e64a3e9a956e` |

The pinned llama.cpp runtime reported the same allocations in all three stderr logs: CPU mapped model buffer 2,572.86 MiB, CPU KV buffer 16.00 MiB, and CPU compute reserve 510.53 MiB. The context teardown confirmed the compute allocation matched its reserve. This is the observed Q4 runtime footprint for the configured 512-token context; it is not a claim about other context sizes or backends.

Content checks were performed separately from runtime capture using the local slow `Qwen2Tokenizer` (`local_files_only=true`; no model weights loaded). The explanation decoded to “A shared expense ledger is a centralized digital record that allows multiple people to track, approve, and reconcile their joint spending in real time.” and was non-empty. The arithmetic output decoded exactly to `42`. The answer-decision output decoded exactly to `{"kind":"answer","basis":"conversation","text":"T0_SMOKE_OK","citations":[]}`; strict JSON parsing used a duplicate-key rejection hook; no duplicate keys were present, and the parsed object matched the expected values. Every generated token ID was within the local tokenizer's range. The tokenizer reports `len=248077` and `vocab_size=248044`, while the GGUF exposes 248320 tokens; these particular generated IDs all decoded within range.

Per-case raw outputs are in `step4-converter\gguf-cpu-outputs\q4_k_m\<case-id>\`. Guard stdout, stderr, command, tree, telemetry, and metadata are in `step4-converter\command-logs\gguf-q4_k_m-<case-id>.*`.

HF raw-logit comparison, F16 CPU inference, and the remaining step-4 comparison are pending. These Q4 runtime and content checks do not report an HF/GGUF logits match.

