# T0 步骤 4：Qwen3.5-4B F16 / Q4_K_M 转换记录

记录时间：2026-10-08（Asia/Shanghai）。共享 run 根：`D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\`。本报告记录真实转换和 GGUF metadata/hash；固定输入的 HF/F16/Q4 logits 与生成对照尚未完成，故步骤 4 的对照验收仍 pending。当前没有 LM Studio 导入/加载、Teacher、长期训练、账本数据或工具调用。

## 输入与转换前硬门

输入为步骤 3 attempt 3 的合并目录 `merged-hf-attempt3\`，架构 `Qwen3_5ForConditionalGeneration`，tied embeddings=true、没有 `lm_head.weight`。attempt 3 merge 通过主审；两个输入 shard SHA-256：

- `model.safetensors-00001-of-00002.safetensors`：`9462882722b4b97c847f483877667dbd6b14c372c177bbfeb979f016e29f36ca`
- `model.safetensors-00002-of-00002.safetensors`：`63b8c849d60c8bbef69d54c21fc72a89c56032c5b65db54bb4cba876b911ebdf`

为控制单个最大 embedding 的峰值，helper 在独立 D 目录 `step4-converter\intermediate\merged-hf-f16ready\` 逐 64 MiB 将 `model.language_model.embed_tokens.weight` 从 BF16 经 torch FP32 再按 NumPy little-endian F16 转换；其他 737 个 tensor payload 和所有其他文件按字节复制。helper 的逐 chunk 复核与 safetensors header/offset/index/config 检查均通过，输入源 shard 前后 hash 一致，源目录没有被改写。

实际 manifest：`step4-converter\intermediate\merged-hf-f16ready\f16ready-conversion-manifest.json`，SHA-256 `D0F1FC0D57E5139C63D858B25D5983BF1C8527438624FB6A2ECA8238141ECA60`。汇总为 verified=738、converted=1、byte-identical=737；source_nonfinite=0、output_nonfinite=0、finite_overflow_to_inf=0，因此 converter-ready gate=true。F16 下溢成零为 1,255 个值，单独记录；本门只允许 BF16→FP32→F16 标准舍入，不屏蔽非有限值或有限值溢出。所用 helper SHA-256：`77F667B900698216907971FC5FFB114F5FE8F2D978BB124B45B88831259C8640`。

## 工具与实际命令

使用 D 盘隔离工具，不改变 `D:\AI\.venv`、全局 Python、CUDA 或 Visual Studio 环境。llama.cpp 固定提交为 `b9acf138a1e28ce1fc23b5a4fc4b12444b50f7ea`，checkout 在运行时 clean；转换器、GGUF reader、C API harness 与 quantizer 来自同一提交。隔离 venv 版本：Python 3.11.15、NumPy 2.2.6、PyTorch 2.11.0+cpu。CPU quantizer 二进制 SHA-256：`C8E52FA79F32BFB0DA949A4F80077F6AF4A478B8EE502CABD8D72E09448B48DF`；C API harness `build-sdk-ninja\t0_gguf_compare.exe` SHA-256：`21141EA88839F89F1B2E1EE4D7AEF1BE5E21D4AFBA7E80265C5A41A357354319`，其源码 `gguf_compare.cpp` SHA-256：`38C25A30FC74DBA149BD6FB8E38A083EB3A296B10078349A288EE8215C794597`。完整 child stdout/stderr、时间、退出码、复现参数、进程树和遥测均在 `step4-converter\command-logs\`；heavy commands 由 D-only wrapper `run_heavy_guard.ps1`（SHA-256 `8C876DD9B368AFB1072D2AAD2874BBD5F97D9ACA172A87DC31E785961CFCE928`）记录。wrapper 经 PowerShell AST 检查及拥有进程树的正常退出 smoke 验证；运行时使用 PID+创建时间追踪自有树，available RAM 低于 2 GiB 或树 private commit 超 8 GiB 时终止并验证仅自有进程树。

官方 F16 转换命令明确带 `--no-mtp`，排除 source 中 15 个 MTP/NextN tensor。固定候选源码在 `convert_hf_to_gguf.py` 支持该 flag；Qwen3.5 mixin 在 `no_mtp` 下维持常规 `num_hidden_layers`，不写 nextn metadata，也过滤 `mtp.*`。

实际命令：

```powershell
D:\AI\tools\venvs\llama-cpp-b9acf138a1e28ce1fc23b5a4fc4b12444b50f7ea\Scripts\python.exe -B D:\AI\tools\llama.cpp-b9acf138a1e28ce1fc23b5a4fc4b12444b50f7ea\convert_hf_to_gguf.py --outtype f16 --no-mtp --outfile D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\step4-converter\artifacts-attempt3\qwen3.5-4b-f16.gguf D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\step4-converter\intermediate\merged-hf-f16ready
D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\step4-converter\build-sdk-ninja\bin\llama-quantize.exe --max-buffer-size 512 D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\step4-converter\artifacts-attempt3\qwen3.5-4b-f16.gguf D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\step4-converter\artifacts-attempt3\qwen3.5-4b-q4_k_m.gguf Q4_K_M 2
```

Both commands exited 0. F16 conversion took 38.289 s; its resource guard observed minimum free RAM 8.848 GiB, maximum process-tree private commit 1.567 GiB, maximum tree working set 0.669 GiB. Q4 quantization took 120.608 s; minimum free RAM was 3.322 GiB, maximum process-tree private commit 0.417 GiB and maximum tree working set 8.251 GiB. Neither guard fired. No model load ran concurrently.

## GGUF 结构、metadata 与 hash

| 产物 | 大小 | SHA-256 | GGUF 类型 | Tensor descriptors / 类型 |
|---|---:|---|---|---|
| `artifacts-attempt3\qwen3.5-4b-f16.gguf` | 8,424,393,600 B | `37fb4e8627a0076160429d26ef6454a1a20a6c824bdfd681c9695dece4d49f13` | `general.file_type=1 / MOSTLY_F16` | 426；F16=249、F32=177 |
| `artifacts-attempt3\qwen3.5-4b-q4_k_m.gguf` | 2,708,804,480 B | `acfd01df6cbd3c8e1fa4dbe144f5852290689851c4f92d4ab892707d08724b34` | `general.file_type=15 / MOSTLY_Q4_K_M` | 426；Q4_K=216、Q6_K=33、F32=177 |

两个产物的 metadata audit 均通过：architecture=`qwen35`、常规 block_count=32、`qwen35.nextn_predict_layers` absent、MTP/NextN tensor name 数为 0；tokenizer token list 数=248,320、EOS=248,046、PAD=248,044，`qwen35.rope.dimension_sections=[11,11,10,0]`。GGUF 保存了 `tokenizer.ggml.tokens` 的完整词表，但没有单独写 `qwen35.vocab_size` 字段；审计明确将该字段记为 null，并用实际 token list 数 248,320 做硬门。F16/Q4 metadata JSON 分别为 `command-logs\attempt3-f16-metadata-audit-v2.stdout.txt` 和 `command-logs\attempt3-q4-metadata-audit.stdout.txt`；审计器按该 pinned reader 读取的绝对 tensor offset 检查所有 ranges 在文件界内且不重叠。

Q4 日志报告模型大小 8,023.67 MiB、量化大小 2,572.86 MiB、5.13 BPW。Quantizer 的 426 tensors 全部处理完成。F16/Q4 SHA 的逐文件流式 hash 结果分别在 `command-logs\attempt3-hash-f16-gguf-v2.stdout.txt`、`command-logs\attempt3-hash-q4-gguf.stdout.txt`；命令运行时间和退出码在对应 `.meta.json`。

## 固定输入与待完成的对照

冻结 cases manifest：`cases.json` SHA-256 `CB65DD89EE1B9BD3E537090305B92A85046EF57B1F16B06490EB55ADE920D93E`；prompt manifest：`hf-inference\prompts\prompts-manifest.json` SHA-256 `8B50180B29CE1E38F159471A7B0EA619907F3A318182C4D1BDCBABC3CB3F6282`。三个 synthetic case 为 `shared_ledger_explanation`、`short_arithmetic`、`agent_answerdecision_json`；input IDs 长度分别 34/36/69，生成上限分别 32/16/96，EOS 248,046，context 512。没有账本数据或工具调用。

截至本报告，HF base+adapter 的既有尝试未输出可比较 raw logits/generation：v1–v3 由已审内存保护门安全结束；v5 在 PEFT attach 阶段遇到本地路径解析 KeyError，随后验证 owned tree 已退出且没有模型结果。HF agent 正准备 root 审过的新单次加载方案。步骤 4 的 C API harness 已构建，但尚未加载 F16/Q4 GGUF，也没有生成 raw logits/generation 比较件。待 HF 成功产出 raw unmerged/merged logits 与固定输入 generation 并释放重资源 slot 后，再串行执行 F16/Q4 三个 case 的 C API 对照；raw float32 全 vocab、shape/finite、argmax/top-k 和数值差异均要记录，不能以相同文本替代 raw-logit 比较。该步骤未覆盖图像/视觉路径；不应据此宣称新版模型质量或 CAP 通过。

## Evidence map

- F16ready helper：`command-logs\attempt3-f16ready-embedding-conversion.{command.txt,stdout.txt,stderr.txt,meta.json,telemetry.jsonl,tree-start.json,tree-end.json}`。
- F16 official conversion：`command-logs\attempt3-convert-f16-no-mtp.{command.txt,stdout.txt,stderr.txt,meta.json,telemetry.jsonl,tree-start.json,tree-end.json}`。
- Q4 quantization：`command-logs\attempt3-quantize-q4-k-m.{command.txt,stdout.txt,stderr.txt,meta.json,telemetry.jsonl,tree-start.json,tree-end.json}`。
- metadata audits and streaming SHA logs：`command-logs\attempt3-f16-metadata-audit-v2.*`、`attempt3-q4-metadata-audit.*`、`attempt3-hash-f16-gguf-v2.*`、`attempt3-hash-q4-gguf.*`。
- Helper manifest and GGUF audit tools stay under `step4-converter\`; original merged source remains intact. No file was staged, committed, or pushed; no P1/main/database file was edited.

