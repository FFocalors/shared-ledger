# Shared Ledger Dataset Schema v0.1

> 状态：**FROZEN FOR GOLD SEED DESIGN**。本规范定义训练、验证和测试主数据的组织方式，不包含正式训练集、Teacher Prompt、最终 split、Exporter、QLoRA/SFT 或模型部署。
> 版本基线：BUSINESS LOGIC `1.2` / AI Contract `0.1.2` / AI Scope `0.1` / Dataset `0.1`；冻结参考 SHA `55fb28a7c0660462e5842e2eb5c71cfa763e5801`。

## 1. 目标与边界

Dataset v0.1 把确定性业务事实与自然语言表达分开，使 pgTAP、MASS、Android 测试、人工场景和未来 Teacher Model 都能落入相同主格式，并在导出到 LlamaFactory、ChatML 或 JSONL 前完成一致校验。

本阶段只新增 Scenario、Sample、Manifest Schema、验证规则和 20 个 `example_only` 记录。没有修改业务逻辑、AI Contract、AI Scope、Intent/Tool ID、RPC、Android 或数据库，也没有生成正式训练数据。

## 2. Canonical Data Flow

```text
冻结业务逻辑 / RPC / pgTAP / MASS / Android / 人工确定性场景
                              ↓
                    Business Scenario
                              ↓
             Scenario Family + split_group_id
                              ↓
             先分组、去重、再分配 Dataset Split
                              ↓
         人工或 Teacher 只生成/改写 Surface Form
                              ↓
                     Language Sample
                              ↓
        Schema + Contract + Scope + Policy + Leakage 校验
                              ↓
                    Canonical Dataset
                              ↓
             后续 Exporter → messages / ChatML / JSONL
```

Canonical Dataset 不与某个训练框架绑定。Exporter 只能转换已批准数据，不能补业务字段、改 Ground Truth 或重新随机切分。

## 3. Scenario 与 Sample 分离

Scenario 描述“业务世界中什么是真的”：最小状态、目标操作、冻结 Scope、标准输出和确定性业务结果。Sample 描述“用户怎样表达同一个问题”：页面、草稿、会话、最近操作、语言形式、任务标签和模型应返回的单个 JSON。

一个 Scenario 可以派生多个 Sample；多个状态近似 Scenario 可以属于同一 Scenario Family。三个标识职责如下：

| 字段 | 作用 |
| --- | --- |
| `scenario_id` | 一组确定状态、操作和 Ground Truth 的唯一版本 |
| `scenario_family_id` | 业务形状和泄漏边界；所有变体必须同 split |
| `sample_id` | 某个 Surface Form + ContextEnvelope + Expected Output |
| `split_group_id` | 实际切分键；v0.1 与 family 稳定绑定 |

## 4. 文件结构

```text
docs/ai/dataset/
├── DATASET_SCHEMA_V0.1.md
├── DATASET_VALIDATION_RULES.md
├── schema/
│   ├── scenario.schema.json
│   ├── sample.schema.json
│   └── dataset_manifest.schema.json
└── examples/
    ├── scenarios.json
    ├── samples.json
    └── dataset_manifest.json
```

没有新增 Evaluation Case Schema：Sample 已包含 split、difficulty、challenge tags、ContextEnvelope、Expected Output、实体解析和执行策略，能够直接表达训练或评测样本。另立格式会增加协议漂移风险。

## 5. Scenario Schema

[scenario.schema.json](schema/scenario.schema.json) 表示一条 Business Scenario。核心字段：

| 分组 | 字段 | 语义 |
| --- | --- | --- |
| 标识 | `scenario_id`, `scenario_family_id`, `split_group_id`, `scenario_version` | 版本化事实与 family 级泄漏边界 |
| 版本 | `versions` | Business Logic、Contract、Scope、Dataset、冻结 SHA |
| 来源 | `source`, `trust` | 原测试/规则引用、可信等级、验证方法和证据 |
| 覆盖 | `rule_tags`, `scope` | 业务标签、CORE/GATED/DEFERRED、关联 Intent/Tool |
| 状态 | `state` | 合成实体、最小业务事实、前置条件；不是数据库 dump |
| 操作 | `operation` | write/query/explain/clarify/unsupported/error/multi_step 与参数 |
| 真值 | `ground_truth` | 当前 Model Output、确定性结果、断言与执行政策 |
| 防泄漏 | `split`, `deduplication` | family split、规范事实 hash、业务去重键 |
| 治理 | `policy_status`, `privacy`, `lifecycle` | pending 政策、无生产数据、状态/废弃版本 |

Ground Truth 中的 `model_output` 直接引用当前 Model Output Schema。`expected_business_result` 保存模型不应自行计算、但评测或服务端可以校验的结果，例如原币金额、应返回的实体或是否仅生成 proposal。

## 6. Scenario Source 与 Trust

Scenario 来源枚举为：`business_logic`、`pgtap`、`mass500`、`mass2000`、`android_test`、`manual`、`synthetic`。Teacher 不创建或改写 Canonical Scenario；它的来源只记录在派生 Sample 的 `source.teacher`。来自现有测试的 Scenario 必须保存路径/用例名或原 case ID；MASS Judge PASS 本身不是业务真值。

可信等级：

| 等级 | 准入依据 | 正式训练资格 |
| --- | --- | --- |
| `GOLD` | 冻结规则、正式 RPC/pgTAP/Android 确定性结果或已审核 Scenario | 通过其余校验后可进入 Gold Seed |
| `SILVER` | MASS 可复放、程序不变量、Teacher Surface Form 经确定性验证 | 审核或升级后进入正式训练 |
| `SYNTHETIC_UNVERIFIED` | Teacher 新生成、尚未通过业务或人工校验 | 只能 unassigned；禁止正式训练 |

Teacher 只能修改 `surface_form`，不能自行把 Synthetic 提升成 Silver/Gold。

## 7. Rule Tags

Scenario 使用受控业务标签：

`activity`, `expense`, `single_payer`, `multi_payer`, `equal_split`, `manual_split`, `multi_currency`, `ledger_unit`, `transfer`, `fifo_repayment`, `targeted_repayment`, `prepayment`, `prepayment_return`, `refund`, `negative_adjustment`, `void`, `delete`, `bilateral_debt`, `participant_balance`, `final_settlement`, `clarification`, `entity_resolution`, `ui_context`, `interaction_context`, `conversation_context`, `permission`, `unsupported`, `error_handling`, `d4_preview_only`, `pending_default_policy`。

标签用于覆盖统计、数据平衡、定向生成和错误分析，不替代 Intent，也不无限扩展同义标签。

## 8. Sample Schema

[sample.schema.json](schema/sample.schema.json) 表示真正用于训练或评测的一条语言样本。核心字段：

| 分组 | 字段 | 语义 |
| --- | --- | --- |
| 关联 | `sample_id`, `scenario_id`, `scenario_family_id`, `split_group_id` | 回溯确定性 Scenario 与 split |
| 任务 | `task.primary`, `task.secondary` | 一个主任务和多个辅助标签 |
| 难度 | `difficulty`, `challenge_tags` | 采样、测试和错误分析维度 |
| 范围 | `scope`, `policy_status` | 复制冻结 Scope 并阻止 pending 数据进入训练 |
| 表达 | `surface_form` | 用户当前话语、有限会话、语言与表达风格 |
| 模型输入 | `input` | 完整复用 ContextEnvelope，不另造上下文协议 |
| 标准答案 | `expected.model_output` | 完整复用 Model Output Protocol |
| 评测注解 | clarification、entity resolution、diff、evidence | 不污染模型输入或输出协议 |
| 治理 | source/trust/dedup/lifecycle/privacy | 生成来源、审核、去重和隐私门槛 |

ContextEnvelope 已包含 `user_message`，所以 `input` 直接引用整个 Envelope；`surface_form.user_message` 是数据治理层副本，Validator 要求二者相等。额外标签、来源、Trust、Ground Truth 指针均在 Dataset Metadata，不发给模型。

## 9. Task Types

v0.1 冻结为 13 类，不把 70 个 Intent 当成 70 种任务：

1. `intent_classification`
2. `parameter_extraction`
3. `entity_resolution`
4. `clarification`
5. `proposal_generation`
6. `tool_call`
7. `ui_context_reasoning`
8. `interaction_context_reasoning`
9. `conversation_context_reasoning`
10. `result_explanation`
11. `rule_qa`
12. `unsupported_detection`
13. `error_handling`

每个 Sample 只有一个 `primary`，可以有去重后的 `secondary`。例如“这个为什么是120？”在 Expense Detail 页面可同时标为 UI Context、Entity Resolution 和 Result Explanation。

Scope Freeze 中的初始配比 22/18/17/17/10/7/6/3 可以映射到这些任务；最终比例留到 Dataset Planning，不由 Schema 强制。

## 10. Difficulty

| 值 | 定义 |
| --- | --- |
| `easy` | 单 Intent、字段完整、表达明确、无上下文依赖 |
| `normal` | 自然口语、省略或单一页面/实体上下文依赖 |
| `hard` | 多轮、多候选、复杂指代、多个付款人、冲突或复杂业务状态 |
| `ood` | 未见表达、无关/对抗输入、超 Scope 请求或异常格式 |

`hard_test` 是 Dataset Split；`hard` 是单条难度。二者不等价。

## 11. Challenge Tags

v0.1 受控标签为：

`colloquial`, `ellipsis`, `pronoun`, `ui_reference`, `recent_action_reference`, `multi_turn`, `same_name_entity`, `multiple_candidates`, `missing_payer`, `missing_participants`, `missing_split_method`, `missing_amount`, `missing_currency`, `missing_occurred_at`, `contradictory_input`, `typo`, `asr_like`, `cross_activity_reference`, `stale_context`, `unknown_write_state`, `unsupported`, `permission_boundary`, `financial_risk`, `gated_operation`, `deferred_operation`, `d4_preview_only`, `pending_default_policy`, `multi_payer`, `manual_split`, `multi_currency`。

业务覆盖用 Scenario rule tags，语言/推理难点用 Sample challenge tags；两者不能互相替代。

## 12. Ground Truth 与 Surface Form

Ground Truth 由冻结业务逻辑、正式 RPC/测试或人工确定性审核给出。它包含 Intent、标准 Model Output、业务结果、执行政策和可验证断言。Surface Form 只包含语言与有限会话历史。

未来 Teacher Generator 输入必须锁定 Scenario Ground Truth，只能输出候选 Surface Form。生成后重新构造 ContextEnvelope，并校验语言没有改变金额、方向、参与人、Scope、确认等级或预期输出。Compiler 漂移视为错误，不把漂移后的内容反写 Scenario。

`source.teacher` 为 provider-neutral provenance：`teacher_generated` Sample 必须填写 provider、model、generation_run_id、prompt_version、generated_at、temperature 和 seed（API 不支持时为 null）；其他来源必须为 null。Schema 不写死 DeepSeek 模型名或私有 API 字段。计划中的 Generator 面向 `TeacherProvider` 抽象，DeepSeek 是未来 `DeepSeekTeacherProvider` 实现。

Teacher 允许生成 `surface_form`、自然语言、口语/ASR/多轮变体及 clarification/explanation/rule QA 措辞；禁止改变 scenario/family ID、Ground Truth、Intent、Tool、Scope、confirmation level、execution allowed、金额、方向、Participant 身份、财务结果和业务规则结果。冲突输出进入 rejected，不覆盖真值。

## 13. Context、UI 与 Interaction

Sample `input` 使用现有 ContextEnvelope：

- UI：route/page_type、Activity/LedgerUnit、selected entity、form mode；
- Interaction：draft、field_sources、recent_actions、write_state；
- Conversation：有界 messages、confirmed bindings、pending clarification；
- Server：按需 enabled tools、verified result IDs 和 Tool results。

同句不同页面由两个 Scenario 表达，但放入同一 family。例如 Expense Detail 的“这个为什么是120？”可解析 selected Expense；Activity Detail 没有唯一对象时必须 clarification。最近操作只有 `succeeded` 或经对账确认的 `committed_refresh_failed` 才能作为“刚才那个”的稳定候选；`unknown` 不能被当成成功。

对话 Surface Form 最多保存 12 个历史 turn；ContextEnvelope 仍受其现有 20 条上限约束。新 Activity 或 screen instance 变化会使旧绑定失效。

## 14. Clarification

Clarification Sample 同时保存：

- Model Output Protocol 的 `clarification` 对象；
- Dataset 注解 `reason`、`missing_fields`、`candidate_entity_ids`、`question`；
- 必要时保存 Entity Resolution mention 与候选。

两份信息必须一致。注解用于错误分析和分项评分，不是另一套模型输出协议。payer、参与人、split、manual amount、币种/时间 pending policy 和所有资金关键字段缺失时按 Scope Freeze 澄清。

## 15. Entity Resolution

每个 mention 记录 `candidate_ids`、`expected_entity_id`、`resolution_status` 和 `evidence_source`。唯一解析时 expected ID 必须属于候选；无法唯一解析时 expected ID 为 null，输出必须 clarification。

证据来源限于 explicit text、selected entity、draft、recent action、confirmed binding 或 server candidates。所有 ID 仍需 Gateway 验证 Activity 归属、可见性和新鲜度。

## 16. Split 与防泄漏

Split 值为 `unassigned/train/validation/test/hard_test`。分配发生在 Scenario Family 层：

1. 先建立 Scenario 并生成 canonical facts hash；
2. 合并完全重复与语义相同的业务形状；
3. 形成 `scenario_family_id` 和不可变 `split_group_id`；
4. 按 family 分配建议比例 70/10/15/5；
5. 只在该 split 内生成语言变体。

同一 family/split group 不能跨 split。v0.1 Schema 阶段不执行最终切分，全部 Example 保持 `unassigned`。禁止对生成完的语言 Sample 随机 80/10/10。

## 17. 去重

Scenario 使用 `canonical_facts_sha256` 和 `dedup_key`；Sample 使用 `normalization_key`、`dedup_key`、`semantic_group_key`。

- Scenario 去重忽略自然语言、显示标题和合成 UUID 的偶然差异，比较规范业务事实。
- Surface normalization 处理空白、标点、数字格式和大小写。
- Semantic group 聚合“三百/300”“我出的/我付的”等近重复。
- v0.1 不要求 embedding，但跨 split 近重复是阻断错误。

## 18. Confirmation 与执行政策

`execution_allowed` 表示未来 Gateway 在满足 Scope、权限、最新状态和可信确认后是否允许推进；它不表示模型有执行权。

- L0 只读：无需确认；
- L1 普通写提案：允许时必须可信 UI 确认；
- L2 高风险资金/删除/void：允许时必须结构化确认卡和可信 UI event；
- 聊天文字不能成为最终授权；
- execution=false 的 DEFERRED 或 pending policy 样本不产生可执行 proposal；D4 必须产生结构化但不可执行的 proposal，风险等级仍保留。

Dataset `execution.confirmation_required` 是评测/Gateway 元数据；Model Output proposal 同时携带 `confirmation.required=true` 和 level，Validator 必须检查两者一致。该布尔值表示需要可信确认，不表示已经授权。

## 19. GATED 与 DEFERRED

GATED 写 Sample 的初始标准答案必须是符合 Contract 的 L2 `proposal`，并标记 `confirmation_required=true`、`final_authorization=trusted_ui_event_required`。只有可信 UI 确认和 Gateway 复核后的阶段才可形成写 `tool_call`；二者都不能宣称银行付款或 RPC 已成功。

DEFERRED 仅训练边界识别、说明和原生流程引导。输出只允许 `answer` 或 `unsupported`，没有执行性 Tool Call，`execution_allowed=false`。Contract 没有 `native_flow_required` 类型，因此使用 `unsupported.suggested_action`。

Dataset Planning 的初始 Scope 采样目标沿用约 **80% CORE / 16% GATED / 4% DEFERRED 边界识别**。这是 family 与覆盖矩阵层面的规划指标，不由单条 Schema 强制，也不要求本文件的 10 个结构示例符合该比例。

## 20. D4 Expense 财务编辑

`update_expense` 识别和 diff 是 CORE；`update_refund` 是 GATED，但两者的正式写入都被 D4 阻断。Schema 要求：

- `execution_allowed=false`；
- Model Expected Output 必须是 `proposal`，`execution_policy.reason=d4_atomic_update_not_supported`；
- `successful_execution_label_allowed=false`；
- 必须有结构化 `expected_diff`；
- `expected_diff` 必须与 `proposal.preview.diff` 深度相等；
- Context 不暴露 `update_expense` 写 Tool；
- 不得出现“已更新成功”Gold Label。

AI Model Contract v0.1.2 的统一 `proposal` 已解决 `SCHEMA_BLOCKER-01`。D4 现在以结构化 preview/diff 作为模型训练目标，同时由 `execution_allowed=false` 保证即使用户点击确认也不能进入写 RPC。Dataset 继续保留 `expected_diff` 作为独立评测注解。

## 21. Pending Default Policy

Activity base currency 和 Gateway 当前时间是否可自动预填仍为 OPEN_DECISION。相关 Scenario/Sample 使用 `policy_status=excluded_pending_policy`：

- split 必须 unassigned；
- execution/success label 为 false；
- 标准答案使用 clarification；
- 不允许生成“模型自动采用默认值”的正式 Gold 样本。

决策后应新增 Dataset 版本或明确迁移记录，不能静默改旧 Label。

## 22. Lifecycle

状态为 `draft`, `generated`, `validated`, `reviewed`, `approved`, `rejected`, `deprecated`。正常路径是 draft → generated → validated → reviewed → approved；失败可以进入 rejected，版本变化使 approved 转 deprecated。

Teacher 新输出从 generated 开始；Schema/程序校验只提升到 validated；人工或认可的确定性证据才可 reviewed/approved。`example_only=true` 永不进入正式导出。

## 23. Manifest

[dataset_manifest.schema.json](schema/dataset_manifest.schema.json) 保存：

- Dataset/Business/Contract/Scope 版本及冻结 SHA；
- 创建时间、状态、Scenario/Family/Sample 数量；
- family 级 split 策略与 split 统计；
- task、scope、source、trust、difficulty、lifecycle 统计；
- artifact 路径、记录数和内容 SHA；
- Schema/Contract/Scope/Leakage/Policy/Privacy 验证结果。

Manifest 统计必须由记录重算。Example Manifest 只描述示例，不能冒充正式 Dataset Manifest。

## 24. Privacy 与合成 ID

训练数据不得包含生产账号、真实姓名、真实活动、真实账单或完整真实聊天。Dataset 使用 `U001/P001/A001/L001/E001/T001` 等 alias；由于 ContextEnvelope 要求 UUID，模型实际输入使用确定性的合成 UUID，alias 只在 Dataset 状态层出现。

所有正式记录要求 `contains_production_data=false`、`contains_real_personal_data=false`。认证 token、手机号、邮箱、Storage URL、数据库密钥和非必要历史均不得进入 Scenario 或 Sample。

## 25. Canonical Format 与 Training Export

Canonical Schema 保留 Scenario、Context、来源、Trust、Scope、policy、评测注解和审计信息。后续 Exporter 可以把 approved Sample 转为 messages：system 指令由训练配置注入，user 内容来自 ContextEnvelope，assistant 目标来自 `expected.model_output`。

Exporter 不得：随机重新切分、把元数据发送给模型、展开 DEFERRED Tool、把 confirmation metadata 写成模型声称、补 pending 默认值、把 D4 diff 转成可执行调用或把 Example 导入训练。

## 26. 示例覆盖

[scenarios.json](examples/scenarios.json) 包含 9 个 Scenario，[samples.json](examples/samples.json) 包含 10 个 Sample，[dataset_manifest.json](examples/dataset_manifest.json) 包含 1 个 Manifest，共 20 个 `example_only` 记录。

10 个 Sample 联合覆盖：L1 create_expense proposal、L2 Transfer proposal、D4 不可执行 update proposal、query_debt 只读 tool_call、参数提取、同句不同 UI 页面、结果解释、clarification、同名实体、缺 payer、entity resolution、多轮纠正、recent action、DEFERRED unsupported、缺失币种/时间 pending policy。每个 Example 都保持 split=unassigned，不计入正式 Dataset。

## 27. 自动验证

完整规则见 [DATASET_VALIDATION_RULES.md](DATASET_VALIDATION_RULES.md)。最低门槛包括：Schema、Contract、Scope、Confirmation、Ground Truth、Policy、D4、Leakage、Dedup、Lifecycle、Privacy、Manifest。

JSON Schema 处理单记录结构和局部条件；跨记录 family/split、Catalog 引用、Context/Surface 一致、evidence、统计和业务不变量必须由离线 Validator 执行。校验器必须包含非法样本回归，不能只验证正例。

## 28. 与现有验证资产的关系

pgTAP 和正式 RPC 提供确定性业务结果；Android 测试提供 payload、草稿和页面交互事实；MASS500/MASS2000 提供候选业务形状。现有 Verification Scenario v1 是运行数据库业务流程的格式，不直接等于语言 Dataset Scenario：导入时保留原 source ID，但必须补 Scope、Ground Truth 来源、Trust、family、policy 和最小 Context。

MASS 历史记录中的 Compiler 漂移、focus miss、Judge 分歧和弱 Final plan 不能直接转成 Gold。当前数据库 30 文件/223 pgTAP、Android 264 项和 Verification 166 项是历史证据，本阶段没有重新运行这些套件。

### Supporting Lookup Compatibility

Dataset records do not duplicate `tool_role`. The Validator derives `PRIMARY` from Intent Catalog `possible_tools` and `SUPPORTING_LOOKUP` from `supporting_lookup_tools`; the latter must map to a read-only L0 Tool and preserve the user-facing Intent. Gateway prefetch remains permitted, while model-issued `tool_call` and a following clarification are also valid. No Dataset JSON Schema shape changed for this addition.

## 29. Contract / Scope Findings

- 已解决：`SCHEMA_BLOCKER-01` 由 AI Model Contract v0.1.2 的结构化 `proposal` 补齐，D4 target 与 `expected_diff` 可相互校验。
- 非 blocker：ContextEnvelope 使用 UUID，而隐私规范示例使用 `U001/P001`；通过“合成 UUID + Dataset alias”兼容，无需改 Contract。
- 非 blocker：Contract 没有 `native_flow_required`；DEFERRED 使用现有 `unsupported.suggested_action`，与 Scope Freeze 一致。
- 非 blocker：proposal 的 confirmation 声明与 Dataset execution metadata 会交叉校验；最终可信授权事件仍不属于模型输出。

除此之外，没有发现 Dataset Schema 无法表达的 CORE 分类、参数、实体解析、澄清、Context、查询解释、Proposal 或单 Tool Call 能力，也没有新的 `SCHEMA_BLOCKER`。

## 30. Freeze Conclusion

**Dataset Schema v0.1: READY FOR OFFLINE VALIDATOR + GOLD SEED DATASET PLANNING。**

可以进入下一阶段，先实现离线 Validator、制定 family 级 Dataset Plan，再建立少量人工审核的 Gold Seed Scenario/Sample。D4 proposal 保持不可执行，pending 默认值继续排除；下一阶段不得直接批量调用 Teacher、生成大规模数据、最终切分或开始训练。
