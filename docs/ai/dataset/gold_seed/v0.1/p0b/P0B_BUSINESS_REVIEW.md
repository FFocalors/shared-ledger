# P0-B Canonical Scenario 独立业务审核报告

> 状态：**INDEPENDENT BUSINESS REVIEW — 只读审核**。本轮不生成 Sample，不调用 DeepSeek 或任何模型 API，不修改 `scenarios.json`、Contract、AI Scope、Catalog、Model Output Schema、Dataset Schema、Validation Rules、Coverage Matrix、Validator、P0-A 资产、业务逻辑、Android、RPC、数据库，不开始 P0-Gold-Sample 阶段。
> 审核对象：`docs/ai/dataset/gold_seed/v0.1/p0b/scenarios.json`（39 条）、同目录 `README.md`、`docs/ai/dataset/gold_seed/v0.1/p0a/README.md`（冻结生产方法）、`P0A_BUSINESS_REVIEW.md` / `P0A_BUSINESS_REREVIEW.md`、`docs/ai/dataset/GOLD_SEED_COVERAGE_MATRIX_V0.1.md`。
> 版本基线：BUSINESS LOGIC `1.2` / AI Contract `0.1.2` / AI Scope `0.1` / Dataset `0.1`；冻结 SHA `55fb28a7c0660462e5842e2eb5c71cfa763e5801`。
> 定位：全部 39 条均以 `scenario_id + scenario_family_id` 定位，未使用数组序号（数组序号与 scenario_id 在本批恰好一致，不作为定位依据）。

## 1. 审核方法

1. **独立复现机器结论**：逐条重跑 Offline Validator、跑 Validator 单测；自建脚本复核 tool 角色、实体声明/引用、`operation` 与 `state` 参数一致性、冻结词表、`recorded_facts` 结构与去重、断言唯一性、evidence 可解析性、lookup 结果覆盖、`evidence_result_ids` 与已记录 result_id 的绑定、proposal 的 diff/confirmation/execution 语义、Pending Policy 依赖。
2. **逐条 + 独立评审**：39 条分 13 组由独立评审者按 15 个维度审查（另有 4 个跨条批判视角：tool 路径、context 证据、内容真实性、重复与覆盖漂移）；全部判定由我回到文件逐条复核后裁定，未直接采信自动标签。
3. **专查任务点名的三处**：`create_settlement_transfer` 与 `get_settlement_options` 的未执行声明性质；13 个 Conversation Context 标签是否有事实支撑；unique / multiple / zero 三种 lookup 结果的代表场景是否保留。

## 2. 机器复现结果：结构全绿，内容为空

**批次自述全部复现**：P0-B 39 条逐条 Validator **0 error / 0 warning**；Validator 单测 **33/33 OK**；examples validator PASS。

**P0-A 五条方法规则的机器检查在 P0-B 上同样全绿**：

| 检查 | 结果 |
| --- | --- |
| Tool 角色合法性（PRIMARY / SUPPORTING_LOOKUP） | **0 越权** |
| 实体声明与引用完整性（无悬空引用、无重复 id） | **0 违规** |
| `operation.arguments` 与 `state.facts.operation_arguments` 逐字段一致 | **0 不一致**（P0-A 复审核出的 N-01 类问题已修复） |
| 冻结词表（无自造字段名/枚举） | **0 违规** |
| `trust.evidence_refs` 可解析（文件存在、行号在界内） | **39/39 可解析** |
| `deterministic_assertions` 原始字符串唯一 | **15/15… 39/39 唯一**（无重复集合） |
| `evidence_result_ids` ⊆ 已记录 result_id | **全部绑定正确** |
| Proposal 的 L1/L2/D4 层级、`confirmation.required`、`execution_allowed`、`final_authorization`、success label | **10/10 正确** |
| Pending Policy（币种/发生时间） | **0 违规**：需要币种与时间的 proposal 均显式给出 |
| 模型自行计算权威账务结果 | **0 处** |
| lookup 结果覆盖 unique / multiple / zero | **保留**：unique 5、multiple 2、zero 1（022） |

**但上述"全绿"是形式上的**。本批的真实状态是：**记录的结构完美，内容是从 Coverage Matrix 练习目录复制来的占位文本**。P0-A 第一轮的缺陷是"真实业务内容 + 结构缺漏"；P0-B 是"结构无懈可击 + 内容空心"——后者更危险，因为它能通过全部机器闸门。

## 3. 批次级根因（逐条量化，全部机器可复核）

### RC-1 `user_message` 是练习标题，不是用户话语 —— 39/39

`state.facts.recorded_facts` 中标为 `source=user_input` 的 `user_message`，逐字等于 Coverage Matrix 的 family 标题：

| 记录 | `user_message` 实测值 | Matrix 来源 |
| --- | --- | --- |
| 022 | `"最近一次写入失败，不得当作已存在的账目"` | ICTX-003 行标题 |
| 024 | `"未认领的「我」→ 澄清（user_id ≠ participant_id）"` | ENT-002 行标题 |
| 025 | `"第三人称「他/她/他们」：唯一指代 vs 多候选"` | ENT-003 行标题 |
| 026 | `"多轮补全：先给金额与付款人，AI 追问参与人与分摊"` | CONV-001 行标题 |
| 027 | `"聊天「确定」不是授权：L1 新建支出方案"` | CONV-004 行标题 |

31/39 与标题逐字相同，其余为同一标题的变体（如 004「已锁定费用的财务修改 → D4 非可执行 proposal（说明锁定边界）」）。对照 P0-A 已审核记录：`"山野午餐 90 CNY，我在 2026-09-12 12:30 付款，和李四 AA。"`。**该字段是 Sample 阶段的模型输入（`surface_form.user_message` 必须逐字等于 `input.user_message`），因此本批全部 39 条的模型输入目前都是练习名称。**

### RC-2 `ground_truth.model_output` 是描述练习的元模板 —— 33/39

| 形态 | 数量 | 逐字骨架 |
| --- | ---: | --- |
| clarification `question` | 11 | `"关于"<family 标题>"，请补充或确认缺失的信息。"` |
| answer `content` | 12 | `"依据 <FAMILY-ID> 的冻结规则或已验证读取结果，说明"<family 标题>"的业务边界，不自行计算账务结果。"` |
| proposal `preview.summary` | 10 | `"按 <FAMILY-ID> 准备"<family 标题>"提案，等待确认。"` |

这三种文本**都不是业务答案**：它们描述"这一题要做什么"，并把内部 family ID（如 `PRE-CORE-003`、`TRF-002`、`UI-003`）与练习标题直接暴露在模型输出里。唯一例外是 022 的 answer：`"最近一次写入失败，当前没有可编辑的既有支出；请回到账单表单重新录入。"`——真实业务内容。另有 5 条 `tool_call` 记录没有可模板化的文本字段。

### RC-3 业务数据字段写入练习标题 —— 5 条

- `create_expense.arguments.title`：001 `"自付自担的零债务消费"`、012 `"有明确原始账单的关联退款"`、026 `"多轮补全：先给金额与付款人，AI 追问参与人与分摊"`、027 `"聊天「确定」不是授权：L1 新建支出方案"`
- `update_expense_presentation.arguments.title`：005 `"改备注/标题/图标 → L1 展示编辑"`
- lookup `query`：016 `"锁定账单不可删除（真实转账来源/退款历史）"`、022 `"最近一次写入失败，不得当作已存在的账目"`、024 `"未认领的「我」→ 澄清（user_id ≠ participant_id）"`、025 `"第三人称「他/她/他们」：唯一指代 vs 多候选"`

按这些记录训练，模型会学会用练习名称命名账目、并用练习描述作为检索串。（注：033–036、038 的 `query` 是 `lookup_business_rule` 的规则提问，属合法用法。）

### RC-4 `deterministic_assertions` 是同骨架替换 family 名 —— 39/39

把 family id 与标题归一化后：

- `"工具路径为 X；其参数与 operation_arguments 一致，且查找候选由已声明的合成实体支持。"` —— 覆盖 **29 条断言**（且本批 34 条记录没有任何 lookup，"查找候选"在多数记录中不存在）
- `"<FAMILY> 目标是"<标题>"，本场景输出 <out>，意图为 <intent>。"` —— 覆盖 **约 25 条断言**

原始字符串"唯一"只因替换了 family 名而成立。**这直接说明 P0-A 的"assertion 唯一性"检查可被替换 family 名绕过**——这是方法闸门的漏洞，不只是数据问题。

### RC-5 `evidence_refs` 是批次常量，能解析但不支持结论 —— 39/39

| 引用 | 出现次数 | 实测内容 | 判定 |
| --- | ---: | --- | --- |
| `docs/backend/BUSINESS_LOGIC.md#L64` | **39/39** | `## 6. Expense、Payment 与 Split` —— **章节标题本身** | 不合格（P0-A 方法明文规定"章节标题文本…都不合格"） |
| `docs/ai/schema/intent_catalog.json#L1` | **39/39** | `{` —— **文件首字符** | 不合格 |
| `docs/ai/dataset/GOLD_SEED_COVERAGE_MATRIX_V0.1.md#L<行>` | 各 1 | 对应 family 行 ✓ | 合格 |

即：本批"evidence 可解析"是通过指向一个章节标题和一个 `{` 达成的，**没有一条引用真正指向支撑其结论的规则正文**（例如 001 真正依赖的"零债务 Expense 仍是有效消费事实"在 `BUSINESS_LOGIC.md#L70`）。

### RC-6 State Recording 只有 1 条事实 —— 34/39

`recorded_facts` 长度分布：**长度 1 者 34 条**，长度 3 者 2 条，长度 4 者 1 条，长度 5 者 2 条。且 **8/8 个 proposal 记录**在 `model_output.operation.arguments` 中断言了无来源的字段：

| 记录 | 无 recorded_fact 来源的 GT 字段 |
| --- | --- |
| 001、012、026、027 | `original_amount`、`payments`、`manual_splits`、`aa_participant_ids`、`split_method` |
| 004、018、020 | `payments`、`manual_splits`、`aa_participant_ids`、`split_method` |
| 015 | `suggestion_id` |

其中 `payments` / `split_method` / `manual_splits` 属 P6 FORBIDDEN_INFERENCE 字段，本批连"明确来源"都没有；唯一的 `user_message`（RC-1）又不含任何金额或参与人。

### RC-7 幽灵实体：声明但从未引用 —— 39/39，共 160 个

每条记录的 `state.entities` 都含 `operation` / `ground_truth` / `facts` 从未引用的实体（001 有 4 个、002 有 5 个、007 有 5 个…），与 `minimal_state_reason`"仅保留完成当前 Intent 与 Ground Truth 所需事实"的声明矛盾。且这些实体在各记录间高度重复（同一批 id），说明实体块是复制粘贴的。

### RC-8 `rule_tags` 与实际输出矛盾 —— 13 条

- 001 `rule_tags=["clarification"]` 但 `expected_output_type="proposal"`
- 010、034、035、037 `rule_tags=["clarification"]` 但输出是 `answer`
- 013、021、023、024、025、030、031、032 输出是 clarification 但 `rule_tags` 里**没有** `clarification`

`rule_tags` 是覆盖统计与数据平衡的受控维度，本批的标签与事实无关。

### RC-9 生产元数据进入记录字段 —— 39/39

`description` 与 `operation.description` 逐字为 `"合成 Canonical Scenario 对齐 Coverage Matrix <FAMILY-ID>：<family 标题>。"`——是生产说明，不是业务描述。`scenario.title` 亦有 31/39 为 `"<FAMILY-ID>: <family 标题>"` 形式。

### 批次级结论

RC-1 ~ RC-9 覆盖全部 39 条。**P0-A 建立的五条方法规则在本批被逐条"形式上满足、实质上违反"**：规则检查的是记录的**形状**（字段是否存在、引用是否解析、断言是否唯一、词表是否合法），而生成过程把 **Coverage Matrix 的行文本直接当作记录内容**，因此每一项形状检查都能通过。

## 4. 逐条审核表（39/39，无抽样）

修复层级：**T1** = 模型输出本身即元模板（训练目标错）；**T2** = 输出为真实业务内容，但输入侧事实/断言/evidence/实体仍需重写。

| # | scenario_id | family_id | primary_task | output | 记录级缺陷（除 §3 批次级之外） | 修复层级 | verdict | severity |
| --- | --- | --- | --- | --- | --- | :-: | --- | --- |
| 1 | `scenario_gs_p0b_001` | `EXP-CREATE-005` | `proposal_generation` | `proposal` | summary 为元模板；业务标题=练习标题 | T1 | **REJECT** | BLOCKER |
| 2 | `scenario_gs_p0b_002` | `EXP-CLARIFY-002` | `clarification` | `clarification` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 3 | `scenario_gs_p0b_003` | `EXP-CLARIFY-007` | `parameter_extraction` | `clarification` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 4 | `scenario_gs_p0b_004` | `EXP-EDIT-003` | `proposal_generation` | `proposal` | summary 为元模板 | T1 | **REJECT** | BLOCKER |
| 5 | `scenario_gs_p0b_005` | `EXP-EDIT-004` | `proposal_generation` | `proposal` | summary 为元模板；业务标题=练习标题 | T1 | **REJECT** | BLOCKER |
| 6 | `scenario_gs_p0b_006` | `EXP-READ-001` | `parameter_extraction` | `tool_call` | 输出为真实业务内容（仅批次级缺陷） | T2 | **REVISE** | MAJOR |
| 7 | `scenario_gs_p0b_007` | `ACT-002` | `tool_call` | `tool_call` | 输出为真实业务内容（仅批次级缺陷） | T2 | **REVISE** | MAJOR |
| 8 | `scenario_gs_p0b_008` | `DEBT-002` | `tool_call` | `tool_call` | 输出为真实业务内容（仅批次级缺陷） | T2 | **REVISE** | MAJOR |
| 9 | `scenario_gs_p0b_009` | `PRE-CORE-003` | `result_explanation` | `answer` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 10 | `scenario_gs_p0b_010` | `TRF-002` | `result_explanation` | `answer` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 11 | `scenario_gs_p0b_011` | `PRE-GATED-004` | `clarification` | `clarification` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 12 | `scenario_gs_p0b_012` | `REF-001` | `proposal_generation` | `proposal` | summary 为元模板；业务标题=练习标题 | T1 | **REJECT** | BLOCKER |
| 13 | `scenario_gs_p0b_013` | `REF-002` | `clarification` | `clarification` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 14 | `scenario_gs_p0b_014` | `FIN-001` | `tool_call` | `tool_call` | 输出为真实业务内容（仅批次级缺陷） | T2 | **REVISE** | MAJOR |
| 15 | `scenario_gs_p0b_015` | `FIN-002` | `proposal_generation` | `proposal` | summary 为元模板 | T1 | **REJECT** | BLOCKER |
| 16 | `scenario_gs_p0b_016` | `DEL-002` | `result_explanation` | `answer` | 输出为元模板；lookup query=练习描述 | T1 | **REJECT** | BLOCKER |
| 17 | `scenario_gs_p0b_017` | `UI-001` | `ui_context_reasoning` | `answer` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 18 | `scenario_gs_p0b_018` | `UI-002` | `ui_context_reasoning` | `proposal` | summary 为元模板 | T1 | **REJECT** | BLOCKER |
| 19 | `scenario_gs_p0b_019` | `UI-003` | `ui_context_reasoning` | `proposal` | summary 为元模板 | T1 | **REJECT** | BLOCKER |
| 20 | `scenario_gs_p0b_020` | `ICTX-001` | `entity_resolution` | `proposal` | summary 为元模板 | T1 | **REJECT** | BLOCKER |
| 21 | `scenario_gs_p0b_021` | `ICTX-002` | `clarification` | `clarification` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 22 | `scenario_gs_p0b_022` | `ICTX-003` | `interaction_context_reasoning` | `answer` | lookup query=练习描述 | T2 | **REVISE** | MAJOR |
| 23 | `scenario_gs_p0b_023` | `ICTX-006` | `interaction_context_reasoning` | `clarification` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 24 | `scenario_gs_p0b_024` | `ENT-002` | `entity_resolution` | `clarification` | 输出为元模板；lookup query=练习描述 | T1 | **REJECT** | BLOCKER |
| 25 | `scenario_gs_p0b_025` | `ENT-003` | `entity_resolution` | `clarification` | 输出为元模板；lookup query=练习描述 | T1 | **REJECT** | BLOCKER |
| 26 | `scenario_gs_p0b_026` | `CONV-001` | `conversation_context_reasoning` | `proposal` | summary 为元模板；业务标题=练习标题 | T1 | **REJECT** | BLOCKER |
| 27 | `scenario_gs_p0b_027` | `CONV-004` | `conversation_context_reasoning` | `proposal` | summary 为元模板；业务标题=练习标题 | T1 | **REJECT** | BLOCKER |
| 28 | `scenario_gs_p0b_028` | `CONV-006` | `conversation_context_reasoning` | `tool_call` | 输出为真实业务内容（仅批次级缺陷） | T2 | **REVISE** | MAJOR |
| 29 | `scenario_gs_p0b_029` | `CONV-007` | `result_explanation` | `answer` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 30 | `scenario_gs_p0b_030` | `CLR-001` | `clarification` | `clarification` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 31 | `scenario_gs_p0b_031` | `CLR-002` | `intent_classification` | `clarification` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 32 | `scenario_gs_p0b_032` | `CLR-005` | `clarification` | `clarification` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 33 | `scenario_gs_p0b_033` | `RULE-001` | `rule_qa` | `answer` | 输出为元模板；lookup query=练习描述 | T1 | **REJECT** | BLOCKER |
| 34 | `scenario_gs_p0b_034` | `RULE-003` | `rule_qa` | `answer` | 输出为元模板；lookup query=练习描述 | T1 | **REJECT** | BLOCKER |
| 35 | `scenario_gs_p0b_035` | `RULE-004` | `rule_qa` | `answer` | 输出为元模板；lookup query=练习描述 | T1 | **REJECT** | BLOCKER |
| 36 | `scenario_gs_p0b_036` | `RULE-005` | `rule_qa` | `answer` | 输出为元模板；lookup query=练习描述 | T1 | **REJECT** | BLOCKER |
| 37 | `scenario_gs_p0b_037` | `RULE-006` | `error_handling` | `answer` | 输出为元模板 | T1 | **REJECT** | BLOCKER |
| 38 | `scenario_gs_p0b_038` | `RULE-007` | `error_handling` | `answer` | 输出为元模板；lookup query=练习描述 | T1 | **REJECT** | BLOCKER |
| 39 | `scenario_gs_p0b_039` | `RULE-008` | `error_handling` | `answer` | 输出为元模板 | T1 | **REJECT** | BLOCKER |

**统计**：REJECT 33（T1）/ REVISE 6（T2）/ PASS 0。BLOCKER 记录级 33 条（模型输出为元模板或业务数据为练习名）；MAJOR 6 条（输出真实但输入侧与元数据不达标）；批次级 BLOCKER 9 类（RC-1 ~ RC-9）适用于全部 39 条。

## 5. 记录级业务错误（输出层之外的实质错误）

| 记录 | 等级 | 问题 | 证据 |
| --- | --- | --- | --- |
| `scenario_gs_p0b_012` (`REF-001`) | **BLOCKER** | **关联退款写成正数且缺少必填的 `original_expense_id`**。BUSINESS_LOGIC §13 规定 Refund 是**负 Expense**；`create_refund` 的 intent notes 要求 `original_expense_id` 明确且 `original_amount/payment/manual_split` 使用负数。本记录 `original_amount="50"`（正）、`payments`/`manual_splits` 均为正 50、**`original_expense_id` 完全缺失**、且没有任何 `get_expense` 读取，故"关联原单"无来源 | `model_output.operation.arguments`；`scope.tool_ids=["create_expense"]`；`state.facts.recorded_facts` 仅 user_message。**Model Output Schema 未约束退款符号与 `original_expense_id`，Validator 因此放行** |
| `scenario_gs_p0b_015` (`FIN-002`) | **BLOCKER** | **L2 资金提案的目标是合成占位符且未读取服务端方案**。`suggestion_id="suggestion-synthetic-001"`，`expected_business_result.supporting_lookup={}`，全记录没有 `get_final_settlement` 读取；BUSINESS_LOGIC §14 要求执行"服务端当前生成的完整建议"并复核版本，不得自行构造 | `model_output.operation.arguments.suggestion_id`；`expected_business_result` |
| `scenario_gs_p0b_004` / `018` / `020` | MAJOR | **D4 diff 的 `payments`/`manual_splits` before 值无来源**。三条记录只把 `original_amount` 与 `financial_version` 记入 `recorded_facts`，却断言了付款与分摊的 before/after。P0-A 复审核过的 009 用完整 `verified_read_result`（含当前 payments/splits）解决过同一问题，本批未复用该模式 | `recorded_facts` 字段集 vs `preview.diff` |
| `scenario_gs_p0b_022` (`ICTX-003`) | MAJOR | 本批唯一输出真实内容的记录，但其金标答案的前提"最近一次写入失败"**没有任何事实记录**（无 `recent_actions`、无 `write_state`），尽管 `rule_tags` 声明了 `interaction_context` | `state.facts` 键集；`rule_tags=["interaction_context"]` |
| `scenario_gs_p0b_006` / `014` / `019` | MINOR | `evidence_refs` 只有 Matrix 行一条合格（RC-5）；`014`/`019` 另有声明但无路径的 Tool（见 §6） | 见 §5、§6 |

**未发现**：Pending Policy 被偷偷采用（0 条）、模型自行计算权威账务（0 条）、把聊天文字当授权（0 条）、L1/L2/D4 确认语义错误（0 条）、`evidence_result_ids` 与已记录 result_id 不匹配（0 条）。这些维度本批是干净的。

## 6. 两个"未实际调用 Tool"的结论（任务点名）

本批 **16 个不同 Tool 被声明，13 个形成真实路径**；**11 条记录存在"声明但无路径"的 Tool**。逐项裁定：

| Tool | 出现在 | 结论 | 等级 |
| --- | --- | --- | --- |
| `get_settlement_options` | 仅 010 (`TRF-002`) | **不合理的多余声明，但不是缺失路径**。010 的金标是`answer`（解释可结算额上限），其上限来自已记录的 `get_debt` 读取（`result-p0b-trf-002` 已绑定），金标不依赖候选列表，故该 Tool 无用途也无需补读取。建议从 `scope.tool_ids` 移除 | MINOR |
| `create_settlement_transfer` | 仅 027 (`CONV-004`) | **既非真实路径也非合理前向声明**。027 的 `model_output` 是 `create_expense` 的 L1 proposal，`create_settlement_transfer` 没有 operation / lookup / verified-read 任何路径；更关键的是**027 没有记录任何会话事实**（`state.facts` 无对话轮次、无 pending proposal），因此"存在一个待确认的 L2 转账方案"这一前提在记录中不存在，该 Tool 的声明无依据。应二选一：把 pending 的 L2 方案作为会话事实记入 state 并给出其读取路径，或删除该 Tool 与相应 intent | MAJOR |
| `lookup_business_rule` | 004、009、010、014、016、033–039 | **合理**：这些记录的金标 answer 均绑定了已记录的规则读取结果（`evidence_result_ids` 与 `recorded result_id` 一致） | — |
| `create_expense` / `get_debt` / `get_participant_balance` / `find_expenses` / `create_expense`（各 1–2 条） | 002、013、019、024、025 | 同类的"声明但本轮未执行"：澄清类记录按 P0-A 方法应只声明本轮实际读取的 Tool（P0-A 同型记录写 `[]` 或只写 lookup）。属**口径不统一**，非资金风险 | MINOR |

**结论**：`get_settlement_options` 属合理范围内的多余声明（MINOR）；`create_settlement_transfer` 属**无依据声明**（MAJOR，且根源是会话事实缺失，与 §7 同因）。

## 7. Conversation / UI / Interaction Context：有标签，无证据（任务点名）

| 标签 | 记录数 | 有对应事实的记录 |
| --- | ---: | --- |
| `conversation_context` | 12（006、009、013、014、026、027、028、029、030、031、036、038） | **0** —— 全部只有一条 `user_message`，无对话轮次、无 `confirmed_bindings`、无 pending proposal、无历史 turn |
| `ui_context` | 12 | 少数（018 有 `ui_context` 事实；017、019、020、021、022、023 等无） |
| `interaction_context` | 10 | 少数（020 记了 `recent_actions.status`）；022 的金标断言写入了"写入失败"但 state 无 `recent_actions`/`write_state` |

其中 4 条以 `conversation_context_reasoning` 为 **primary task**（026 CONV-001 多轮补全、027 CONV-004 聊天确认非授权、028 CONV-006 旧绑定失效、029 CONV-007 方案后追问），它们**必须**依赖多轮事实才能成立：

- 026 的 family 是"先给金额与付款人，AI 追问参与人与分摊"——需要两轮，记录只有一条消息；
- 028 的 family 是"跨活动切换后旧绑定失效"——需要先有一个旧绑定，记录里没有；
- 029 的 family 是"方案生成后追问『记好了吗』"——需要先有一个 pending proposal，记录里没有（且 `evidence_result_ids=[]`）。

**结论：任务所担心的"有 context tag，但没有 context evidence"在本批成立，且是 12/12 的系统性缺失**——这正是 RC-6（State Recording 空心）在上下文维度的表现。

## 8. 重复与覆盖漂移

**结构性近重复 5 簇**（按 intent + 输出 + tool 集 + 操作类型 + lookup 结果 + missing_fields + 确认级别比较，不以金额/姓名判断）：

| 簇 | 成员 | 说明 |
| --- | --- | --- |
| 1 | 001 ↔ 026 | 同为 `create_expense` L1 proposal、无 lookup、指纹完全相同；026 本应是多轮补全形态，因无会话事实而塌缩成 001 的形状 |
| 2 | 003 ↔ 023 | 同为 `create_expense` clarification(missing_fields=["payer"])；023 的 family 是"ui_default 不构成授权"（应有 draft/ui_default 事实），实际未编码 |
| 3 | 018 ↔ 020 | 同为 `update_expense` D4、`get_expense` 唯一 lookup、三字段 diff（100→120）——编码完全相同，仅 family 不同（UI-002 vs ICTX-001） |
| 4 | 033 / 034 / 035 / 036 | 4 条 `explain_rule` answer、`lookup_business_rule`，编码与**模板化内容**均相同；不因规则主题不同而可区分 |
| 5 | 037 / 038 / 039 | 3 条 `explain_error` answer，同上 |

**覆盖漂移**：`UI-002` 家族是"同句在不同页面的**对照**家族"（一个有选中账单、一个没有），018 只编码了其中一支；`ICTX-006`（023）与 `ICTX-003`（022）的 ui/interaction 事实缺失使家族目标未兑现；`DEL-002`（016）的 `answer` 未给出真实的锁定原因解释（模板）。

**支持性结论**：批次 README 声明的 unique/multiple/zero 覆盖属实（022 的零匹配分支真实且内容真实），**这一项没有回退**——任务担心的第三种结果代表场景是保留的。

## 9. 本批确实做对的部分（不掩盖问题，也不夸大问题）

为避免报告失衡，明确记录以下维度**没有**发现问题：

1. **Proposal 层级与确认语义全部正确**：L1 7 / L2 3；`confirmation.required=true`、`final_authorization=trusted_ui_event_required`、L2 无降级、D4 三条 `execution_allowed=false` + `reason=d4_atomic_update_not_supported` + `successful_execution_label_allowed=false`，无一条声称已执行。
2. **无 Pending Policy 依赖**：需要币种与发生时间的提案均显式给出，无一条靠默认预填。
3. **无模型自行计算账务**：规则/解释类金标均绑定已记录读取结果，`evidence_result_ids` 与 `recorded result_id` 逐条一致。
4. **lookup 三结果覆盖保留**：unique 5 / multiple 2 / zero 1，零匹配记录未编造目标对象。
5. **结构一致性优于 P0-A 第一轮**：0 越权、0 悬空实体引用、0 `operation`↔`state` 参数不一致、0 词表违规、evidence 全部可解析（虽然指向不合格位置）。
6. **001 之外的 `rule_tags`、`description` 等元数据问题不涉及资金语义**。

也就是说：**本批不是"业务判断错了"，而是"根本没有写业务内容"**。它的资金语义维度（确认级别、执行政策、D4、授权）是对的；它的**训练输入与训练目标**是空的。

## 10. 系统性判断：P0-B 是否再次出现方法级问题？

**是。而且是新的、更危险的一种。**

**与 P0-A 第一轮的区别**：P0-A 第一轮的缺陷是"真实的业务数据 + 结构缺漏"（Gold 引用了 state 里没有的金额、标签互相矛盾、diff 漏列字段）。P0-B 的缺陷是"**完美的结构 + 空心的内容**"——生成过程把 Coverage Matrix 的行文本（family id、标题、任务描述）直接搬进记录的 `title`、`user_message`、`model_output`、`assertion`、`description`，使每一条形状检查都能通过。

**为什么会通过全部闸门**：P0-A 的 5 条方法规则 + 7 条 preflight 自检，检查的全是记录的**形状**：
- "State Recording Contract" 检查是否有 `recorded_facts` 且 source 合法 → 有一条 `user_message` 即通过；
- "Scenario-specific assertions" 检查断言是否唯一 → 替换 family 名即唯一；
- "Resolvable evidence references" 检查引用是否可解析 → 指向章节标题与 `{` 也可解析；
- "Frozen vocabulary" 检查字段名是否取自 Catalog → 标题文本写进 `title` 字段仍是合法字符串；
- "Coverage reconciliation" 检查 intent/tool/输出类型是否与 family 行一致 → 本批完全一致（确实一致）。

**没有一条规则问："这条记录里的用户话语、模型输出和业务数据，是不是真实的业务内容？"** 这是方法的结构性缺口，会以完全相同的方式复制到任何后续批次。

**判定**：这属于任务所指的"会污染整个 Gold Sample 生产的方法级问题"，而不是"少量机械性单条问题"。相应地，本轮结论为 `NOT_READY_FOR_P0_GOLD_SAMPLE`（§11.3）。

## 11. 结论

### 11.1 统计

| 项 | 数量 |
| --- | ---: |
| 审核 Scenario | **39 / 39**（无抽样，按 `scenario_id + scenario_family_id` 定位） |
| `PASS` | **0** |
| `REVISE` | **6**（006、007、008、014、022、028 —— 输出为真实业务内容，输入侧与元数据待重写） |
| `REJECT` | **33**（模型输出本身是元模板，或业务数据写入练习标题） |
| 记录级 BLOCKER | **33**（另 2 条业务语义 BLOCKER 已含在内：012 退款正数且缺 `original_expense_id`、015 目标为合成占位符） |
| 记录级 MAJOR | **6**（T2 组） |
| 批次级 BLOCKER | **9 类**（RC-1 ~ RC-9），适用于全部 39 条 |
| 建议 `APPROVE_AS_GOLD` | **0** |
| 建议 `KEEP_SILVER` | **39**（维持现状正确；不因本轮审核升级任何记录） |
| 近重复簇 | **5**（涉及 12 条记录） |
| 覆盖漂移 | 3 处（018、023、016） |
| Tool 路径问题 | 无依据声明 1（027 `create_settlement_transfer`，MAJOR）；多余声明 5（MINOR） |
| Context 标签无证据 | `conversation_context` 12/12；`ui_context`、`interaction_context` 各有多条 |
| Pending Policy / 计算泄漏 / 授权越界 / 确认语义错误 | **0** |

### 11.2 需修订的 Scenario

**全部 39 条均需重写内容**，方向一致但成本分两档：

- **T1（33 条，REJECT）**：重写 `ground_truth.model_output`（真实问句/真实解释/真实提案摘要），重写业务数据标题与 lookup query，重写 `user_message`、`assertions`、`description`、`title`，删除幽灵实体，修 `rule_tags`，并把 evidence 指向真正支撑结论的规则正文。**其中 012 与 015 必须先修业务语义**（退款负数 + `original_expense_id` + 原单读取；final settlement 的服务端方案读取）。
- **T2（6 条，REVISE）**：输出已是真实内容，只需重写输入侧与元数据（`user_message`、`assertions`、`evidence_refs`、`description`、幽灵实体、`rule_tags`），并为 022 补记"写入失败"事实、为 006/014/019 处理声明但无路径的 Tool。

### 11.3 是否存在 `GOLD_SEED_BLOCKER`

**是，存在两项。**

```text
GOLD_SEED_BLOCKER-P0B-01（数据级）
P0-B 全部 39 条的记录内容由 Coverage Matrix 练习目录文本生成：
user_message = family 标题（39/39）、model_output = 元模板（33/39）、
业务标题与 lookup query = 练习标题（9 处）、assertions = 同骨架替换（54 条）、
evidence_refs = 章节标题与 "{"（78 处）、description/title = 生产元数据（39/39）。
在重写之前，本批不能产出任何一条合法 Gold Sample。
```

```text
GOLD_SEED_BLOCKER-P0B-02（方法级）
P0-A 生产方法的 5 条规则与 7 条 preflight 只校验记录的"形状"，
不存在任何"内容真实性"检查，因此
（a）以 family 目录文本填充记录即可通过全部机器闸门；
（b）"assertion 唯一性"可被替换 family 名绕过；
（c）"evidence 可解析"可被指向章节标题与 "{" 满足。
在该缺口补齐之前，任何后续批次都会以同样方式产出"全绿但空心"的数据。
```

### 11.4 P0-Gold-Sample 准入判断

```text
NOT_READY_FOR_P0_GOLD_SAMPLE
```

**解除条件（三项，全部属"改数据 + 补方法闸门"，不需要改冻结资产）**：

1. **先补方法闸门**，再重做数据：为 preflight 增加**内容真实性检查**，至少包括——
   (a) `user_message` 必须是可发出的用户话语，且不得等于 family 标题/family id；
   (b) `model_output` 的 `question` / `content` / `preview.summary` 不得包含 family id、family 标题或"依据 X 的冻结规则…的业务边界"式元描述；
   (c) `title` / `operation.arguments.title` / lookup `query` 不得等于 family 标题或含练习术语（`→`、`L1/L2`、`proposal≠` 等）；
   (d) 断言必须在**归一化 family id/标题后**仍互不相同，且每条可用 state 或 verified result 判定；
   (e) `evidence_refs` 的每一行必须落在支撑结论的正文，章节标题行与文件首字符不合格；
   (f) `state.entities` 中每个实体都必须被 operation / ground_truth / facts 引用；
   (g) `rule_tags` 必须与 `expected_output_type` 一致。
2. **重写 39 条记录**（T1/T2 两档），优先修 `scenario_gs_p0b_012` 与 `scenario_gs_p0b_015` 的业务语义。
3. **重跑 P0-A 的 5 条规则 + 上述 7 项内容检查 + 独立业务复审**，并对 P0-A 的 001/002/013 做同样的内容真实性回归（它们已升 GOLD；本轮未发现其内容为模板，但同一生成管线值得回归确认）。

**不建议**：在未完成上述三项前进入 Gold Sample 生产；本批的 33 条 T1 记录若直接进入 Sample 阶段，模型将学到"输出练习名称与模板句"，这是比"业务答案错误"更难纠正的污染。

### 11.5 本轮边界

未生成任何 Sample；未调用 DeepSeek 或任何模型 API；未修改 `scenarios.json`、Contract、AI Scope、Catalog、Model Output Schema、Dataset Schema、Validation Rules、Coverage Matrix、Validator、P0-A 资产、业务逻辑、Android、RPC、数据库；未提交 Git。本报告是本轮**唯一新增文件**。
