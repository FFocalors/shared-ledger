# P0 Gold Sample Dataset v0.1

本目录是 P0 Gold Seed v0.1 的冻结数据集。权威 Canonical Scenario 仍分别保存在同级 `p0a/scenarios.json` 与 `p0b/scenarios.json`；本目录的 `scenarios.json` 是供统一离线 Validator/Manifest 使用的合并索引，Scenario 对象与两份权威文件一致。95 条 Sample 的 `expected.model_output`、`expected_diff`、业务执行策略、证据 ID 均绑定其 `scenario_id`，Canonical Scenario 是唯一 Ground Truth。

## Scenario 治理

依据 [P0_FINAL_REVIEW.md §7](../P0_FINAL_REVIEW.md)，除 FIN-002 外的 53 条 Scenario 已登记为 `trust.level=GOLD`、`business_validated=true`、`lifecycle.status=reviewed`。`scenario_gs_p0b_015`（FIN-002）仍为 `SYNTHETIC_UNVERIFIED / false / draft / unassigned`，没有 Sample，不导出、不训练。它保留缺少真实 Gateway 绑定建议时必须澄清的安全分支；Gateway 落地后另增真实 suggestion 支持的 proposal 分支，不覆盖此场景。

95 条 Sample 均为 `trust.level=GOLD`、`ground_truth_locked=true`、`surface_form_reviewed=true`、`lifecycle_status=approved`。审核依据为 [P0_GOLD_SAMPLE_REVIEW.md §7](../P0_GOLD_SAMPLE_REVIEW.md)，终审裁决为 `READY_FOR_P0_GOLD_SEED_FREEZE`；用户接受该独立审核结论并授权冻结。源报告未记录个人审核者身份，因此不虚构姓名，记录审核日期 2026-09-29、报告引用与身份缺失说明。FIN-002 不计入 95 条。

## Matrix quota 对账

Coverage Matrix P0 的总配额为 **54 Family / 96 Samples**。FIN-002 的 1 条配额因无服务端 suggestion 而排除；最终 **53 Family / 95 Samples**。12 个 Family 配额为 1，42 个 Family 配额为 2；无自行调配。

| P0 Family | Matrix 配额 | 本批 Samples | 对账 |
|---|---:|---:|---|
| `ACT-002` | 1 | 1 | 精确符合 Matrix |
| `CLR-001` | 2 | 2 | 精确符合 Matrix |
| `CLR-002` | 2 | 2 | 精确符合 Matrix |
| `CLR-005` | 2 | 2 | 精确符合 Matrix |
| `CONV-001` | 2 | 2 | 精确符合 Matrix |
| `CONV-004` | 2 | 2 | 精确符合 Matrix |
| `CONV-006` | 2 | 2 | 精确符合 Matrix |
| `CONV-007` | 2 | 2 | 精确符合 Matrix |
| `DEBT-001` | 2 | 2 | 精确符合 Matrix |
| `DEBT-002` | 2 | 2 | 精确符合 Matrix |
| `DEBT-004` | 2 | 2 | 精确符合 Matrix |
| `DEL-001` | 1 | 1 | 精确符合 Matrix |
| `DEL-002` | 1 | 1 | 精确符合 Matrix |
| `ENT-001` | 2 | 2 | 精确符合 Matrix |
| `ENT-002` | 2 | 2 | 精确符合 Matrix |
| `ENT-003` | 2 | 2 | 精确符合 Matrix |
| `EXP-CLARIFY-001` | 2 | 2 | 精确符合 Matrix |
| `EXP-CLARIFY-002` | 2 | 2 | 精确符合 Matrix |
| `EXP-CLARIFY-003` | 2 | 2 | 精确符合 Matrix |
| `EXP-CLARIFY-007` | 2 | 2 | 精确符合 Matrix |
| `EXP-CREATE-001` | 2 | 2 | 精确符合 Matrix |
| `EXP-CREATE-002` | 2 | 2 | 精确符合 Matrix |
| `EXP-CREATE-005` | 2 | 2 | 精确符合 Matrix |
| `EXP-EDIT-001` | 2 | 2 | 精确符合 Matrix |
| `EXP-EDIT-003` | 2 | 2 | 精确符合 Matrix |
| `EXP-EDIT-004` | 2 | 2 | 精确符合 Matrix |
| `EXP-READ-001` | 2 | 2 | 精确符合 Matrix |
| `EXP-READ-002` | 2 | 2 | 精确符合 Matrix |
| `EXP-READ-003` | 2 | 2 | 精确符合 Matrix |
| `FIN-001` | 1 | 1 | 精确符合 Matrix |
| `FIN-002` | 1 | 0 | 排除：无真实 Gateway suggestion |
| `ICTX-001` | 2 | 2 | 精确符合 Matrix |
| `ICTX-002` | 2 | 2 | 精确符合 Matrix |
| `ICTX-003` | 2 | 2 | 精确符合 Matrix |
| `ICTX-006` | 2 | 2 | 精确符合 Matrix |
| `ICTX-008` | 2 | 2 | 精确符合 Matrix |
| `PRE-CORE-003` | 2 | 2 | 精确符合 Matrix |
| `PRE-GATED-001` | 1 | 1 | 精确符合 Matrix |
| `PRE-GATED-004` | 1 | 1 | 精确符合 Matrix |
| `REF-001` | 1 | 1 | 精确符合 Matrix |
| `REF-002` | 1 | 1 | 精确符合 Matrix |
| `RULE-001` | 2 | 2 | 精确符合 Matrix |
| `RULE-003` | 2 | 2 | 精确符合 Matrix |
| `RULE-004` | 2 | 2 | 精确符合 Matrix |
| `RULE-005` | 2 | 2 | 精确符合 Matrix |
| `RULE-006` | 2 | 2 | 精确符合 Matrix |
| `RULE-007` | 2 | 2 | 精确符合 Matrix |
| `RULE-008` | 2 | 2 | 精确符合 Matrix |
| `TRF-002` | 1 | 1 | 精确符合 Matrix |
| `TRF-007` | 1 | 1 | 精确符合 Matrix |
| `UI-001` | 2 | 2 | 精确符合 Matrix |
| `UI-002` | 2 | 2 | 精确符合 Matrix |
| `UI-003` | 1 | 1 | 精确符合 Matrix |
| `UNS-001` | 2 | 2 | 精确符合 Matrix |

## Sample 约定与覆盖

- Surface Form 由人工编写；`source.surface_form_type=human_authored`，`generator=null`，`teacher=null`。第二表达改写句式、指代/省略、口语、ASR 或多轮续接，保持 Scenario 业务参数与输出不变；非批量替换姓名或数字。
- 每条 Sample 绑定 `scenario_id`、`scenario_family_id` 和同一 `split_group_id`。95 条均 `split=unassigned`；其中 pending policy 的两条也保持 unassigned。
- Model Output 完整复制 Canonical Scenario Ground Truth；D4 `expected_diff` 与 proposal diff 深度一致。Tool/verified result ID 只来自 Scenario state/result，Proposal、Evidence、澄清候选可追溯到 Scenario。
- Context Envelope 按冻结 Schema 完整填写。平台 fixture 字段（request/screen/conversation ID、Android sample app 版本、发送/生成时间）是合成测试元数据；不表示生产流量或新增服务端业务事实。Scenario 未记录的账务工具结果不会被补造；`verified_result_ids` 仅复用已记录 ID。
- 不跨 Family 或 split 复制语义组；Validator 的 exact duplicate、normalized duplicate、semantic-group 与 split leakage 检查全部通过，无 duplicate/near-duplicate warnings。
- 实际输出类型：proposal 23、clarification 30、tool_call 12、answer 28、unsupported 2。P0 Canonical Scope 没有 `error` 类型目标；为覆盖它而改写 GT 会违反冻结 Scenario。
- Context 覆盖：10 条 Sample 携带 Scenario 已记录的对话历史；8 条含实际 recent action 状态；50 条使用具体 UI page context（其余为 home/normal activity）；表面表达包含 2 条 ASR-like、32 条 colloquial，其余为 neutral。UI、Interaction、Conversation 同时在 Expected Output 和 Scenario State 之间保持一致。

## 已知复审 MINOR 的处理

M-1 的 2 个 `recorded_facts` 粒度项仍能从其自身用户原话或 verified read 字段直接追溯；Sample 不改写或补造这些值。M-2 的 Envelope 必需字段由 Sample Context 按 schema 完整提供，fixture 元数据与业务/服务端事实分开。M-3 是终审确认过的 9 条通用安全断言骨架；本批没有复用 Scenario Assertion，也没有据此改变任何业务输出。三个 finding 均为终审接受的 MINOR，无未解决 BLOCKER/MAJOR。

## Validation

运行 `python scripts/ai_dataset_validator/cli.py validate dataset docs/ai/dataset/gold_seed/v0.1/p0`：**54 scenarios / 95 samples / 54 families；0 errors / 0 warnings**。Manifest 版本为 Business Logic 1.2 / AI Contract 0.1.2 / AI Scope 0.1 / Dataset 0.1；样本数量与 Matrix 的可生产 P0 配额严格一致。Validator 单测 46/46 通过，Examples 0 errors（三条既有 duplicate/semantic review warnings）。Samples 已按 Schema 治理为 `approved` 并纳入冻结 Manifest；这不授权 Teacher 生成或训练。


## v0.1 冻结记录

- 冻结状态：`P0_GOLD_SEED_V0_1_FROZEN`；日期：2026-09-29。Dataset / Business Logic / AI Contract / AI Scope 版本分别为 `0.1 / 1.2 / 0.1.2 / 0.1`，基线 SHA-1 为 `55fb28a7c0660462e5842e2eb5c71cfa763e5801`。
- 95 条 Sample 的治理状态为 `approved`（`GOLD` 且已人工审阅 Surface Form）；Manifest lifecycle statistics 为 95 approved。Scenario 仍是 54 条索引，其中 53 条已审阅 GOLD，FIN-002 维持 `SYNTHETIC_UNVERIFIED / draft / unassigned`，无 Sample，排除导出与训练。
- 审核依据：[P0_GOLD_SAMPLE_REVIEW.md](../P0_GOLD_SAMPLE_REVIEW.md)，结论 `READY_FOR_P0_GOLD_SEED_FREEZE`。报告未记名审核者，故审计字段明确注明身份未记录；冻结/审核日期为 2026-09-29。
- Manifest SHA-256：`scenarios.json` = `b4ba7f406f017cd28c7c6885827717ae246b8f4dfb794a76fe00db5f9db59815`；`samples.json` = `34ffd94d9c5ccbb17e6632b8689194c4be53f7275db828e983f6d6540b406dee`。Manifest 不对自身计算哈希。
- Teacher 不得反向修改此冻结 Dataset 中的 Surface Form、Context、Tool Path、Ground Truth、Scenario 绑定或治理记录。任何修订或扩充都必须进入新的 Dataset version，更新 Manifest/哈希并重新审核；本次不启动 Teacher Generation、API、训练或导出。
