# T0 HF Loader and Inference Report

记录时间：2026-10-08（Asia/Shanghai）。本报告只记录 HF 路径；所有运行文件、权重副本、offload、缓存和日志都在 `D:\AI`。没有训练、读取或改写真实账本，也没有向云端传输模型或数据。主工作区 `D:\project\Android\shared-ledger` 与并行 P1 文件未修改；没有 stage 或 commit。

## 结果

实际 HF inference 使用单次 `accelerate.load_checkpoint_and_dispatch`，比较原始 base+adapter 与 attempt-3 merged checkpoint。两个 v4 attempt 都由 PID-tree guard 以 exit 0 结束，`guard_reason=null`、`guard_abort=false`、`termination_verified=true`。三组固定输入均保存了 full-vocabulary raw logits 和 greedy generation。每个 raw logits NPY 是有限值 `float32[248320]`，输入 ID 与冻结 prompt 完全匹配。

`base_adapter` 与 `merged` 的三组生成 token IDs 和原始解码文本逐字相同，输出分别是 28、3、23 个 token，均以 EOS 结束。算术样例为精确文本 `42`；JSON 样例通过拒绝重复键和非法常量的独立解析，并与冻结的 expected object 完全相等：`{"basis":"conversation","citations":[],"kind":"answer","text":"T0_SMOKE_OK"}`。解释样例由 root 审阅为正常；runner 的自动检查本身只检查非空，不能单独代表解释质量已通过。

## Builder 与输入源

CPU raw-copy builder PASS，输出在 `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\combined-peft-attempt1\`。manifest 声明 1,219 tensors、9,143,468,544 payload bytes、全目标 reread match；723 个原 base tensors 与 496 个 adapter tensors 保持源 bytes/dtype，没有 merge 或 cast。三份源文件的 before/after SHA 相等：

- `D:\AI\models\Qwen3.5-4B\model.safetensors-00001-of-00002.safetensors` — `26a93f066e1916adb13453dae5a0c707c0fbc71299ed98779571a907b8e74c61`
- `D:\AI\models\Qwen3.5-4B\model.safetensors-00002-of-00002.safetensors` — `cb544bd9bfae93dc59b0f22b292f5933573854a7f9b97835c67060d7d910e188`
- `D:\AI\runs\shared-ledger\training_runs\qlora-v0.2-experiment-a-only\20261002-0859\checkpoints\checkpoint-36\adapter_model.safetensors` — `2bd4458c59903af11dcdc78b1ad2a42dab06a00bc48ad2735e5ecc1e35eba8f9`

`D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\combined-peft-attempt1\combined-checkpoint-manifest.json` SHA-256 `db1b0da730e61046119b69b7443cd8e2890bea0a95651f381fd8bc5698ee9352`; `model.safetensors.index.json` SHA-256 `c2337db719bae2efbfcd10d433019a836e539940f21b2dabc6fa4ff48486a198`. Builder source `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\scripts\build_combined_peft_checkpoint.py` SHA-256 `543d5af78718b1cb4de9cde11e615cc1f08391a2360e7472701f0d611d5102ce`. Builder guard logs remain under `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\step4-converter\command-logs\combined-peft-builder-attempt1-20261008-1635.*`.

## Loader修复依据与 v4 变更

旧 v3 实际 device map 把 decoder layers 12–31 放在 disk。Qwen3.5 的 `Qwen3_5GatedDeltaNet.forward` 对单 token cached decode 直接读 `self.conv1d.weight.squeeze(1)`（`D:\AI\.venv\Lib\site-packages\transformers\models\qwen3_5\modeling_qwen3_5.py:455-463`）；torch fallback 随后把该权重传给 `F.conv1d`（同文件 :210-224）。Accelerate offload hook 对 disk child 参数逐个挂钩；`preload_module_classes` 命中时才在 parent forward 开始前递归加载注册子模块并停止 child hooks（`D:\AI\.venv\Lib\site-packages\accelerate\hooks.py:502-524`）。Accelerate 的 API 文档明确把“forward 直接使用已注册子模块 weight”列为该选项用途（`D:\AI\.venv\Lib\site-packages\accelerate\big_modeling.py:564-570`）。

v4 在同一单次 dispatch 中加了 `preload_module_classes=["Qwen3_5GatedDeltaNet"]`，并把模型 canonical `core._skip_keys_device_placement` 原样传为 `skip_keys`；Qwen3.5 值为 `past_key_values`（modeling source :802），Transformers Accelerate integration 也从该属性传 `skip_keys`（`D:\AI\.venv\Lib\site-packages\transformers\integrations\accelerate.py:385-386`）。缓存、权重、dtype、冻结 IDs、greedy 设置与 `use_cache=True` 均保持不变。

runner 额外在 disk 映射的 GatedDeltaNet cached kernel 入口包装原函数，只记录每层前两次调用的 weight/conv-state/hidden/output device、dtype、shape 和 `is_meta`，不读取 weight 数据、不改变函数参数或返回值。两 variant 每个 case 均命中 15 层、各两步（30 条事件）；被观测 conv weight 全为 `cuda:0`、`torch.bfloat16`、`is_meta=false`，conv state 与 hidden state 也在 cuda:0。此次加载与生成结果支持 cached offload 路径是旧 v3 垃圾输出原因的判断；由于 preload 与 canonical skip_keys 同时启用，没有分别 ablate 两个参数的独立因果作用。

## Runtime 与数值对照

Wrapper 在启动时要求 RAM ≥7.3 GiB、GPU free ≥5632 MiB；运行 guard 保留 RAM hard floor 2 GiB、tree private ≤16 GiB、working set ≤5.5 GiB、GPU free ≥512 MiB；device map 上限为 GPU 4 GiB、CPU 1 GiB，其余放 D 盘。base_adapter 启动采样为 RAM 13.239 GiB / GPU free 6286 MiB；merged 启动采样为 RAM 13.433 GiB / GPU free 6305 MiB。两个 attempt 已终止并验证进程树结束，模型槽于 19:32 +08 复核无 Python 推理进程后释放。

v4 比较文件的 `PASS` 只表示输入、向量和 artifacts 成功比较，不代表数值严格等价。三组 logits 均非逐位相等，但 argmax 相同；确定性 greedy 下生成 IDs 与文本全相同：

| 冻结 case | max abs diff | RMSE | 相对 base RMS 的 RMSE | cosine | argmax 相同 | generation IDs 相同 |
|---|---:|---:|---:|---:|---|---|
| shared_ledger_explanation | 0.25 | 0.0436388303 | 0.0219129283 | 0.9997798528 | 是 | 是 |
| short_arithmetic | 0.1796875 | 0.0332042463 | 0.0178569768 | 0.9998405661 | 是 | 是 |
| agent_answerdecision_json | 0.3125 | 0.0515289498 | 0.0260222654 | 0.9996614901 | 是 | 是 |

没有设置事后数值阈值。相同的三个生成结果也不建立全域 numerical equivalence 或任意 prompt 的语义质量保证。v4 的 raw logits 直接 forward 使用 `use_cache=False`；generation 保持 `use_cache=True`。

## 旧尝试保留情况

旧输出和日志均未覆盖或删除。v1 静态语法检查在 `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\logs\script-syntax-check-v1.stderr.txt` 记录 runner 第 335 行拼接产生的 `SyntaxError`。v2 `hf-base_adapter-accelerate-v2-attempt1` 在 tokenizer Mapping 被当作 ID iterable 时以 `ValueError: ... 'input_ids'` 退出，见其 python stderr 和 `tree-end.json`；v3 增加 Mapping、Encoding.ids 和 list/flatten 兼容。v3 的两路 raw captures 已完成，但 cache 开启时解释/算术 generation 为乱码；旧文件仍在 `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\hf-inference\base_adapter-accelerate-v3-attempt2\`、`merged-accelerate-v3-attempt2\` 和 `hf-model-comparison-accelerate-v3-attempt2.json`。v4 是新的 attempt1，未复用旧输出目录。

## Evidence paths 与 SHA-256

| Artifact | Absolute path | SHA-256 |
|---|---|---|
| v4 runner | `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\scripts\hf_inference_accelerate_v4.py` | `182d20aaff46961762e3a937013eb95ba6baf8273e9023ad58843d8536eeb1f7` |
| v4 wrapper | `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\scripts\run-hf-inference-accelerate-v4-attempt1.ps1` | `18bf908778be2294a0402839f47b5f4f830d2ba418515952baf0e64be7c6453f` |
| v4 comparator | `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\scripts\compare_hf_logits_accelerate_v4_attempt1.py` | `bea1c65ba80fe22b2ef8e64adfa873ae771741c8ed3c91bfe2a77d7b0126673b` |
| base_adapter result | `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\hf-inference\base_adapter-accelerate-v4-attempt1\inference-result.json` | `662235fb643240e0e081f3c6075037cbbbedb597e70bd2feb1d370c7a2e068ca` |
| merged result | `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\hf-inference\merged-accelerate-v4-attempt1\inference-result.json` | `75f1ad06046817bb66699cbf64c0492c58bf2ca64b214ebc3b3337ad12e186eb` |
| base_adapter independent verification | `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\logs\hf-base_adapter-v4-attempt1-verification.json` | `e2dc7468b89954c6603fc54d554b78c57bfed85364ea964812104a021b8fcd57` |
| merged independent verification | `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\logs\hf-merged-v4-attempt1-verification.json` | `5fac0e301d9d0067a080b8ed749b8054177c983b52f3212c3db58fb72b7ed96a` |
| HF comparison | `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\hf-inference\hf-model-comparison-accelerate-v4-attempt1.json` | `b5ba3d1480591c63b07c6625923024650576d7ad53ebdb0c78c8778422102f7e` |
| base_adapter guard terminal | `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\logs\hf-base_adapter-accelerate-v4-attempt1.tree-end.json` | `9a889b0a7264852e72e1751be684a88d1b16a04cb6ee8835792cbc98bb64033a` |
| merged guard terminal | `D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\logs\hf-merged-accelerate-v4-attempt1.tree-end.json` | `10f8824b6d39e568027a5d6c4a713032c014053df8efef9ca70aaa7f32c2233e` |

Each variant's raw logits, raw logits metadata, generation JSON, preflight, stdout/stderr and telemetry remain in their corresponding absolute run directories. Verification JSON records each NPY and generation SHA. The frozen case manifest SHA-256 is `cb65dd89ee1b9bd3e537090305b92a85046ef57b1f16b06490eb55ade920d93e`. HF step 3 raw logits and greedy generation are now captured; F16/Q4 comparison and later T0 housekeeping remain separate work.
