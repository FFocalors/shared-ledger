# Shared Ledger Dataset v0.1 Validation Rules

> 状态：**FROZEN FOR GOLD SEED DESIGN**。本文件定义 Canonical Dataset 的离线验收门槛；JSON Schema 只负责单记录结构，跨文件、Contract、Scope、业务结果与泄漏检查由确定性 Validator 负责。

## 1. 校验输入与执行顺序

Validator 必须离线加载以下固定输入，不访问 `shared-ledger.invalid`：

1. [Scenario Schema](schema/scenario.schema.json)、[Sample Schema](schema/sample.schema.json)、[Manifest Schema](schema/dataset_manifest.schema.json)；
2. [Intent Catalog](../schema/intent_catalog.json)、[Tool Catalog](../schema/tool_catalog.json)；
3. [Context Envelope](../schema/context_envelope.schema.json)、[Model Output](../schema/model_output.schema.json)；
4. [AI Scope Freeze v0.1](../AI_SCOPE_FREEZE_V0.1.md) 与 BUSINESS LOGIC FREEZE `55fb28a7c0660462e5842e2eb5c71cfa763e5801`。

执行顺序固定为 Schema → 引用/版本 → Contract → Scope/执行 → Ground Truth → Policy → Leakage/去重 → Privacy → Manifest。任一 `ERROR` 使记录不能进入 `approved` 或正式导出；`WARNING` 需要审核结论但不自动改变 Ground Truth。

## 2. Schema Validation

- 三份 Schema 自身必须通过 JSON Schema Draft 2020-12 meta-schema。
- 校验器必须启用 `format`，特别是 UUID、date-time。
- Scenario、Sample、Manifest 必须拒绝未知顶层字段。
- `input` 必须直接通过 Context Envelope；`expected.model_output` 与 `ground_truth.model_output` 必须直接通过 Model Output Schema，包括 Tool 分支参数。
- `expected.output_type` 必须等于 `expected.model_output.type`；Scenario 同理。
- `surface_form.user_message` 必须逐字等于 `input.user_message`；`context_turn_count` 必须等于 `surface_form.conversation` 长度，并与 Context Envelope 中用于该轮的历史一致。

## 3. Version and Reference Validation

- Dataset v0.1 只接受：Business Logic `1.2`、AI Contract `0.1.2`、AI Scope `0.1`、Dataset `0.1`。
- `frozen_reference_sha` 必须为 `55fb28a7c0660462e5842e2eb5c71cfa763e5801`。
- 每个 Sample 的 `scenario_id` 必须存在；family、split group 和版本必须与其 Scenario 一致。
- `ground_truth_pointer` 必须准确指向关联 Scenario 的 `/ground_truth`。
- `deprecated_by_version` 非空时，记录不得继续作为当前版本 `approved` 数据。

## 4. Contract Validation

- `intent_ids` 必须存在于 Intent Catalog；`tool_ids` 必须存在于 Tool Catalog。
- `tool_call.intent_id/tool/arguments` 与 `proposal.intent_id/operation.tool/arguments` 必须匹配 Model Output 的封闭联合分支。
- Scenario/Sample 声明的 Tool 必须在该 Intent 的 `possible_tools`（PRIMARY）或 `supporting_lookup_tools`（SUPPORTING_LOOKUP）中；辅助映射只从 Intent Catalog 派生，不在 Tool Catalog 重复维护。纯 `answer`、`clarification`、`unsupported`、`error` 允许没有实际 Tool 或 proposal。
- `server_context.enabled_tools` 只能包含 Catalog 中存在且本轮 Scope 允许暴露的 Tool；DEFERRED、D4 禁用写 Tool 不得注入。
- 动态账务 `answer` 的 `evidence_result_ids` 必须出现在输入的 `server_context.verified_result_ids`；规则问答也必须绑定冻结规则证据。
- Dataset 不创造 `native_flow_required` 输出类型；原生引导使用 `unsupported.suggested_action` 或说明性 `answer`。

### 4.1 Supporting Lookup Rule

- `possible_tools` 表示 PRIMARY；`supporting_lookup_tools` 表示 SUPPORTING_LOOKUP。模型输出仍只使用 `tool_call`，角色由 Intent 与 Catalog 映射确定，不添加顶层类型或冗余 Dataset `tool_role` 字段。
- Supporting Lookup 必须对应当前 Intent 的明确映射，Tool `mode=read` 且 `confirmation_level=0`；不允许从任意只读 Tool 推导授权。
- Supporting Lookup 保持原业务 Intent；读取候选后可继续为同一 Intent 输出 `clarification`、PRIMARY Tool 或其他契约允许结果。多候选必须澄清，唯一候选仅在证据充分时继续。
- Supporting Lookup 不得改变账务事实、输出成功写入标签或绕过 L1/L2 proposal；D4 写入仍不可执行。

### 4.2 Proposal Validation

- `type=proposal` 时必须存在完整 `operation`、`preview`、`confirmation` 与 `execution_policy`，且不得带 tool_call 的顶层 `tool/arguments`。
- `preview.kind` 只能为 create/update/delete/financial；每个 diff item 必须有 field，并至少有 before/after/added/removed 之一。创建不要求 before。
- Dataset `expected_diff` 必须与 `proposal.preview.diff` 深度相等；Scenario 的 operation、Sample scope 和 proposal 的 Intent/Tool/参数不得冲突。
- `confirmation.level` 必须等于 Catalog/Scope 的实际等级，并等于 Dataset `execution.confirmation_level`；`confirmation.required` 必须为 true，并等于 Dataset `confirmation_required`。
- `execution_policy.execution_allowed` 必须等于 Dataset execution 标记。值为 true 只表示可信确认后可推进，不表示已授权或已执行。
- DEFERRED Intent 不得输出 proposal；至少必须拒绝任何 DEFERRED executable proposal。D4 只允许 reason 为 `d4_atomic_update_not_supported` 的不可执行 proposal。
- Proposal 的 summary、对话目标和相邻 answer 不得声称“操作已经完成”“资金已经转移”“数据已经修改”或等价成功语义。此项是 **semantic validator rule**，不能只依赖 JSON Schema。

## 5. Scope Validation

- Scenario/Sample 的 `ai_scope` 必须与其主要 Intent 的 `ai_scope_v0_1` 一致；多 Intent 记录必须列出全部 Scope，并由 Validator 拒绝会降低最高风险的声明。
- CORE 可产生读 Tool、允许的 L1 写提案、clarification、answer、unsupported/error。
- SUPPORTED_BUT_GATED 可产生读 Tool或待确认写提案；写入的确认属性必须正确。
- DEFERRED 只允许 `answer` 或 `unsupported`，不得有执行性 `tool_call`，`execution_allowed` 和 `successful_execution_label_allowed` 必须为 false。
- Scope 百分比约 80/16/4 是 Planning 目标，不是单批 Schema 硬错误；Manifest 产生偏差报告。

## 6. Confirmation Validation

- 只读 L0：`confirmation_required=false`、`final_authorization=not_applicable`。
- 实际允许推进的 L1/L2 写提案：`confirmation_required=true`、`final_authorization=trusted_ui_event_required`。
- Level 2 适用于 Transfer、Prepayment、Return、Refund、Final Settlement、delete、void 等 GATED 高风险操作。
- Dataset `confirmation_required` 与 proposal 的 `confirmation.required` 必须一致；最终可信 confirmation event 不得被塞入 Model Output。
- 对话中的“确定”“可以”“执行吧”不能将 `final_authorization` 改成已授权，也不能形成 successful execution label。可信 UI confirmation event 不作为自然语言模型输出。
- DEFERRED 不创建 proposal。D4 创建 `confirmation.required=true` 的 preview-only proposal，但 `execution_allowed=false`；即使产生点击事件也不能转换为 tool_call。

## 7. Ground Truth Validation

- Teacher Model 只能生成或改写 `surface_form`；不得更改 Scenario/family ID、state、operation、Ground Truth、Intent、Tool、Scope、确认等级、执行许可、金额、方向、Participant 身份、财务结果、业务规则结果或 split。
- `surface_form_type=teacher_generated` 时必须有完整 `source.teacher` provenance；其他来源必须为 null。Validator 校验 provider、model、generation_run_id、prompt_version、generated_at、temperature 和 nullable seed，并将 Teacher 与锁定 Ground Truth 的任何冲突标为 rejected。
- GOLD 必须有冻结规则、正式 RPC/pgTAP/Android 测试或人工确定性审核证据。SILVER 必须经过程序校验或可复放的 MASS/Teacher 生成链。`SYNTHETIC_UNVERIFIED` 只能处于 `unassigned`，生命周期只能是 draft/generated/rejected。
- 能由正式 RPC、fixture、pgTAP 或确定性计算器验证的金额、方向、权限、锁、版本和结果必须执行该验证；Judge/Teacher 的 PASS 不能单独升级 Ground Truth。
- MASS500/MASS2000 的 Compiler 漂移、focus miss、Final plan 弱化与历史 Judge 分歧必须在导入前清洗；保留原 case ID 与验证证据。
- 模型不得自行计算 Debt、AA 尾差、FX、Refund 额度、Prepayment Usage、Final plan 或 completed。

## 8. Clarification Validation

- `output_type=clarification` 时必须有 `clarification_annotation`。
- Annotation 的 reason、missing_fields、question 必须与 Model Output 完全一致。
- Candidate ID 必须来自 Context/服务端候选；不可访问对象不能作为候选。
- 同名或多候选无法唯一确定时，`entity_resolution.expected_entity_id=null` 且 `resolution_status=clarification_required`。
- payer、参与人、split method、manual amount、Transfer 双方/金额、Prepayment owner/custodian、Refund 收款/受益、Final 实际付款不明确时，不得通过默认值补齐。

## 9. Entity Resolution Validation

- 每条 mention 必须列出 `candidate_ids`、`resolution_status`、证据来源。
- `resolved` 必须有非空 `expected_entity_id`，且该 ID 必须属于候选并与当前 Activity 一致。
- selected_entity、draft、recent_action、confirmed_binding 只能作为线索；Gateway 仍需校验对象归属和可见性。
- “我”必须能映射到当前 Activity 已认领 Participant；User ID 不能替代 Participant ID。
- 换 Activity、stale screen、unknown write state 或跨活动指代必须澄清或读取最新状态。

## 10. Policy Validation

- `pending`、`excluded_pending_policy` 的 Scenario/Sample 必须保持 `split=unassigned`，且 execution/success label 均为 false。
- 当前本位币预填和当前时间预填是 `excluded_pending_policy`；不得生成模型已获准采用默认值的正式 Gold 样本。
- `deprecated` 样本不得被正式 Exporter 选取。
- Exporter 只接受 `policy_status=active`、`lifecycle_status=approved`、`example_only=false` 的记录。

## 11. D4 Execution Validation

- Intent 为 `update_expense` 或 `update_refund` 时，必须有 `expected_diff`。
- Model Output 必须为 proposal；`execution_policy.reason=d4_atomic_update_not_supported`，proposal 与 Dataset 的 `execution_allowed=false`，`successful_execution_label_allowed=false`；`server_context.enabled_tools` 不得含 `update_expense`。
- `expected_diff` 必须与 `proposal.preview.diff` 深度相等，confirmation level 必须保持 update_expense=L1、update_refund=L2。
- 不得出现“已更新”“执行成功”或 successful execution receipt 的 Gold Label。
- D4 proposal 允许作为结构化训练目标，但 Exporter 和 Gateway 必须保留不可执行标记；不能降级为 answer，也不能提升为写 tool_call。

## 12. Leakage Validation

- Split 的分配单位是 `scenario_family_id`；`split_group_id` 是稳定的物理执行键。
- 同一 family 或 split group 在所有 Scenario、Sample 中只能有一个 split，包括 train/validation/test/hard_test/unassigned。
- 切分顺序固定为：建立并去重 Scenario → 聚合 Scenario Family → 锁定 split group → 分配 split → 在该 split 内生成 Surface Form。
- 禁止先生成全部语言样本再随机 80/10/10。
- 推荐规划比例是 family 级 70/10/15/5；v0.1 Schema 阶段所有示例保持 unassigned。
- 相同 Activity/对话链、相同业务状态变体、同一句在不同页面的对照样本必须由策划明确决定是否归入同一 family；本期同句不同页面对照放在同一 family，防止跨 split 泄漏。

## 13. Deduplication Validation

- Scenario `canonical_facts_sha256` 对归一后的 state、operation、Ground Truth 业务事实计算；忽略标题、自然语言和随机 UUID 的表示差异。
- `dedup_key` 用于完全业务重复；`normalization_key` 用于大小写、数字写法、标点和空白归一后的 Surface Form 重复。
- `semantic_group_key` 聚合语义近重复，如“三百/300”“我付/我出的”。它至少用于报告与人工复核，不要求 v0.1 实现 embedding。
- 完全重复为 ERROR；同 family 的近重复为 WARNING；跨 split 的近重复为 ERROR。

## 14. Lifecycle Validation

允许状态：draft → generated → validated → reviewed → approved。任意状态可转 rejected；approved 可在新版本转 deprecated。不能从 generated 直接进入 approved；SYNTHETIC_UNVERIFIED 不能进入 validated/reviewed/approved。状态变化必须保留审核人/工具、时间和证据，实际流水线字段可在后续 Planning 中外置为审计日志。

## 15. Privacy Validation

- Scenario state 和 Sample input 只能使用虚构实体。Context Envelope 要求 UUID，因此模型输入使用确定性合成 UUID；`U001/P001/A001/E001` 等仅作 Dataset alias。
- `contains_production_data=false`、`contains_real_personal_data=false` 是正式训练入口硬条件。
- 不允许真实姓名、手机号、邮箱、Auth token、Storage URL、生产 Activity/Expense/Transfer ID 或完整真实聊天。
- Teacher 输入只获得完成该 Scenario 所需的最小状态，不能获得整库导出。

## 16. Manifest Validation

- Manifest 的 scenario/sample/family 数量必须与实际记录一致。
- split/task/scope/source/trust/difficulty/lifecycle 统计必须从记录重新计算并逐项相等。
- target percentages 必须合计 100；`assignment_unit` 必须为 `scenario_family`。
- artifact path 必须存在；正式冻结 Manifest 的 SHA-256 必须与文件内容一致。
- 任一验证错误必须反映在 `validation_summary.error_count`；已解决的 Contract blocker 不再计 warning。

## 17. Required Negative Tests

每次修改 Schema 或 Validator 至少验证以下非法数据会被拒绝：

1. DEFERRED Sample 输出可执行 tool_call 或 executable proposal；
2. malformed proposal（缺 operation/preview/diff、Intent/Tool 分支不匹配或多余字段）；
3. L2 proposal 的 confirmation_required=false 或 level≠2；
4. D4 proposal 标记 execution_allowed=true、reason 错误或 diff 注解不一致；
5. pending policy 被放入 train；
6. SYNTHETIC_UNVERIFIED 被标为 approved；
7. teacher_generated 缺 provenance 或 Teacher 改写 Ground Truth；
8. 同一 scenario_family_id 跨 split；
9. 不存在的 Intent/Tool；
10. Surface Form 与 ContextEnvelope user_message 不一致；
11. Model Output 类型或 Tool 参数不符合 Contract；
12. Manifest 统计与实际记录不一致。

## 18. Validation Result Semantics

只有以下全部成立时才可声明 Dataset `validated`：Schema、Contract、Scope、Confirmation、Ground Truth、Policy、Leakage、Privacy、Manifest 均通过。`approved` 还需要人工业务审核或被认可的确定性来源。Schema 校验通过不代表资金业务正确，也不代表 Gateway 已实现。

