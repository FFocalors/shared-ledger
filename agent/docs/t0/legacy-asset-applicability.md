# 旧训练资产与标签适用性审核

审核日期：2026-10-08。范围仅为只读静态核查旧训练资产、标签与失败轨迹，不涉及 Teacher、训练、模型推理、真实账本或云端请求，不读取权重；原始冻结资产未修改，未提交。

## 结论

旧数据可供新 T0 参考任务、覆盖缺口和失败类型，但不能把旧标签或模型输出直接当作新版训练正例。按唯一 `sample_id` 去重核查 266 行：`可复用` 0、`需重标` 187、`证据不足待核` 73、`不适用` 6。此为适用性审核结果，不是新版数据集冻结、train/validation/sealed 切分或训练准备完成的声明。行级标签、理由码、来源版本/行 SHA、轨迹、预期与实际类别及规则锚点均在 [`legacy-applicability-manifest.json`](assets/legacy-applicability-manifest.json)；每行 `positive_training_eligible=false`，73 条证据不足行均带明确 `next_action`，不能以教师文本补证。root 已复核批准此处置边界：0 行直接复用，187 行只作待重标素材，73 行不准入正例，6 行排除，所有旧模型输出隔离。

新版业务依据是用户当前决策和 Agent 指南 v0.4.2：普通活动无预存；大型子活动的 Expense payer 与每个 Split bearer 各自必须在该子活动持久化的 Participant ID scope 内、二者可不同；此限制仅适用于 Expense，不套到 CAP13 的 Activity 级预存 Owner/Custodian。历史未保存 scope 的子活动保持 legacy-unscoped，不补造选择。AA 尾差、币种/精度与 FX、历史转账或退款来源造成的财务锁、Expense presentation、普通 Final 均按当前后端；普通 Final 不支持预存返还，只有大型活动有该路径。D4 的全局禁用是历史策略：未锁 Expense 可按预览和用户确认提出修改，执行前重核权限和版本；不能跨越后端锁。CAP07/08/12/13/15 及指南 `#coverage`、`#sources` 为业务锚点。

## 资产版本、来源与覆盖

审核来源为三条指定 run：`D:/AI/runs/shared-ledger/training_runs/qlora-v0.1/20260930-143013`、`D:/AI/runs/shared-ledger/training_runs/qlora-v0.2-experiment-a-only/20261002-0859`、`D:/AI/runs/shared-ledger/training_runs/qlora-v0.2-experiment-c-only/20261003-134314`。先按各自小型 manifest、PREREGISTRATION、final_manifest、final_artifact_hashes/source_hashes 报告追溯冻结源与 schema；未检索整个 `D:/AI`，未读权重。逐份源文件 SHA、行 SHA、轨迹报告 SHA 和来源提交在 manifest 的 `archive_indexes`；原报告、脚本与静态证据归档于 `D:/AI/runs/shared-ledger/t0-deploy-smoke/20261007-200705-step3-merge/legacy-review/`。

| 来源 | 冻结语义版本及行数 | 源文件 SHA-256（关键入口） |
|---|---|---|
| v0.1 canonical | dataset `0.1` frozen；business logic `1.2`、AI contract `0.1.2`、AI scope `0.1`；250 行 | commit `0405f1d80e7ef1a94a401349010561528593fded`；`dataset_manifest.json` `7f8cc2ef70d1abedd49ea040826d93f4c3708a8cb5893e7e1fedcc488e2c2252`；`samples.json` `768916c8781dc2608ac8220588a0e85ffc043d8f16a45e9bd3497b87a214e562` |
| v0.1 training setup | 来源 commit `b302ff0498e6dd937a403a3dea0473d1b7eb3de5`；244 个 active 导出行 | `traceability.json` `ad8fd7ba663216c8c185307945bc5507809895f4856c7739603213bf261c42ba`；其余 train/validation/test/hard-test 和 manifest 的逐文件 SHA 见 manifest |
| v0.2 A-only canonical path | `dataset_version=0.1`、contract `0.1.2`、scope `0.1`、status `validated`；266 行，不是新冻结版本 | commit `7f0aea8`；`dataset_manifest.json` `1aec43b9fa72f028326833ad317031e87bf19f9d92dacd8dcde2b2d8a4e3dabc`；`samples.json` `12529f50accd452bad5153dbe36efa123e468408259ad3263adf8a457a1afe13` |
| v0.2 A-only training setup | 211 个导出行（187 train、24 validation） | commit `7f0aea8`；`traceability.json` 本地 SHA `8ed9421bc7dec11850cdfc11d52a368a46995c1f3aa20dc594bd04e8037708e0`；冻结报告没有给此文件独立 run-report SHA 供交叉比对 |
| v0.2 C-only setup | 复用 v0.1 数据设置；训练导出 244 行 | commit `bffb05f`；`manifest.json` `57b2200f337ee86b36493dd29ffb18c74429bfec3258f99bea3c3186a40514d9`；`traceability.json` 与 v0.1 相同 SHA |
| v0.1.2 旧 schema | 输出 schema、tool catalog、intent catalog、context envelope | 来源 commit `0405f1d80e7ef1a94a401349010561528593fded`；SHA 分别 `5ad944f7e1163c5b186cd4b9aea4b3ddf8c39910b9cbaf63554a7718af689bd9`、`e6f25251c6bdef6cd50f0ce01489adf9c0e6bb5efade5f789e847d86a7350744`、`5170f625130d706a4db95fa5e67ab8cc11c1d56aafc0c093692f9421d4d2e651`、`5caed757f06b2edfb6b7499d5bff5bfa68225a3416ac5627290664832b9c4a9e` |

去重核查覆盖 v0.1 250 行与 A-only 266 行，共 516 个版本记录；250 个重叠 ID 的行内容全部相同，合并后 266 个唯一 ID，A-only 增加 16 行。v0.1/C-only 导出拆分为 171 train、24 validation、37 test、12 hard_test；A-only 实际训练导出为 187 train、24 validation。来源 hash 与已有 run-report hash 的可比项目均匹配；唯一例外是 A-only setup `traceability.json` 没有报告侧哈希，文件本身已计算并列明，故不宣称它有独立报告对照。

独立核对了六类旧协议、三档旧 Scope 和当前规则的逐行映射。旧协议计数（v0.1 / A-only path）为 `answer` 77/78、`clarification` 75/82、`tool_call` 32/35、`proposal` 60/65、`unsupported` 6/6、`error` 0/0。映射到新版四类 `answer / clarify / read / propose` 时：answer 仍需逐条核验其证据引用；clarification 重编码为 clarify；旧 tool_call 只能按确定性权限映射为 read 或经确认的 propose；proposal 必须重建为可信 preview 和确认绑定的 propose；unsupported 改成 answer 或 clarify；旧 error 类没有样本可映射。六类每行均标为 `需重标` 协议维度，不能仅凭业务意图相似即复用。

旧 Scope 的 `CORE` 为 211/226，`SUPPORTED_BUT_GATED` 为 39/40，`DEFERRED` 为 0/0（v0.1 / A-only path）。这三个历史标签均不能直接等价于新版权限或执行范围；manifest 对每行独立保留旧 Scope、当前 Scope 适用性分类和理由。A-only 增加的 payer-bound/unbound、活动选择歧义、recent-action 成败对照、D4/展示修改和 gated delete 行也逐行纳入。`sample_v02_e_recent_failed` 是 clarify 候选，`sample_v02_e_recent_succeeded` 是 read 候选，二者仍需新协议重标；动作历史不能替代 UUID 绑定或用户确认。`sample_v02_f_verified_expense_answer` 因结果正文缺失而待核。

## 重点标签裁定

- **普通活动预存正例：** 三条 `create_prepayment` proposal（`sample_gs_p0_038`、`sample_teacher_598c007bc8b5`、`sample_teacher_75bf6ec27c31`）的输入/场景没有绑定普通还是大型 Activity。新版 CAP13 对普通 Activity 的 preview/create/return 均拒绝；预存只适用于大型 Activity。三行统一 `证据不足待核`，不得保留为普通预存正例，也不能把旧行改写成大型 Activity。若后续构建新的大型 Activity 预存样本，应从权威场景明确 Activity type，并按 CAP13 的 Activity 级 Owner/Custodian、币种和资金账户语义，具备当前服务器 preview 与确认流程；预存入口可在有效子活动间共用，不把它限定为子活动级写操作。旧三行仍待权威来源核对或隔离，不补造证据。
- **D4 全局禁用：** v0.1 有 20 行，A-only path 新增 1 行 `sample_v02_g_financial_d4`。旧 `d4_atomic_update_not_supported` 是历史否定策略，不代表当前业务永久禁写；按 CAP08 对锁定状态、展示字段与可修改财务字段分别重标。当前锁约束不变：真实 Transfer/source 或持久 refund-source history 锁住原 Expense；作废 Transfer 不解锁；展示字段走独立 RPC；没有可用的 Expense restore RPC，Transfer 不可编辑/恢复，只能在允许时 void。
- **answer 的证据：** v0.1 有 69/77 行、A-only path 有 70/78 行声明了 expected `evidence_result_ids`，但 model-visible `server_context.tool_results` 没有相应结果正文。去重后 70 行 `证据不足待核`；另外 8 个 answer 行仍需按当前事实和新版 answer schema 重标。缺结果正文时不凭教师文本补证据。
- **失败输出和错误轨迹：** 145 条模型轨迹全部设 `positive_training_example_allowed=false`，其中 65 条 schema 不合法、30 条人工事实复核为错误、7 条为部分正确、4 条为正确，104 条未复核；只有 66/145 与目标业务结构匹配。它们是诊断证据，不是修正后的目标。尤其观察与动作不相连、引用 ID 未经 Harness 可信绑定、没有用户确认、或错误响应未在轨迹中得到纠正的记录不能用作正例。

## checkpoint 与失败处置

| 历史运行 | 记录与结论 |
|---|---|
| v0.1 cp22 validation | 24 行；schema 12/24、结构匹配 11/24、关键事实 55/90、unsafe 12；旧 checkpoint_selection 按 flag 计数选 cp22（cp22 22 flags、cp33 23 flags），保留为历史选择 |
| v0.1 cp33 validation | 24 行；schema 13/24、结构匹配 11/24、关键事实 57/90、unsafe 11；后续按 unsafe row 数排序 cp33 胜于 cp22（11 对 12）。两次评选单位不同，不能把 cp33 后评改写成 cp22 当时未选 |
| A-only cp36 | 24 行；schema 16/24、结构匹配 13/24、关键事实 59/90；run 结论 `V0_2_EXPERIMENT_A_REGRESSION`；含 1 个直接写轨迹 |
| C-only cp33 | 24 行；schema 14/24、结构匹配 12/24、关键事实 61/90；run 结论 `REGRESSION`；read 工具名 6/6 命中但 payload malformed，proposal 0/3 正确 |

轨迹 manifest 覆盖 validation 96 条、test 37 条、hard_test 12 条，共 145 条；按 73 个 sample ID 去重用于统计。发现四条不可作正例的直接写轨迹：`sample_gs_p0_052` 和 `_053`（v0.1 cp22 test）把本应澄清展示更新的响应变成 `update_expense` 写工具调用；A-only cp36 的 `sample_gs_p0_037` 和 C-only cp33 的 `sample_teacher_4053b71f5faa` 把应提议的 `void_transfer` 直接变成写调用。后两条把不透明的 `result-p0a-transfer-011` 当 `transfer_id`，均无 confirmed binding/确认；源上下文有 result id，但 0 个 result body、0 个 confirmed binding、0 条 recent action。cp33 对 `sample_gs_p0_037` 的 unsupported 输出同样不能作为正例。失败处置是隔离旧输出，仅在之后具备纠正后的规范目标、UUID 与实际结果绑定、工具权限及可信确认来源时重新标注；本次没有生成或补写任何训练目标。

## 适用规则与边界

行级理由锚点使用指南 `#components`、`#protocol`、`#write-flow`、`#coverage`、`#sources`，并关联 CAP06/CAP08/CAP13；每行的具体锚点见 manifest。历史 scope 不能替代当前后端边界或 Harness 检查：模型只提出语义意图，Harness 负责可信 UUID 绑定、只调用固定 allowlist RPC、预览与用户确认、执行时重核权限和版本、稳定 execution key 与回执恢复。旧的确认文本、旧 tool 参数、模型生成的 ID 均不证明用户确认或服务端授权。

截至 2026-10-08 19:11（Asia/Shanghai）的 T0 状态快照：attempt3 HF merge PASS；F16/Q4 metadata/hash PASS；base+adapter D-only raw-copy checkpoint1219 builder PASS。HF base+adapter v3 的 capture 已完成，但 cached generation 出现乱码、算术 JSON 校验失败，不能记为模型 PASS；merged HF 同设置 capture/comparison 仍 pending。另一路已记录三项固定 Q4 CPU inference 通过，但这不证明 HF/GGUF logits 一致。对应记录位于 `D:/AI/runs/shared-ledger/t0-deploy-smoke/20261007-200705-step3-merge/logs/hf-base_adapter-accelerate-v3-attempt2.*` 与 `logs/hf-merged-accelerate-v3-attempt2.*`，Q4 结果见 `agent/docs/t0/runs/20261008-q4-cpu-inference.md`。本审核没有占 GPU 或重资源；报告完成的是旧资产适用性裁定，不代表 187 行已重标、缺失证据已找回或 T1 已完成，也不代表 T0/model PASS。
