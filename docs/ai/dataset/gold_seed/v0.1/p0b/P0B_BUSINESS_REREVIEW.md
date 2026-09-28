# P0-B Canonical Scenario 第二次独立业务复审报告

> 状态：**SECOND INDEPENDENT BUSINESS REVIEW — 只读复审**。本轮不生成 Sample，不调用 DeepSeek 或任何模型 API，不修改 `scenarios.json`（P0-A / P0-B）、Contract、AI Scope、Catalog、Model Output Schema、Dataset Schema、Validation Rules、Coverage Matrix、Validator、业务逻辑、Android、RPC、数据库，不开始 P0-Gold-Sample 阶段。
> 复审对象：`docs/ai/dataset/gold_seed/v0.1/p0b/scenarios.json`（39 条）、同目录 `README.md`、`P0B_BUSINESS_REVIEW.md`（上一轮）、`docs/ai/dataset/gold_seed/v0.1/p0a/README.md`（生产方法与 Content Authenticity Preflight）、P0-A 两个批次的 `scenarios.json`、`docs/ai/dataset/GOLD_SEED_COVERAGE_MATRIX_V0.1.md`。
> 版本基线：BUSINESS LOGIC `1.2` / AI Contract `0.1.2` / AI Scope `0.1` / Dataset `0.1`；冻结 SHA `55fb28a7c0660462e5842e2eb5c71cfa763e5801`。
> 定位：全部以 `scenario_id + scenario_family_id` 定位，未使用数组序号。

## 1. 审核方法

1. **独立复现全部机器结论**：逐条重跑 Offline Validator（P0-A / P0-B 分别跑）、跑 Validator 单测、跑 examples validator；自建脚本复核上一轮的全部根因项（user_message 真实性、model_output 元模板、业务标题/查询、断言归一化去重、evidence 实质性与解析、幽灵实体、rule_tags 与输出一致性、GT 参数接地、tool 声明与真实路径、lookup 基数、context 标签与事实、冻结枚举）。
2. **回到文件逐条裁定**，未采信批次自述。
3. **专项**：FIN-002 的 A/B/C 选项裁决；P0-A 三条降级记录的合理性；两个点名维度（Tool 路径、Conversation Context）。

## 2. 机器复现结果

| 检查 | 批次自述 | 本轮复现 | 结论 |
| --- | --- | --- | --- |
| P0-B Validator（39 条逐条） | 39/39，0 error，0 warning | **39/39，0 error，0 warning** | ✓ 属实 |
| Validator 单测 | 38/38 PASS | **38/38 OK** | ✓ 属实 |
| examples validator | PASS | **PASS**（3 条既有 duplicate/semantic-group warning） | ✓ 属实 |
| **P0-A Validator（15 条逐条）** | 未提及 | **28 error / 12 条记录不通过** | ✗ **批次自述未覆盖，见 §7** |

**新机器闸门的实际覆盖面**（读 `validator.py` 后确认）：`_validate_scenario_authenticity` 覆盖 `user_message`、`ground_truth.model_output`（仅 `content`/`question`/`summary` 三个用户可见字段）、业务标题/查询、evidence 行质量、实体未引用、`rule_tags` 与输出/上下文事实；`_validate_scenario_batch_authenticity` 覆盖断言的 family-id/title 归一化去重。**它不覆盖 `ground_truth.expected_business_result`**——这正是本轮主要残留所在（§4.1）。

## 3. 重写确实修好的部分（先确认成绩，再讲问题）

对上一轮 9 类批次级根因逐项复测，**全部关闭**：

| 上轮根因 | 上轮实测 | 本轮实测 | 结论 |
| --- | --- | --- | --- |
| RC-1 `user_message` = family 标题 | 39/39 | **39/39 为真实业务话语**（如 `"2026年9月12日中午，早餐花了50元，我付的，这笔只算我一个人。"`、`"我准备给林转120元，系统为什么提示当前最多只能付80元？"`） | **关闭** |
| RC-2 `model_output` = 元模板 | 33/39 | **0**（无 family id、无"依据 X 的冻结规则…的业务边界"式元描述） | **关闭** |
| RC-3 业务标题/查询 = 练习标题 | 9 处 | **0**（`lookup_business_rule` 的 query 是用户原问题，属合法用法） | **关闭** |
| RC-4 断言 = 同骨架替换 family 名 | 29 + 25 条 | **78 条断言全部互不相同，且不含 family id**（每记录 2 条） | **关闭** |
| RC-5 evidence 指向章节标题/`{` | 78 处 | **117 处实质引用，0 处标题/分隔符/根花括号** | **关闭** |
| RC-6 GT 参数无来源 | 8/8 proposal | **0/8**（`recorded_facts` 长度分布 1:8、2:17、3:4、4:2、6:2、9:1、10:5） | **关闭** |
| RC-7 幽灵实体 | 39/39，160 个 | **0** | **关闭** |
| RC-8 `rule_tags` 与输出矛盾 | 13 条 | **0** | **关闭** |
| RC-9 生产元数据进字段 | 39/39 | `description` 已改为业务描述 | **关闭** |

**点名维度一（Tool 路径）**：`scope.tool_ids` 中"声明但本轮无 operation / lookup / verified-read 路径"的记录 **0 条**（上轮 11 条）。上轮点名的两个 Tool 均已处置得当：`get_settlement_options` 已从 010 移除（金标上限由已记录的 `get_debt` 读取支撑）；`create_settlement_transfer` 已从 027 移除，027 改为 `answer` 且工具列为空（与其"聊天确认不是授权"的家族目标一致）。

**点名维度二（Conversation Context）**：5 条 `conversation_context` 记录**全部有真实对话事实**——026 记录了 `turn-1 "今天晚餐90元，我先垫。"` / `turn-2 "我和林AA。"` 的两轮补全；027/029 记录了 `pending_proposal`；028 记录了消息 + `recent_actions`。UI 8/8、Interaction 4/4 亦均有对应事实。**上轮"有标签无证据"的问题彻底解决。**

**其他要点确认**：012 已改为负数 `-50` 且 `original_expense_id` 来源为 `server_result`（`verified_read_result` 记录了 100 CNY 正原单）✓；023 的 `policy_status=pending` + `split=unassigned` + `execution_allowed=false`，符合 Validation Rules §10 ✓；断言 78/78 唯一且无 family 名 ✓；pending policy 无违规（所有含金额的 proposal 均显式给出币种与发生时间）✓；lookup 三结果保留（unique 2 / multiple 1 / zero 1，022 的零匹配真实且不编造目标）✓。

**结论：上一轮 `GOLD_SEED_BLOCKER-P0B-01`（数据级）与 `-02`（方法级）均已解除。** 本轮的发现全部是新的、范围窄得多的问题。

## 4. 本轮发现

### 4.1 MAJOR（批次级）：`expected_business_result` 未随重写更新

重写覆盖了 `state`、`model_output`、`title`、`description`，但**没有更新 `ground_truth.expected_business_result`**：

| 现象 | 数量 | 记录 |
| --- | ---: | --- |
| `ground_truth` 内仍含 Coverage Matrix family 标题 | **15** | 005、006、013、016、017、022、024、025、033–039 |
| `ground_truth` 内仍含已不存在的旧 `result-p0b-*` id（state 现用 `result-*-verified`） | **20** | 006、007、008、009、010、013、014、016、017、022、024、025、028、033–039 |
| `ebr.supporting_lookup` 与 `state.facts.supporting_lookup_result` 不一致 | **22 / 22（全部有 lookup 的记录）** | — |

典型例（022）：state 记录 `query="地铁票 78元"`、`result_id="result-ictx-003-verified"`；同一记录的 `expected_business_result.supporting_lookup` 仍写 `query="最近一次写入失败，不得当作已存在的账目"`、`result_id="result-p0b-ictx-003"`——**上一轮的练习描述文本与失效 id 原样留在注解里**。

**根因**：`_validate_scenario_authenticity` 只遍历 `ground_truth.model_output`，从不访问 `expected_business_result`。因此这类残留能通过全部机器闸门。

**等级 MAJOR 而非 BLOCKER 的理由**：ebr 不是模型输入也不是模型输出（模型看到 `state`，产出 `model_output`），因此不直接污染训练信号；但它是 Dataset 的交叉校验目标（`expected_diff`、`verified_result_ids`），旧 id 会切断证据链，并在 Sample 阶段被继承为注解。**必须在生成 Sample 之前修复，否则脏注解会进入正式数据。**

### 4.2 BLOCKER（单条）：`scenario_gs_p0b_018` 的 D4 diff 与自身已验证读取矛盾

- `state.facts.verified_read_result.expense.title = "周末民宿"`（这是本记录自己引用的服务端读取结果）。
- 但 `model_output.preview.diff` 写 `{"field":"title","before":"民宿房费","after":"民宿房费"}`——**before 值与读取结果不符，且被标为"未变化"**。
- 后果：该提案在保持金额修改的同时会把账目标题从"周末民宿"静默改成"民宿房费"，而预览声称标题不变。这正是 D4 "完整 before/after" 要防的错误。
- 同记录的 `expected_diff` 缺少 `title` 项，与 `preview.diff` 不等（见 §4.3）。

**等级 BLOCKER**：Ground Truth 的 diff 自身错误，且模型输出即训练目标。

### 4.3 MAJOR：`expected_diff` 与 `preview.diff` 不一致，且 Validator 对 Scenario **从不检查**该项

| 记录 | `preview.diff` | `expected_diff` | 判定 |
| --- | --- | --- | --- |
| 020 | 4 项：`title` 西门停车费→东门停车场，`original_amount`/`payments`/`manual_splits` 均 90→90（与用户"金额和分摊不变"一致） | **上一轮遗留的 `original_amount` 100→120 等 3 项** | **矛盾**：注解与模型输出、与用户请求都不符 |
| 018 | 4 项（含 title） | 3 项（无 title） | **不一致** |
| 001 / 012 / 019 / 026 | 有 diff | **缺 `expected_diff`** | 注解缺失（MINOR） |

**根因（精确）**：`validate_scenario` 调用 `_validate_output(..., expected_diff=未传)`，而 `_validate_output` 的两个相关判定分别是 `if expected_diff is not None and output.preview.diff != expected_diff`（跳过）与 `if path.startswith("/expected/")`（Scenario 路径为 `/ground_truth/model_output`，不匹配）。**因此 Dataset Validation Rules §4.2（`expected_diff` 必须与 `proposal.preview.diff` 深度相等）与 §11（D4 必须有 `expected_diff`）对 Canonical Scenario 完全未被执行**——它们只在 Sample 路径生效（`validator.py` 第 519 行）。这解释了为什么 018/020 的矛盾能以 0 error 通过。

### 4.4 MAJOR（单条）：`scenario_gs_p0b_023` 的 UI 上下文与家族及其自身话语都不符

- 家族 `ICTX-006` 的 `ui_context` 要求是 **`expense_form`**，家族定义为"草稿看似填满，但财务字段只有 `ui_default`"，即需要记录一份带 `field_sources=ui_default` 的**未提交表单草稿**。
- 记录的 `ui_context` 却是 `page_type=expense_detail`、`route=normal_activity`、`form_mode=view`（只读详情页），且**没有记录任何 draft / field_sources**。
- 而它的 `user_message` 写"表单里现在默认我付款、大家AA，但我还没过选"——用户在描述一个带默认值的**表单**，与记录页面矛盾。
- 金标澄清本身是正确且安全的（"页面上的付款人和AA方式都只是默认值，请明确…"，符合 P7），但支撑它的上下文事实不成立。

### 4.5 MAJOR：5 条记录的 `ui_context` 使用了非冻结枚举值

| 记录 | 字段 | 记录值 | 冻结枚举 |
| --- | --- | --- | --- |
| 004、017、019、023 | `form_mode` | `"view"` | `create / edit / refund / transfer / receive / fund / return`（只读页应为 `null`） |
| 011 | `page_type` | `"prepayment_form"` | `prepayment`（Context Envelope 为封闭枚举，无该值） |

这两处在 Scenario 的 `state.facts` 里是自由 JSON，故 Validator 放行；但 Sample 的 `input` 必须直接通过 Context Envelope Schema，**这些值一旦被继承到 Sample 会直接被 Schema 拒绝**。属"前向破损"，须在生成 Sample 前修正。

### 4.6 MINOR

| 项 | 数量 | 说明 |
| --- | ---: | --- |
| 断言骨架重复 | **26 条** | `"本轮用户原话为<Q>，回答不得增加这句话未提供的资金事实。"` 每记录占 2 条断言中的 1 条。每条都用自己的话语实例化、可判定，故非上轮 RC-4；但一半的断言额度是通用护栏而非场景特有命题。Validator 的批次归一化只去 family 名/标题、不去引号内容，因此抓不到 |
| `ui_context.route` 与 `page_type` 不匹配 | 6 条（004、005、017、018、019、023） | 记 `route="normal_activity"` 而 `page_type="expense_detail"`；Contract §7 中 expense_detail 的 route 为 `expense-detail/{expenseId}` |
| 缺 `expected_diff` | 4 条（001、012、019、026） | 非 D4 提案，法无明文强制，但削弱审计（P0-A 全部提案都有） |

### 4.7 未发现的问题（明确记录，避免夸大）

- **无真正重复**：5 个粗粒度指纹簇（001↔026、003↔023、018↔020、033–036、037–039）经逐条比对后均为**指纹粒度不足造成的假阳性**——001（自付自担零债务，manual）与 026（我与林两人 AA）业务形状不同；003（错别字噪声→缺 payer）与 023（ui_default→缺 payer+参与人+分摊，且记录 `ui_context`）不同；033–036 是四条不同规则、037–039 是三个不同错误，答案内容各异。**无 `NEAR_DUPLICATE_FAMILY`。**
- **无模型自行计算账务**：所有规则/解释类金标均绑定已记录读取结果，`evidence_result_ids` 与 `result_id` 逐条一致。
- **无 Pending Policy 违规**、**无聊天文字当授权**、**无 L1/L2/D4 确认语义错误**（8 条 proposal：L1 6 / L2 2；D4 三条 `execution_allowed=false` + `reason=d4_atomic_update_not_supported` + 无成功标签；全部 `final_authorization=trusted_ui_event_required`）。
- **无幽灵实体、无声明但无路径的 Tool、无 ground_truth 参数无来源**。

## 5. 逐条复审表（39/39）

| # | scenario_id | family_id | output | 二审发现（MAJOR/BLOCKER） | MINOR | verdict | severity |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `scenario_gs_p0b_001` | `EXP-CREATE-005` | `proposal` | 无 | 缺 expected_diff（MINOR） | **PASS** | — |
| 2 | `scenario_gs_p0b_002` | `EXP-CLARIFY-002` | `clarification` | 无 | — | **PASS** | — |
| 3 | `scenario_gs_p0b_003` | `EXP-CLARIFY-007` | `clarification` | 无 | — | **PASS** | — |
| 4 | `scenario_gs_p0b_004` | `EXP-EDIT-003` | `proposal` | ui_context.form_mode='view' 非冻结枚举 | ui_context.route 与 page_type 不匹配（MINOR） | **REVISE** | MAJOR |
| 5 | `scenario_gs_p0b_005` | `EXP-EDIT-004` | `proposal` | ground_truth 残留 Matrix 标题 | ui_context.route 与 page_type 不匹配（MINOR） | **REVISE** | MAJOR |
| 6 | `scenario_gs_p0b_006` | `EXP-READ-001` | `tool_call` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id | — | **REVISE** | MAJOR |
| 7 | `scenario_gs_p0b_007` | `ACT-002` | `tool_call` | ground_truth 残留旧 result_id | — | **REVISE** | MAJOR |
| 8 | `scenario_gs_p0b_008` | `DEBT-002` | `tool_call` | ground_truth 残留旧 result_id | — | **REVISE** | MAJOR |
| 9 | `scenario_gs_p0b_009` | `PRE-CORE-003` | `answer` | ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |
| 10 | `scenario_gs_p0b_010` | `TRF-002` | `answer` | ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |
| 11 | `scenario_gs_p0b_011` | `PRE-GATED-004` | `clarification` | ui_context.page_type='prepayment_form' 非冻结枚举 | ui_context.route 与 page_type 不匹配（MINOR） | **REVISE** | MAJOR |
| 12 | `scenario_gs_p0b_012` | `REF-001` | `proposal` | 无 | 缺 expected_diff（MINOR） | **PASS** | — |
| 13 | `scenario_gs_p0b_013` | `REF-002` | `clarification` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id | ui_context.route 与 page_type 不匹配（MINOR） | **REVISE** | MAJOR |
| 14 | `scenario_gs_p0b_014` | `FIN-001` | `tool_call` | ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |
| 15 | `scenario_gs_p0b_015` | `FIN-002` | `clarification` | 无 | ui_context.route 与 page_type 不匹配（MINOR） | **PASS** | — |
| 16 | `scenario_gs_p0b_016` | `DEL-002` | `answer` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |
| 17 | `scenario_gs_p0b_017` | `UI-001` | `answer` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id；ebr lookup 与 state 不一致；ui_context.form_mode='view' 非冻结枚举 | ui_context.route 与 page_type 不匹配（MINOR） | **REVISE** | MAJOR |
| 18 | `scenario_gs_p0b_018` | `UI-002` | `proposal` | expected_diff≠preview.diff；diff 的 title.before 与已验证读取矛盾（会使提案静默改名） | ui_context.route 与 page_type 不匹配（MINOR） | **REJECT** | BLOCKER |
| 19 | `scenario_gs_p0b_019` | `UI-003` | `proposal` | ui_context.form_mode='view' 非冻结枚举 | 缺 expected_diff（MINOR）；ui_context.route 与 page_type 不匹配（MINOR） | **REVISE** | MAJOR |
| 20 | `scenario_gs_p0b_020` | `ICTX-001` | `proposal` | expected_diff≠preview.diff | — | **REVISE** | MAJOR |
| 21 | `scenario_gs_p0b_021` | `ICTX-002` | `clarification` | 无 | — | **PASS** | — |
| 22 | `scenario_gs_p0b_022` | `ICTX-003` | `answer` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |
| 23 | `scenario_gs_p0b_023` | `ICTX-006` | `clarification` | page_type=expense_detail 与家族(expense_form)及话语不符；ui_context.form_mode='view' 非冻结枚举 | ui_context.route 与 page_type 不匹配（MINOR） | **REVISE** | MAJOR |
| 24 | `scenario_gs_p0b_024` | `ENT-002` | `clarification` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id | — | **REVISE** | MAJOR |
| 25 | `scenario_gs_p0b_025` | `ENT-003` | `clarification` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |
| 26 | `scenario_gs_p0b_026` | `CONV-001` | `proposal` | 无 | 缺 expected_diff（MINOR） | **PASS** | — |
| 27 | `scenario_gs_p0b_027` | `CONV-004` | `answer` | 无 | — | **PASS** | — |
| 28 | `scenario_gs_p0b_028` | `CONV-006` | `tool_call` | ground_truth 残留旧 result_id | — | **REVISE** | MAJOR |
| 29 | `scenario_gs_p0b_029` | `CONV-007` | `answer` | 无 | — | **PASS** | — |
| 30 | `scenario_gs_p0b_030` | `CLR-001` | `clarification` | 无 | — | **PASS** | — |
| 31 | `scenario_gs_p0b_031` | `CLR-002` | `clarification` | 无 | — | **PASS** | — |
| 32 | `scenario_gs_p0b_032` | `CLR-005` | `clarification` | 无 | — | **PASS** | — |
| 33 | `scenario_gs_p0b_033` | `RULE-001` | `answer` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |
| 34 | `scenario_gs_p0b_034` | `RULE-003` | `answer` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |
| 35 | `scenario_gs_p0b_035` | `RULE-004` | `answer` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |
| 36 | `scenario_gs_p0b_036` | `RULE-005` | `answer` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |
| 37 | `scenario_gs_p0b_037` | `RULE-006` | `answer` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |
| 38 | `scenario_gs_p0b_038` | `RULE-007` | `answer` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |
| 39 | `scenario_gs_p0b_039` | `RULE-008` | `answer` | ground_truth 残留 Matrix 标题；ground_truth 残留旧 result_id；ebr lookup 与 state 不一致 | — | **REVISE** | MAJOR |

**统计**：`PASS` **12** ／ `REVISE` **26** ／ `REJECT` **1**；BLOCKER **1**（018），MAJOR **26**，MINOR 若干（§4.6）。

## 6. FIN-002 专项裁决：**推荐 B**

三种处理的评估：

| 选项 | 评估 | 结论 |
| --- | --- | --- |
| **A. 当前就能合法构造** | 仓库内无 AI Gateway、无 `get_final_settlement` 的运行结果、也无任何捕获到的 Gateway 绑定 `suggestion_id`；BUSINESS_LOGIC §14 要求执行的是"服务端当前生成的完整建议"并复核 `financial_version`，Contract 与 Catalog 都不允许从聊天文本推导或自行重算建议标识。要"合法构造"只能伪造结果，这被明确禁止 | **不可行** |
| **B. 保留 Canonical Scenario，但在 Gateway 实现前排除出 Gold Sample** | 该记录已被重写为一个**合法且更安全**的金标：`ebr.blocked_by="GOLD_SEED_BLOCKER-FIN-002"`、`final_settlement_suggestion=null (missing)`、`ui_context.suggestion_state="not_loaded"`、金标为"没有可核对的服务端建议时只澄清、不编造双方/金额/币种/版本/suggestion_id"。它教的正是"不要凭聊天或记忆补出 L2 资金操作的目标"这一高风险行为。且机制上已被排除：`trust=SYNTHETIC_UNVERIFIED` + `split=unassigned`（Dataset Schema §14、Validation Rules §14 与 Exporter 规则都禁止此类记录进入正式导出） | **推荐** |
| **C. 当前 Scenario 本身应重设计** | 记录已重设计过一次，形态正确、语义安全，没有需要再改的业务错误；真正缺的是**家族的另一分支**（真正的 L2 proposal），而它缺的原因是不可构造，不是设计错误 | **不需要** |

**建议**：维持 B，并在文档中把"FIN-002 的 proposal 分支"显式登记为待 Gateway 落地后新增的**独立记录**（不是修改本条），使 `FIN-002` 家族的 proposal 形状有明确归属。**不要伪造 `suggestion_id` 或虚构 Gateway 结果。**

## 7. P0-A 回归与降级评估

**（a）三条降级记录（001 / 002 / 013）的降级合理，确认维持。**

- 三者现均为 `SILVER / draft / business_validated=false`，`review_notes` 记明"authenticity preflight found citation/entity defects, downgraded pending correction and re-review"。
- 复核其真实状态：**001/002 的 evidence_refs 已修好**（现指向 `BUSINESS_LOGIC.md#L66` 的 Expense 事实规则正文与 Matrix family 行，非标题），因此它们**通过**新的内容闸门；013 的引用指向 §19 幂等/Gateway 边界、Contract §3 工具边界，亦为实质内容。
- 但它们仍有上轮遗留的接地缺口：**001 的 `recorded_facts` 只有 `user_message` 一项**（金额 90、付款人、参与人、分摊方式均无逐项来源）；**013 完全没有 `recorded_facts` 条目、没有 `user_message`**，即没有可追溯的规范用户话语。降级为 SILVER 待修是正确且保守的判断。
- **需要指出**：降级说明里"citation/entity defects"的理由对 001/002 已过时（引用已修），其真正待修项是 **recorded_facts 覆盖**与复审；013 的待修项是**补记 user_message**。

**（b）批次自述未覆盖的一个事实：P0-A 整体现在不通过离线闸门。**

对 P0-A 15 条逐条运行 Validator：**28 个 ERROR，12 条记录不通过**（003、004、005、006、007、008、009、010、011、012、014、015；只有 001、002、013 通过）。错误码分布：

| 错误码 | 数量 | 含义 |
| --- | ---: | --- |
| `SCENARIO_ENTITY_UNUSED` | 13 | 声明的实体未被任何业务事实/参数/输出引用（幽灵实体） |
| `EVIDENCE_REF_LOW_QUALITY` | 9 | 引用行是 Markdown 标题或 JSON 分隔符 |
| `SCENARIO_BUSINESS_META_TEXT` | 4 | 业务标题/查询含 `→`、`L1/L2/D4`、`proposal` 等流程术语 |
| `SCENARIO_CONTEXT_TAG_STATE_MISMATCH` | 2 | 008 声明 `interaction_context`/`conversation_context` 但无对应事实 |

也就是说：**新闸门只对重写过的 P0-B 生效，P0-A 未同步**。因此**合并的 54 条语料目前不是"全部通过"状态**。这不改变 P0-A 已降级的结论，但意味着在进入 Sample 阶段前，P0-A 必须按同一 Content Authenticity 标准补齐（工作量与 P0-B 的修复同量级，且其中"幽灵实体/标题行引用"是纯机械修复）。

## 8. 系统性判断：是否出现新的系统性生产问题？

**没有出现上一轮那种方法级、会污染整批的系统性问题。** 判据：

1. **上一轮的 9 类根因全部关闭且可复现**（§3），且新闸门是**真的在拦**——P0-B 39/39 干净的同时，P0-A 未重写的 12 条被拦下 28 处，说明闸门有效而非摆设。
2. **本轮 27 条被标记的记录中，23 条同源于一个原因**（`expected_business_result` 未随重写更新）。这是一个**被遗漏的兄弟对象**，而不是方法本身错误：规则要求"输出面向用户、业务标题不含流程术语、evidence 有内容"，重写落实到了 `state` 与 `model_output`，只是没扫到同一个 `ground_truth` 下的注解对象。
3. **剩余问题全部是机械可检出的**：018 的 before 值不一致、020 的 expected_diff 陈旧、5 处非冻结枚举、6 处 route 不匹配、26 条断言骨架——每一项都能被一条确定性检查或一次字段级替换修复，不需要重新设计任何业务语义。业务判断（澄清必要性、L1/L2/D4、授权、不脑补、不计算）本批**没有发现错误**。
4. **两处闸门漏洞必须补**，否则同类残留会在下一批重现：
   - `_validate_scenario_authenticity` 必须把 `ground_truth.expected_business_result` 纳入扫描（元文本、旧 result_id、与 state 的 lookup 一致性）；
   - `validate_scenario` 必须把 `expected_business_result.expected_diff` 传给 `_validate_output`，使 §4.2 与 §11 的相等性/必填检查对 Scenario 生效；
   - 建议追加：`state.facts.ui_context` 的 `page_type` / `form_mode` 必须落在 Context Envelope 的冻结枚举内（或为 `null`）。

## 9. 结论

### 9.1 统计

| 项 | 数量 |
| --- | ---: |
| 复审 Scenario | **39 / 39** |
| `PASS` | **12**（001、002、003、012、015、021、026、027、029、030、031、032） |
| `REVISE` | **26**（004、005、006、007、008、009、010、011、013、014、016、017、019、020、022、023、024、025、028、033、034、035、036、037、038、039） |
| `REJECT` | **1**（018） |
| BLOCKER | **1**（018，记录级） |
| MAJOR | **26**（23 条为批次级注解残留，2 条为 018/020 的 diff 问题，1 条为 023 的页面上下文；5 条非冻结枚举含于其中） |
| MINOR | 断言骨架 26 条、route 不匹配 6 条、缺 `expected_diff` 4 条 |
| 建议 `APPROVE_AS_GOLD` | **0**（本批全部仍须修订；不因本轮复审升级任何记录） |
| 建议 `KEEP_SILVER` | **39** |

### 9.2 仍需修改的 Scenario

**须先修（阻塞级）**
- `scenario_gs_p0b_018`（`UI-002`）：修正 `preview.diff` 的 `title.before`，使其等于 `verified_read_result.expense.title`（`"周末民宿"`）；若确实要改标题，则 before/after 如实反映，否则删除该 diff 项。

**须随批修复（MAJOR）**
- **21 条**（005、006、007、008、009、010、013、014、016、017、022、024、025、028、033、034、035、036、037、038、039）：重写 `expected_business_result.supporting_lookup`，使其与 `state.facts.supporting_lookup_result` 完全一致（同一 `query`、同一 `result_id`），并清除注解中残留的 Matrix 标题与旧 `result-p0b-*` id。
- `scenario_gs_p0b_020`（`ICTX-001`）：`expected_diff` 改为与其 `preview.diff` 深度相等（标题单项变更，金额/分摊 90→90 不变）。
- `scenario_gs_p0b_023`（`ICTX-006`）：把 `ui_context` 改为 `page_type=expense_form` 并记录带 `field_sources=ui_default` 的草稿事实，使其与家族及自身话语一致。
- `scenario_gs_p0b_004 / 011 / 017 / 019 / 023`：`form_mode="view"` → `null`；`011` 的 `page_type="prepayment_form"` → `prepayment`。
- **P0-A 的 12 条**：按同一 Content Authenticity 标准补齐（13 处幽灵实体、9 处标题行引用、4 处业务标题流程术语、008 的 2 处 context 标签无事实）。

**建议修（MINOR）**：26 条通用断言骨架替换为场景特有命题；6 处 `route` 与 `page_type` 对齐；4 条补 `expected_diff`。

### 9.3 是否存在 `GOLD_SEED_BLOCKER`

```text
GOLD_SEED_BLOCKER-P0B-01（数据级，上一轮）  → 已解除
GOLD_SEED_BLOCKER-P0B-02（方法级，上一轮）  → 已解除

GOLD_SEED_BLOCKER-FIN-002（既有，维持开放）
  性质不变：`execute_final_settlement` 需要 Gateway 绑定的真实 suggestion_id，
  仓库无可合法引用的运行结果。处置按 §6 采用 B（保留 Scenario，排除出 Gold Sample）。
  该 blocker 不阻塞其余记录的 Sample 生产，但应保持显式登记。
```

**本轮未新增 `GOLD_SEED_BLOCKER`。** 018 是记录级 BLOCKER（须改后才能进入 Gold Seed），不构成批次级 blocker；批次级残留（§4.1）定为 MAJOR。

### 9.4 P0-Gold-Sample 准入判断

```text
NOT_READY_FOR_P0_GOLD_SAMPLE
```

**判定依据**：①存在 1 条记录级 BLOCKER（018 的 D4 diff 与其自身已验证读取矛盾，会教出错误的 before 值并静默改名）；②26 条 MAJOR 中 21 条同源于 `expected_business_result` 未更新，而该注解会在 Sample 阶段被继承为交叉校验目标；③5 处非冻结 `ui_context` 枚举值会在 Sample 阶段直接触发 Context Envelope Schema 拒绝；④P0-A 整体 28 处 ERROR 未修，合并语料并非"全部通过"。

**为什么仍给出"接近就绪"的判断**：上一轮的 9 类系统性根因已全部关闭且机器可复现；本轮问题全部是机械可检出、字段级可修复的残留，业务判断维度（澄清必要性、L1/L2/D4、授权语义、不脑补、不自算、tool 路径、context 证据）**没有发现错误**。修复清单短且明确。

**建议的解除顺序（三项，均不需修改冻结资产）**：
1. **先补两处闸门**：`_validate_scenario_authenticity` 纳入 `expected_business_result`；`validate_scenario` 把 `expected_diff` 接入 `_validate_output`（并可加 `ui_context` 枚举校验）。
2. **再修数据**：018（BLOCKER）→ 020 → 21 条注解残留 → 5 处枚举 → P0-A 的 12 条 → MINOR 项。
3. **重跑**：P0-A + P0-B 逐条 Validator + 单测 + 独立业务复审；确认 54 条全部 `0 error` 后再评估是否将具备条件的记录升 GOLD。

完成上述后，`READY_FOR_P0_GOLD_SAMPLE`（FIN-002 按 §6 以 B 处理、继续排除）是可以达成的；本报告不建议在完成前进入 Sample 生产。

### 9.5 本轮边界

未生成任何 Sample；未调用 DeepSeek 或任何模型 API；未修改 `scenarios.json`（P0-A / P0-B）、Contract、AI Scope、Catalog、Model Output Schema、Dataset Schema、Validation Rules、Coverage Matrix、Validator、业务逻辑、Android、RPC、数据库；未提交 Git。本报告是本轮**唯一新增文件**。
