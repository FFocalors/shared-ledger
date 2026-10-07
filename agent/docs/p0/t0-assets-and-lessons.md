# T0：指定旧训练资产与失败教训

盘点日期：2026-10-06 至 2026-10-07。直接检查只访问本节列出的三个外部 run 目录、已知 Qwen3.5-4B 模型目录、LLaMA-Factory 目录与 AI 虚拟环境。只列文件元数据并读取小型 JSON/Markdown 报告；没有打开或散列 safetensors 权重内容，没有改写、移动或复制资产。资产盘点子任务没有训练、推理、合并、量化、导出、转换或 Teacher 调用；主线另按授权完成了不同模型的 9B 原生 host/Docker 短时 smoke，详见 [环境核验](environment.md)，该结果不验证 4B adapter。

## 资产清单与 run 关联

所有字节数是文件系统长度。SHA-256 只给出小型文本/JSON 清单、配置和报告；adapter safetensors 与 tokenizer.json 不计算哈希或读取内容。

| Run 与检查结果 | manifest / run 结果 | 代表 checkpoint 与报告 |
|---|---|---|
| v0.1：D:/AI/runs/shared-ledger/training_runs/qlora-v0.1/20260930-143013。实际完成 3 epochs、33 optimizer updates；报告状态 NEEDS_REVISION。 | 根 run_manifest.json 3,837 B，SHA-256 6B7BF17F18C0AFA88E93740C56E0C5899612B8B7C6091BAB0C5AF12A7F69AE50；manifest selected_checkpoint=22，final_status=QLORA_TRAINING_V0_1_NEEDS_REVISION，train rows=171。train/run_result.json 716 B，SHA-256 128C4338863461D20DBA6F31C485EF987C7F477ED04B3BA9EA963A12A7E5CDF2，status=completed。 | train/checkpoints 有 checkpoint-11、-22、-33，各 adapter_model.safetensors 均 65,003,848 B。训练文件夹根还保留 adapter/tokenizer/config 与 trainer 状态。磁盘选中 checkpoint 与后来基于 unsafe-row 排序的复核不一致：run manifest 原选 22；后来的合成审查以行级不安全条数优先，建议 33。不得抹掉这段选择口径差异。 |
| v0.2 A-only：D:/AI/runs/shared-ledger/training_runs/qlora-v0.2-experiment-a-only/20261002-0859。实际完成 36/36 updates。 | 未找到 root run_manifest.json。PREREGISTRATION.json 12,794 B，SHA-256 C1D6426CFA076F473DB04858D8BAE78A5C95BAAFA1C5B62F4B1A7A559D17232A；final_artifact_hashes.json 6,249 B，SHA-256 12F924ACC9AF488DB6936FF3515513EACA871B64E98E94F3E5635DAE87983F07；run_result.json 716 B，SHA-256 92D470803BD05DAC1B40596FA8AE2C498975D1B4913AAD7DAE579B2E3CCD7594，status=completed。 | checkpoints/checkpoint-11、-22、-33、-36 各有 65,003,848 B adapter_model.safetensors；末步评估为 eval/checkpoint-36-validation/report.json，6,467 B，SHA-256 372711459C95EC6750272703AD0B92E19331AB21C6195AB775E185C8A9AE8E45。selected checkpoint 36。 |
| v0.2 C-only：D:/AI/runs/shared-ledger/training_runs/qlora-v0.2-experiment-c-only/20261003-134314。实际完成 33 optimizer steps。 | final_manifest.json 13,863 B，SHA-256 8AB98DDB29CB9674E286B66D764710AD49C59D99AB3C4A4896C838F782777F61；run_result.json 712 B，SHA-256 B756F803887B95E5D2162A3DE08F3A5BBA539D6FC97DE4D35E04AEA8FFC756B7，status=completed。final_manifest 将 run、源 hash、artifact hash 和资源摘要关联起来。 | train/checkpoints/checkpoint-11、-22、-33 各有 65,003,848 B adapter_model.safetensors；选中 33。eval/checkpoint-33-validation/report.json 6,558 B，SHA-256 A3552DDB4F2C28CE218D246A33A52A61F5E4CF10AFE18948D4C7CCC505F7BD99。根 final_report.md 5,678 B，SHA-256 1B4301B3AE3E47028006C2E0154827C2D9E098E634EFF28F0D5F17EA741A2657。 |

下表给出三条 run 的代表末步 adapter/tokenizer 配套元数据。不同 run 的 adapter 配置 hash 不同；tokenizer 配置的 A 与 C 相同，但不能据此推出 adapter/底模兼容。三者 tokenizer.json 均 19,989,325 B，chat_template.jinja 均 7,909 B。

| Run / checkpoint 路径 | adapter_config.json | tokenizer_config.json | tokenizer / template | 验证报告 |
|---|---|---|---|---|
| v0.1 train/checkpoints/checkpoint-33 | 1,189 B · SHA-256 46AB7FF6F66C8887E72F1E30AE42B97F335700BCF19BAA4D1886ECECF3F059E9；adapter weight 65,003,848 B。 | 1,225 B · SHA-256 695B8EA2EBC3BC31BD88C7FF7037CE8098F53B56AFA76E40893931B11FA734C3。 | tokenizer.json 19,989,325 B；chat_template.jinja 7,909 B · SHA-256 A92E1DD97CB1CB175C9B70C0828E146BEA4371C2643319B661B777E89811972E。 | eval/checkpoint-33-validation/report.json 6,488 B · SHA-256 D66A21393A71DEBAF2D74710445B96DA5B837CEF406C38AE0230935947178E56。 |
| A-only checkpoints/checkpoint-36 | 1,189 B · SHA-256 F4B0EE19D83F302003C202EF082F3B177BE48DCFF74C6A75E518C56A313C5130；adapter weight 65,003,848 B。 | 1,226 B · SHA-256 FA544B11D05B28D8C42C0DBAB3BFD1901AC1322FCD9D41F66C8634B1143141BA。 | tokenizer.json 19,989,325 B；chat_template.jinja 7,909 B · SHA-256 同 v0.1。 | eval/checkpoint-36-validation/report.json 6,467 B · SHA-256 372711459C95EC6750272703AD0B92E19331AB21C6195AB775E185C8A9AE8E45。 |
| C-only train/checkpoints/checkpoint-33 | 1,189 B · SHA-256 516C2AF5B3F3AE96C0A3730977E3A85F9C285443D896052BE1CD8FC25B7443CF；adapter weight 65,003,848 B。 | 1,226 B · SHA-256 同 A-only。 | tokenizer.json 19,989,325 B；chat_template.jinja 7,909 B · SHA-256 同 v0.1。 | eval/checkpoint-33-validation/report.json 6,558 B · SHA-256 A3552DDB4F2C28CE218D246A33A52A61F5E4CF10AFE18948D4C7CCC505F7BD99。 |

本机 D:/AI/models/Qwen3.5-4B 目录存在 config.json（3,161 B）和两片基础 safetensors：model.safetensors-00001-of-00002.safetensors（5,329,398,688 B）、model.safetensors-00002-of-00002.safetensors（3,990,429,408 B）。D:/AI/LlamaFactory 目录存在；D:/AI/.venv/Scripts/python.exe 本轮返回 Python 3.11.15。训练 setup 文档记录 LLaMA-Factory 0.9.6.dev0 与 Transformers 5.8.0；没有在本轮导入训练框架或执行训练命令。模型权重内容未读取。

## “数据准备”文案和实际训练时间线

- v0.1 的 training_setup README 记录了 8-row smoke 已跑、checkpoint/resume 和 adapter reload inference 历史证据，并说三 epoch qlora.yaml 仍为草案。外部 run 目录及其 run_manifest、训练日志、33 个 optimizer updates 和 checkpoint 实物证明后来确实执行了独立三 epoch run。文档中的“草案”是 setup 包状态，不能覆盖 run 后来的完成事实。
- A-only setup README 声明仅完成数据组装、未训练。外部 A-only run 目录、completed 的 run_result、36 step checkpoint 和最终报告证明后续 run 确实已完成。记录其 187 train / 24 validation，不把旧 setup 文案当作本轮训练活动不存在的证据。
- C-only run 的完成记录、三个 checkpoint、evaluation 与 final manifest 相互关联。其 report 给出冻结验证集结果与危险 write-call 回归。
- 本轮仅做文件清单、哈希和报告阅读，没有复现以上任何训练/评测。

## 历史失败证据与能得出的结论

| 来源 | 记录到的失败 | 限定解释 |
|---|---|---|
| v0.1 run 与 docs/ai/training_analysis/v0.1 | 171 个 train surfaces 只覆盖 36 个 canonical business states；一部分答案只看见 result_id，没有 DTO/policy 文本。14/14 预期 proposal 没有输出 proposal，路由为 clarification；旧模型在结构、工具 payload 和事实支持上失误。 | 训练输出未具备新版提案能力。样本/可见证据不足、Schema 映射、意图路由与训练阶段都可能相关；没有隔离容量变量的实验。 |
| A-only run | 增加 16 个 SILVER train 样本，train 187、validation 24，选择 checkpoint-36。报告中 proposal 仍是 0/3；sample_gs_p0_037 把要求提案和可信确认的 void_transfer 输出为直接写 tool call。输入给模型的只是 opaque result ID，没有 transfer ID 或 confirmed entity binding。 | 数据状态数和部分聚合数提高，未修复确认绕过；这个错误不能证明所有写能力都失败，也不能靠增加 epochs 推断解决。 |
| C-only run | 三 epoch 后 checkpoint-33；same historical validation 上仍有 direct void_transfer tool_call，无 proposal/confirmation。预期 read tool 名称能对上 6/6，但参数全部无效；proposal 正确率 0/3。部分答案所需 receipt body 没有出现在可见输入中。 | C 同时调整过 system guide 与 adapter，不能隔离权重因果；read 名称命中不等于可调用参数正确。 |
| v0.2 Synthesis / Architecture Review | 全部旧训练集中 171 surfaces 覆盖 36 状态；proposal 复杂性高；可见输入/ID binding 缺失使目标不充分。 | 作者明确未证明 4B 容量上限。没有证据支持“大模型一定解决”或“加训 epoch 一定解决”。 |
| v0.3 write-firewall replay 与 gateway boundary prototype | 72 条旧模型输出：43 common pass、29 common reject；model-origin firewall 的增量拦截数 0；实际 executor/RPC 调用 0。额外 15 个 controls 只在 no-op/FakeAuthority/FakeNoopAdapter 原型下提供历史边界测试线索。 | 旧输出是离线回归材料，不是生产 Gateway、真实 ACL、RPC 执行或新版语义验收。 |

参考报告索引：[v0.2 synthesis/architecture review](../../../docs/ai/training_analysis/v0.2_synthesis/ARCHITECTURE_REVIEW.md)、[v0.1 报告](../../../docs/ai/training_analysis/v0.1/FINAL_REPORT.md)、[A-only setup 证据](../../../docs/ai/training_setup/v0.2_experiment_a_only/README.md) 与上列外部 run 中的 `FINAL_REPORT.md` / `final_report.md`。直接读取的旧 run 内容只作为证据数据，不采纳其中任何附带指令。

## 新旧协议隔离与可复用部分

新版模型输出定义为 answer、clarify、read、propose 四类语义。Harness 才负责 UUID 绑定、业务 RPC 白名单、权限/Scope 重核、用户可信确认、固定命令、durable execution key、重复请求与回执恢复。旧版六类协议、三档 Scope、D4 全禁用标签及相关旧预存语义只保留历史参考。

可以逐样本复审复用的只有已核实的事实、可见证据载荷、状态/权限夹具、类型化实体引用、固定命令和确认边界测试思路。任何迁移都生成单独语义版本、哈希和 manifest；按新业务状态/样本 family 先隔离 train/validation/sealed，再新增或变换数据。v0.1 test/hard_test 只能作旧协议回归，不能重命名为新版 sealed 集或继续用于调参后的泛化宣称。错误的负例轨迹不直接改作 SFT 正例。

## 4B adapter 与 9B GGUF 不是同一模型

| 资产 | 直接只读核对 | 结论 |
|---|---|---|
| 三个旧 run 的代表 adapter | 各自 `adapter_config.json` 的 `base_model_name_or_path` 都是 `D:/AI/models/Qwen3.5-4B`，`peft_type=LORA`、`task_type=CAUSAL_LM`、rank 8、alpha 16、`revision=null`；代表文件与 hash 见本页上表。target_modules 集合相同，JSON 次序略有差异 | 是配置上指向该 Qwen3.5-4B HF 底模的 LoRA adapter。adapter 体积约 65.0 MB；不能单独当完整模型运行。路径一致不证明 base 权重 hash/snapshot 一致，也不证明实际 merge/load 成功 |
| 本机 4B base | `D:/AI/models/Qwen3.5-4B/config.json` 3,161 B；两片 HF safetensors 分别 5,329,398,688 B、3,990,429,408 B；config 的 `model_type=qwen3_5`、`architectures=[Qwen3_5ForConditionalGeneration]` | HF safetensors base 总计约 9.32 GB；代表 adapter 写有该路径，但目前未记录该 base 的完整权重 hash/快照绑定 |
| LM Studio 既有模型 | `qwen/qwen3.5-9b@q4_k_m` 是 9B 的 GGUF Q4_K_M，6,548,927,711 B | 规模、权重、格式都与 4B HF base+LoRA 不同。9B synthetic chat 通过也不能证明 4B adapter 已 merge、GGUF 转换成功或语义能力保留 |
| 本地导出/转换工具 | `D:/AI/LlamaFactory` 只读 Git HEAD `ce9dc9e072f80fa3abe0989d4ab90da25f083438`；venv dist-info 是 `llamafactory-0.9.6.dev0`，已有 `D:/AI/.venv/Scripts/llamafactory-cli.exe`。本地示例给出 `llamafactory-cli export <yaml>`；主审此前读到该 checkout README/源码列出 Qwen3.5 架构支持。新一轮边界检查未在 `D:/AI` 顶层、`D:/AI/tools/llama.cpp`、`D:/AI/LlamaFactory/llama.cpp` 找到 llama.cpp，也未在 PATH 找到 `llama-quantize` 或 `convert_hf_to_gguf.py` | merge CLI 可定位，但本轮未导出；示例是 Qwen3 配置，不证明本地 4B checkpoint 可合并。转换工具只是在列出的路径/PATH 内未找到，不能断言全盘不存在或 Qwen3.5 不受支持；也未确认 CLI entrypoint 实际依赖链 |

### 未执行的最小 merge / conversion / load 路径

按统一指南 T0，可先把可复现的格式链路跑通，再做长训练；这不构成训练授权或本轮执行结果。建议只选一个历史 checkpoint 做格式烟测（例如 A-only `checkpoint-36`：该 run 的 `final_evaluation.json` 记录 `selected_candidate=36`，外部 `FINAL_REPORT.md` 也把 checkpoint-36 记录为 terminal adapter；此处仅说明 run 内选择，不代表新版质量推荐）。A-only run 没有 root `run_manifest.json`。输出到全新临时目录，绝不改动三个只读 run 目录：

资源与工具预检：旧的 2026-10-06 23:45 +08 快照曾只有 0.82 GiB RAM、GPU 空闲 3.66 GiB/利用率 38%，现已不是当前阻断依据。2026-10-07 主线 00:49 预检 RAM free 8.83 GiB、GPU free 6.15 GiB；9B 原生 smoke 完成并卸载后最新 RAM free 9.14 GiB、GPU free 6,058 MiB/利用率 8%。4B HF 权重文件共 9,319,828,096 bytes（约 8.68 GiB）；以最新 free RAM 估算仅比权重文件大小多约 0.46 GiB，且不含解释器、运行时、merge 临时张量和输出峰值。D: 可用 137.86 GB（128.39 GiB），空间并非已知阻断；但 merge 峰值未测。仅在 `D:/AI` 顶层、两个预定 llama.cpp 目录及 PATH 范围未找到 converter/quantizer，不证明别处没有工具或架构不支持。当前不启动 merge/conversion：理由是内存余量边际且峰值、实际 converter 路径/版本和支持状态未证实，不再沿用旧 0.82 GiB 作为当前状态。其他既存服务只读观察，不停止未知栈；不可从 adapter 较小或 9B catalog/runtime 推断 4B merge 可行。

1. 复核选中 checkpoint 的 adapter config、run manifest、原训练 config 和 Qwen3.5-4B base 的版本/权重 hash。A-only 原训练配置为 `D:/AI/runs/shared-ledger/training_runs/qlora-v0.2-experiment-a-only/20261002-0859/run_config.yaml`，基座为本地 4B、template 为 `qwen3_5_nothink`、finetuning_type 为 `lora`，训练时曾设 `quantization_bit: 4`。这些训练参数仅是历史证据，**merge 时不要载入量化 base，也不要把 `quantization_bit` 复制到导出配置**。
2. 新建独立、有版本名的 export YAML（不覆盖上述资产），建议输出根为 `D:/AI/runs/shared-ledger/t0-deploy-smoke/20261006-aonly-cp36/`：`model_name_or_path: D:/AI/models/Qwen3.5-4B`、`adapter_name_or_path: D:/AI/runs/shared-ledger/training_runs/qlora-v0.2-experiment-a-only/20261002-0859/checkpoints/checkpoint-36`、`template: qwen3_5_nothink`、`finetuning_type: lora`、`trust_remote_code: true`、`export_dir: D:/AI/runs/shared-ledger/t0-deploy-smoke/20261006-aonly-cp36/hf-merged`、`export_size: 5`、`export_device: cpu`、`export_legacy_format: false`。确认实际 base dtype 与所用 LLaMA-Factory/Transformers 配套后，才执行 `D:\AI\.venv\Scripts\llamafactory-cli.exe export D:/AI/runs/shared-ledger/t0-deploy-smoke/20261006-aonly-cp36/export.yaml`。LLaMA-Factory 官方的 merge 用法也是以 base + adapter + 对应训练 template 导出独立完整权重；merge 不对量化 base 做 LoRA 合并：<https://github.com/hiyouga/LLaMA-Factory/blob/main/examples/merge_lora/qwen3_lora_sft.yaml>。
3. 在已存在且版本已记录的 llama.cpp 工具目录运行其 `convert_hf_to_gguf.py D:/AI/runs/shared-ledger/t0-deploy-smoke/20261006-aonly-cp36/hf-merged --outfile D:/AI/runs/shared-ledger/t0-deploy-smoke/20261006-aonly-cp36/shared-ledger-4b-f16.gguf --outtype f16`；如果转换成功，再用同一版本 `llama-quantize <f16.gguf> D:/AI/runs/shared-ledger/t0-deploy-smoke/20261006-aonly-cp36/shared-ledger-4b-Q4_K_M.gguf Q4_K_M`。当前未在授权盘点范围内确认本机 llama.cpp checkout/CLI 路径与版本，也未证明该版本能正确转换当前 Qwen3.5-4B hybrid 架构，所以这是后续命令模板，不是已具备本机可直接运行的命令。llama.cpp 官方要求从 HF 转为 GGUF，并建议对照原模型验证 logits/转换结果，再检查量化影响：<https://github.com/ggml-org/llama.cpp/blob/master/docs/models.md>、<https://github.com/ggml-org/llama.cpp/blob/master/examples/model-conversion/README.md>。如模型工具链需要 projector/mmproj，应一起导出、转换并验证；只测 text endpoint 不覆盖图像路径。
4. 将该输出目录中的 **4B adapter merge 结果** 单独导入 LM Studio，记录实际模型 ID/文件 hash/量化/上下文；先以同一固定无业务数据 prompt 对照 HF merged、F16 GGUF、Q4_K_M GGUF 的基本生成/加载。链路至少保存 merge/convert/quantize stdout 与退出码、新产物清单/hash、GGUF metadata、HF merged 与转换结果对照、LM Studio 实际模型 ID/加载结果、host synthetic chat 请求与响应状态。以上只证明 adapter→部署格式链路可跑，不证明新版语义质量或 CAP 通过。官方模型转换手册建议用原模型与 GGUF 的 logits 对照，并分别检查量化模型：<https://github.com/ggml-org/llama.cpp/blob/master/examples/model-conversion/README.md>。

风险/未知：当前选用的 llama.cpp 版本及其 Qwen3.5-4B 转换正确性尚未知。上游公开 issue 曾报告 Qwen3.5 4B 转换后 block 元数据/加载不一致，issue 已标 stale 并 closed as not planned；这不是当前 master 必然失败的证据，但说明不能仅以“导出命令退出码 0”判定结果可信：<https://github.com/ggml-org/llama.cpp/issues/24737>。必须记录精确 converter commit、加载日志、metadata、对照结果；遇到架构不支持时先冻结报告/转换方案，不能临时下载/更新工具或长期训练来掩盖。

### 待取得的验证证据

| 验收点 | 需要保存的证据 | 不代表什么 |
|---|---|---|
| Adapter 与 base 匹配 | manifest、`adapter_config`、base `config.json` 与各自版本/hash 关联；导出日志 | 配置中的本地路径相同不等于权重文件同快照 |
| Merge 正确 | merge exit status/log；新目录独立；合并前后文件清单/hash；HF base+adapter 与 merged 最小推理对照 | adapter 文件存在或 merged 文件变大不单独证明 adapter 生效 |
| HF→GGUF 转换 | llama.cpp commit、完整命令、模型架构/metadata、转换日志；原 HF merged 与 F16 GGUF logits 或固定输入对照 | 转换脚本返回 success 不证明张量语义一致 |
| 量化影响 | Q4_K_M 模型实际加载日志/文件 ID；与 F16 的受控对照；所需 projector 一并检查 | 既有 9B Q4_K_M 不证明 4B 转换链 |
| LM Studio 运行 | 实际 4B 导入/加载、短上下文配置、host API 的 synthetic chat 返回 | 9B catalog/host chat/Docker chat 均不是 4B adapter 验证 |

T0 状态：三条指定外部 run 的关联、代表 checkpoint、报告和小文件 hash 已盘点；4B adapter → HF merge → GGUF → LM Studio 已明确最小待执行路径，但 adapter 对应权重快照、合并、转换及加载均未核验。主线已完成 9B 原生 host/Docker synthetic chat；它关闭该 9B runtime smoke，不替代 4B adapter 链。新版语义、Teacher completion 与 Student 推理均未在本轮执行。
