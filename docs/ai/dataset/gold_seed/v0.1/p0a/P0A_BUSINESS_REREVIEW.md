# P0-A Canonical Scenario 修订后二次独立审核报告

> 状态：**SECOND INDEPENDENT BUSINESS REVIEW — 只读复审**。本轮不生成 Scenario / Sample，不调用 Teacher，不修改 `scenarios.json`、Contract、Scope、Catalog、Model Output Schema、Dataset Schema、Validation Rules、Coverage Matrix、Validator、业务逻辑、Android、RPC、数据库，不开始 P0-B。
> 复审对象：`docs/ai/dataset/gold_seed/v0.1/p0a/scenarios.json`（15 条）、同目录 `README.md`、`P0A_BUSINESS_REVIEW.md`（上轮报告）、`docs/ai/dataset/GOLD_SEED_COVERAGE_MATRIX_V0.1.md`。
> 版本基线：BUSINESS LOGIC `1.2` / AI Contract `0.1.2` / AI Scope `0.1` / Dataset `0.1`；冻结 SHA `55fb28a7c0660462e5842e2eb5c71cfa763e5801`。

## 1. 复审方法

1. **先独立复现机器结论**（不采信批次自述）：逐条重跑 Offline Validator、跑 Validator 单测、跑 examples validator；并自建脚本复核实体引用完整性、`operation` 与 `state` 参数一致性、冻结词表、`recorded_facts` 结构与去重、断言唯一性、lookup 结果覆盖。
2. **逐条回到文件**核对上轮 3 个 BLOCKER、9 个 MAJOR、7 个 MINOR 与 5 类系统性发现的关闭情况；**逐项打开 evidence 目标行**确认其内容确实支持所引结论（不只看能否解析）。
3. **专门寻找整改引入的新错误**（重复条目、未更新的镜像字段、遗漏的实体声明、被替换掉的覆盖分支）。

## 2. 机器复核结果（本轮独立执行，全部可复现）

| 检查 | 结果 |
| --- | --- |
| Offline Validator（逐条 15 条） | **15/15，0 error，0 warning** ✓ 与批次自述一致 |
| Validator 单测 | **27/27 OK** ✓ 与批次自述一致 |
| examples validator | **PASS** ✓ |
| 新增的 evidence-reference 校验 | **存在且有效**：`validator.py:_evidence_references` 对空值、越界行号、无法解析的 JSON Pointer 抛 `EVIDENCE_REF_UNRESOLVED` |
| `trust.evidence_refs` 可解析性（自建脚本 + 人工抽验目标行） | **15/15 全部可解析，且目标内容确实支持结论**（例：`BUSINESS_LOGIC.md#L64` = "## 6. Expense、Payment 与 Split"；`tool_catalog.json#L12728/14265/16148` = `get_expense`/`delete_expense`/`get_prepayment_accounts` 条目） |
| Tool 角色合法性 | **0 越权** |
| `deterministic_assertions` 唯一性 | **15/15 互不相同**，模板化已消除 |
| `state.facts.recorded_facts` 结构 | **13/15 采用新结构且每条均为 `{field,value,source}`**；001/002 的旧式最小状态与 013/014 的 4 键状态均无扩展字段，不违反"扩展必须用 recorded_facts"的规则 |
| `recorded_facts` 来源值合法性 | 全部取自约定集合（`user_input` / `user_selected` / `ui_context` / `server_result` / `missing` / `stale_context`） |
| Coverage Matrix 过期注记（上轮 §5.5） | **已修正**：`EXP-CLARIFY-002` 家族说明已改为"`create_expense` 的 Catalog 映射明确允许 `find_participants` 作为 read/L0 SUPPORTING_LOOKUP" |
| 生产规则落文 | README 新增 5 节（State Recording Contract / Coverage reconciliation / Frozen vocabulary / Resolvable evidence references / Scenario-specific assertions）+ 7 条 preflight 自检 |
| 治理状态 | 001/002/013 = `GOLD` / `reviewed` / `business_validated=true`；其余 12 条 = `SILVER` / `draft` / `business_validated=false` ✓ 符合批次自述 |

## 3. 上轮发现的关闭情况

### 3.1 BLOCKER（3/3 全部关闭）

| ID | Scenario | 上轮问题 | 复核证据 | 结论 |
| --- | --- | --- | --- | --- |
| B-01 | 003 | 金标 question 引用"60 CNY 的桌游费用"，但全记录无金额/标题来源 | `recorded_facts` 现记录 `title=桌游`、`original_amount=60`、`original_currency=CNY`、`occurred_at`、`payer=null(source=missing)`，并含 `user_message`；`original_currency` 明确标为 `user_input`，同时消解了上轮"币种可能来自默认预填"的 P8 疑虑 | **CLOSED** |
| B-02 | 009 | D4 diff 只列 `original_amount`，漏掉必然变化的 `payments`/`manual_splits`；且 `get_expense` 声明未执行、pre-state 不可追溯 | `state.facts.verified_read_result` 现记录 `get_expense` 的 `arguments`、`result_id=result-p0a-expense-009`、`financial_version=11` 与完整当前支出（100 CNY、payments 100、splits 100、`financial_locked`、`version`、`is_deleted`）；`preview.diff` 与 `expected_diff` 现为 3 项（`original_amount`/`payments`/`manual_splits`，均 100→120），实测深度相等，守恒成立；D4 五项硬约束仍全部正确 | **CLOSED** |
| B-03 | 012 | title/description 讲 `create_refund` 而 intent/scope/GT/README 讲 `delete_expense`；lookup query 是占位串；DEL-001 家族主形状未落地 | 已重写为 `scenario_gs_p0a_012`「删除唯一定位的本人未锁定支出需 L2 提案」：title/description/intent/scope/GT/README 六处一致指向 `delete_expense`；query 改为真实检索串"设备租赁"；输出 `preview.kind=delete` 的 L2 单提案（diff 只含 before，符合 DEL-001 家族说明）；`find_expenses` 唯一命中且服务端结果显示 `financial_locked=false`/`is_deleted=false` | **CLOSED** |

### 3.2 MAJOR（9 条：8 条关闭，1 条部分关闭）

| ID | Scenario | 上轮问题 | 本轮复核 | 结论 |
| --- | --- | --- | --- | --- |
| M-01 | 004 | `reason` 应为 `needs_explicit_financial_choice` | 现为 `needs_explicit_financial_choice`，`missing_fields=["split_method"]` | **CLOSED** |
| M-02 | 004 | `occurred_at` 无来源却断言"只缺 split_method" | `recorded_facts` 现记录 `occurred_at=2026-09-21T19:30:00+08:00 (user_input)` | **CLOSED** |
| M-03 | 005 | state 只记检索串，付款人角色与已给字段无来源 | `recorded_facts` 现记录 `original_amount=300`、`split_method=aa`、`payer=张伟`、`occurred_at`、`title`、`user_message` | **CLOSED** |
| M-04 | 006 | intent 与冻结家族冲突（应 `find_expenses`） | 现为 `intent_ids=["find_expenses"]`，且候选带 `occurred_at`/`original_amount`，改为按金额区分同日两笔（比上轮按日期更严格） | **CLOSED** |
| M-05 | 007 | UI 家族无 UI 事实；`interaction_context` 标签无对应事实 | `state.facts.ui_context` 现含 `page_type=expense_detail`/`screen_instance_id`/`selected_entity`；`rule_tags` 已移除 `interaction_context` | **CLOSED** |
| M-06 | 008 | `missing_fields=["current_form_instance"]` 非业务字段 | 现为 `["original_amount","payments"]`；`state.facts` 补 `ui_context` 与 `page_state`（含 `draft` 与 `draft_field_sources`） | **CLOSED**（但引出 N-01） |
| M-07 | 011 | diff 使用非冻结字段 `transfer.status` | `preview.diff`/`expected_diff` 现为 `is_voided` false→true 与 `void_reason`；`state.supporting_lookup_result` 亦改为 `is_voided` + `result_id` + `arguments` | **部分关闭**：`expected_business_result.supporting_lookup` 仍保留 `"status": "active"`（见 N-06） |
| M-08 | 015 | `operation.tool_id` 与 `arguments` 不匹配 | `tool_id` 现为 `get_participant_balance`，参数与之匹配；`state.facts.verified_read_results` 记录两次读取各自的参数与 `result_id` | **CLOSED** |
| M-09 | 015 | canonical world 缺 Custodian，20 CNY 预存无来源 | `get_prepayment_accounts` 结果现含 `custodian_participant_id=P002` 与账户 id，`balance=20 CNY` 有可达来源 | **CLOSED** |

### 3.3 MINOR 与系统性发现

| 上轮项 | 复核 | 结论 |
| --- | --- | --- |
| 001 lookup query 未记入 state | `supporting_lookup_result` 现含 `query="李四"` 与 `source="server_result"` | **CLOSED** |
| 013 assertions 模板化 | 现为 2 条场景特有断言 | **CLOSED** |
| 014 与 `DEBT-001` 家族行的分页子分支未兑现 | README 与本记录断言均**显式声明**只覆盖 `query_debt → get_debt` 主分支，不声称覆盖并入的 DEBT-010 分页分支，并把 Matrix/Catalog 差异留作审核发现 | **CLOSED（按我的建议方式）** |
| S-01 State Recording | 规则落文；13/15 记录采用 `recorded_facts` 并带来源 | **CLOSED（方法层）** |
| S-02 Coverage reconciliation | 规则落文；004/006/012/014 实际对账 | **CLOSED** |
| S-03 Frozen vocabulary | 规则落文；绝大部分已改正，008 的 `operation.arguments` 与 011 的 ebr 仍有残留 | **基本关闭**（见 N-01、N-06） |
| S-04 evidence 不可解析 | 规则落文 + Validator 新增强制校验 + 15/15 可解析且目标切题 | **CLOSED（closure 最彻底的一项）** |
| S-05 assertion 模板化 | 规则落文；15/15 断言唯一；断言改为场景特有 | **CLOSED（方法层）**，但 011/006 各有一条断言自身不成立（见 N-06、N-07） |
| Coverage Matrix `EXP-CLARIFY-002` 过期注记 | 已改写为符合 v0.1.2 的表述 | **CLOSED** |

## 4. 逐条复审表（15/15）

| scenario_id | family | verdict | severity | 关键复核点 | required_change |
| --- | --- | --- | --- | --- | --- |
| `scenario_gs_p0a_001` | EXP-CREATE-001 | **PASS** | — | BLOCKER 无；lookup query 与 user_message 已入 state；断言场景特有；evidence 切题；L1 正确 | 无（GOLD 维持） |
| `scenario_gs_p0a_002` | EXP-CREATE-002 | **PASS** | MINOR | GOLD 维持；沿用最小 4 键 state + `user_message` | MINOR：与 001 统一"参与人解析来源"的记录方式（002 未记录 participant 来源） |
| `scenario_gs_p0a_003` | EXP-CLARIFY-001 | **PASS** | — | BLOCKER 已关闭；金额/标题/币种/时间/参与人均有来源，currency 明确为用户输入；payer 标 `missing` | 无，建议 `APPROVE_AS_GOLD` |
| `scenario_gs_p0a_004` | EXP-CLARIFY-003 | **PASS** | MINOR | MAJOR 全部关闭；`reason` 已对账；`occurred_at` 有来源 | MINOR：`aa_participant_ids` 以 `user_input` 记录，但 `split_method` 仍为 `missing` —— 该字段名自带 AA 承诺，建议改用中性表述或在记录中注明"参与名单，非 AA 选择" |
| `scenario_gs_p0a_005` | ENT-001 | **PASS** | MINOR | 付款人角色与已给字段均有来源；候选与 lookup 一致；`expected_entity_id=null` | MINOR：`recorded_facts` 有 **5 组完全重复条目**（12 条 = 6 条唯一），见 N-04 |
| `scenario_gs_p0a_006` | EXP-READ-002 | **PASS** | MINOR | intent 已对账；同时候选带金额，消歧更强 | MINOR：description 写"昨天的火锅"、`user_message` 写"这两天"，而断言声称"按 2026-09-12 自然日"查询，但 `operation.arguments` 只有 `{activity_id, query}`（无 `from_time`/`to_time`），见 N-07 |
| `scenario_gs_p0a_007` | EXP-READ-003 | **PASS** | — | UI 上下文入 state；`interaction_context` 标签已移除；`lookup_required=false` 明确 | 无，建议 `APPROVE_AS_GOLD` |
| `scenario_gs_p0a_008` | ICTX-008 | **REVISE** | MAJOR | `missing_fields` 已改为业务字段；但 `operation.arguments` 未同步更新 | **N-01**：`operation.arguments` 仍用 `payer_participant_id`/`amount`/`currency`/`surface`，与同一记录的 `state.facts.operation_arguments`（`original_amount`/`original_currency`/`payments`/`page_type`）矛盾，违反本批新写的 Frozen vocabulary 规则 |
| `scenario_gs_p0a_009` | EXP-EDIT-001 | **REVISE** | MAJOR | BLOCKER 已关闭（diff 完整、pre-state 有来源、lookup 有结果）；D4 全对 | **N-03**：Proposal 的 `manual_splits` 指向 `…104`（P002），但 `state.entities` 未声明 P002 —— 输出为未声明实体分摊。**N-02**：`state.entities` 重复声明同一 id（E001 与 E009 均为 `…110`） |
| `scenario_gs_p0a_010` | PRE-GATED-001 | **PASS** | MINOR | `expected_financial_version` 现有 `financial_version_source`（server_result）；L2 正确 | MINOR：description 仍称"聊天同意不能执行登记"，但 state 无会话事实（断言已不依赖它，影响有限） |
| `scenario_gs_p0a_011` | TRF-007 | **REVISE** | MAJOR | diff 已改用 `is_voided` ✓ | **N-06**：①`expected_business_result.supporting_lookup` 仍带非冻结字段 `"status":"active"`；②`void_reason` 三处不一致（user_message"金额登记错误" / recorded_facts"登记金额错误" / args"登记金额录入错误"）；③断言称"void_reason 与用户提供的'登记金额错误'相同"，实测不成立 —— 断言自身为假 |
| `scenario_gs_p0a_012` | DEL-001 | **PASS** | MINOR | BLOCKER 已关闭；六处标签一致；query 真实；L2 删除提案落地 | MINOR：**N-05** 读取结果中的 P001/P002 未在 `state.entities` 声明；且 `operation.arguments`（delete 参数）与 `state.facts.operation_arguments`（lookup 参数）含义不一致，与 001/011 的约定（lookup 参数放 `supporting_lookup_result.arguments`）不统一 |
| `scenario_gs_p0a_013` | UNS-001 | **PASS** | — | 断言已场景特有；evidence 切题；unsupported 语义正确 | 无（GOLD 维持） |
| `scenario_gs_p0a_014` | DEBT-001 | **PASS** | — | reconciliation 已按显式限缩分支解决；断言场景特有 | 无，建议 `APPROVE_AS_GOLD` |
| `scenario_gs_p0a_015` | DEBT-004 | **PASS** | — | MAJOR 全部关闭；两次读取参数/结果/result_id 完备；答案逐项引用 | 无，建议 `APPROVE_AS_GOLD` |

## 5. 整改引入的新发现

| ID | Scenario | 严重度 | 问题 | 证据 | 建议 |
| --- | --- | --- | --- | --- | --- |
| N-01 | 008 | **MAJOR** | `operation.arguments` 未随 `state` 更新，两处对同一操作给出不同字段名与不同内容 | `operation.arguments.stale_draft = {…, payer_participant_id:…103, amount:"80", currency:"CNY"}`；`state…stale_draft = {…, original_amount:"80", original_currency:"CNY", payments:[{…103,"80"}]}`；`current_ui` 一处为 `surface`、一处为 `page_type` | 用与 `state` 相同的冻结字段名重写 `operation.arguments`（或在 `state` 中同步为旧名——不推荐）。这是 preflight 第 3 条本应拦下的机械 slip |
| N-02 | 009 | MINOR | 同一 id 被声明为两个 expense 实体 | `state.entities` 同时有 `E001/…110` 与 `E009/…110` | 保留一个别名 |
| N-03 | 009 | **MAJOR** | Proposal 的 `manual_splits` 把 120 分摊给 `…104`（P002），但 `state.entities` 未声明 P002 | `model_output.operation.arguments.manual_splits=[{…104,"120"}]`；entities 仅 A001/L001/U001/P001/E001/E009 | 在 `state.entities` 声明 P002（并核对是否同时需要声明其为李四） |
| N-04 | 005 | MINOR | `recorded_facts` 有 5 组完全重复条目 | 12 条记录中 `original_amount`/`original_currency`/`split_method`/`payer`/`occurred_at` 各出现 2 次且值相同 | 去重。属"用追加代替替换"的整改痕迹 |
| N-05 | 012 | MINOR | 读取结果引用的 P001/P002 未声明；`operation.arguments` 与 `state.operation_arguments` 含义不一致 | entities 仅 A001/L001/U001/E012；operation 为 `{activity_id, expense_id}`、state 为 `{activity_id, query}` | 声明两个参与人；把 lookup 参数移到 `supporting_lookup_result.arguments`（与 001/011 一致），使 `operation.arguments` 只表达删除操作 |
| N-06 | 011 | **MAJOR** | 非冻结字段残留 + 三处 `void_reason` 不一致 + **断言自身为假** | `ebr.supporting_lookup = {tool, transfer_id, status:"active"}`；`void_reason` 三值不一致；断言"void_reason 与用户明确提供的'登记金额错误'相同"与实际 `"登记金额录入错误"` 不符 | ①`ebr.supporting_lookup` 改用 `is_voided`；②统一三处 `void_reason`（建议直接用用户原话）；③修正断言 |
| N-07 | 006 | MINOR | description / `user_message` / 断言的查询范围表述互不一致，且断言声称的时间范围未被 `operation.arguments` 表达 | description"昨天的火锅"、`user_message`"这两天的火锅"、断言"按 2026-09-12 自然日"、`operation.arguments={activity_id, query}`（`find_expenses_input` 支持 `from_time`/`to_time` 但未使用） | 统一时间表述；若确实以自然日为界，把 `from_time`/`to_time` 写进 lookup 参数，否则删去断言中的范围表述 |
| N-08 | 批次级 | **MAJOR（覆盖）** | **零匹配路径在 P0-A 中失去代表记录**：原 012 承载的 `resolution="zero"` 分支在重写为 L2 删除提案后消失，现全批只有 unique（001/003/012）与 multiple（005/006），无 zero | 逐条扫描 `supporting_lookup_result.resolution`；README 亦不再声明零匹配分支 | 在 P0-B 中补一条零匹配代表记录（例如 `EXP-READ-002` 家族已声明的"零匹配 → 说明未找到"分支），或明确记录该分支顺延到 P0-B |

**关于 N-08 的说明**：这不是重写本身的错误——重写 012 解决了 B-03（DEL-001 主形状未落地）这一更严重的问题；但它在无提示的情况下吃掉了上一批唯一的零匹配样本，因此必须显式补回或显式顺延，否则该覆盖会静默丢失。

## 6. 系统性判断：上轮的生产方法问题是否已解决？

**结论：上轮的 5 类系统性生产方法问题已解决；本轮剩余的是个别数据 slip，不是方法问题。**

判据：

1. **规则已落文且可执行**：README 新增 5 节分别对应上轮 S-01 ~ S-05，并附 7 条 preflight 自检。规则本身与冻结 Contract/Schema 一致，不需要修改任何冻结资产。
2. **最硬的一项已被强制校验**：S-04（evidence 不可解析）现在既有规则、又有 Validator 的 `EVIDENCE_REF_UNRESOLVED` 强制检查，15/15 实测可解析且目标切题——这类问题不会再静默通过。
3. **上轮的方法级病灶已消除**：断言模板化消失（15/15 唯一）；记录与 family 的对账实际发生（004/006/012/014）；`recorded_facts` 带来源成为主流（13/15）。
4. **本轮 3 条 MAJOR 的性质**：N-01（镜像字段未同步）、N-03（实体未声明）、N-06（残留字段名 + 字符串不一致 + 断言失实）**全部是机械可检出的一致性 slip**，不是业务判断错误——三者的模型目标（clarification / D4 proposal / L2 void proposal）本身都正确，且都不改变任何资金语义。这与会话第一轮的性质（GT 引用无来源事实、标签互相矛盾、diff 违反守恒）有本质区别。
5. **可量化对比**：上一轮 11/15（73%）需改动，含 3 BLOCKER；本轮 3/15（20%）需改动，0 BLOCKER，且都不影响模型应学到的行为。

**但必须指出一个仍未被自动化的环节**：README 的 preflight 是**人工清单**。本轮 3 条 MAJOR 恰好都是清单第 3、7 条本应拦下的可机械判定项。若不做自动化，相同的 slip 会以约 3/15 的比率复制到剩余 39 个 family（约 8 条）。因此建议（非阻塞）为 preflight 增加 5 个确定性检查：①`operation.arguments` 与 `state.facts.operation_arguments` 逐字段一致；②所有被引用的实体（含输出参数与读取结果中出现的 id）均在 `state.entities` 声明且不重复；③`recorded_facts` 无重复条目、无未约定来源值；④全记录不含非冻结字段名；⑤`supporting_lookup_result.resolution` 覆盖 unique/multiple/zero。这 5 项都可离线判定，且都不需要改冻结 Schema。

## 7. 结论

### 7.1 统计

| 项 | 数量 |
| --- | ---: |
| 复审 Scenario | **15 / 15** |
| `PASS` | **12**（001、002、003、004、005、006、007、010、012、013、014、015） |
| `REVISE` | **3**（008、009、011） |
| `REJECT` | **0** |
| BLOCKER | **0**（上轮 3 个全部关闭） |
| MAJOR | **3** 记录级（N-01、N-03、N-06）+ **1** 覆盖级（N-08） |
| MINOR | **5**（N-02、N-04、N-05、N-07 + 002/004/010 的记录级小项） |
| 上轮 BLOCKER 关闭率 | **3/3 = 100%** |
| 上轮 MAJOR 关闭率 | **8/9 完全关闭，1/9 部分关闭（M-07 → N-06）** |
| 上轮系统性方法问题关闭 | **5/5 关闭**（S-04 另获 Validator 强制校验） |

### 7.2 GOLD 建议

**维持 GOLD（3 条）**：`scenario_gs_p0a_001`、`scenario_gs_p0a_002`、`scenario_gs_p0a_013`。
复核确认三者的模型目标与业务真值在本轮**未发生实质变化**（001 补了 lookup query 与 `user_message`、002 补了 `user_message`、013 把模板断言改写为场景特有断言），其 `GOLD / reviewed / business_validated=true` 状态**成立**。001 的两条 MINOR 已在整改中关闭；002 建议补齐参与人来源记录（MINOR，不改变 GOLD）。

**建议新增 `APPROVE_AS_GOLD`（9 条）**：`003`、`004`、`005`、`006`、`007`、`010`、`012`、`014`、`015`。
依据：业务 Ground Truth 明确、Context 自洽、Tool 路径合理、无 Pending Policy 依赖、无未解决歧义；各自仅存 1 条 MINOR 级元数据/措辞项，均不影响模型应学到的行为。
**这 9 条仍不由我升级**——`business_validated=true` 与 lifecycle 提升应在 Codex 的治理步骤中执行；且按 README「修订者不得把自己的修订标为已独立审核」，本轮复审记录可作为其独立审核依据。

**建议维持 `SILVER`（3 条）**：`008`、`009`、`011`，按 §5 的 N-01/N-03（+N-02）/N-06 修正后即可重新评估。

### 7.3 仍需修改的 Scenario 与原因

| Scenario | 等级 | 原因 |
| --- | --- | --- |
| `scenario_gs_p0a_008` | MAJOR | `operation.arguments` 使用非冻结字段名且与 `state` 矛盾（N-01） |
| `scenario_gs_p0a_009` | MAJOR | Proposal 向未声明实体 P002 分摊（N-03）；实体列表重复（N-02，MINOR） |
| `scenario_gs_p0a_011` | MAJOR | 残留 `status` 字段、`void_reason` 三处不一致、断言自身为假（N-06） |
| `scenario_gs_p0a_002` / `004` / `010` / `006` / `005` / `012` | MINOR | 分别为参与人来源未记录、`aa_participant_ids` 命名语义、description 提及未记录的 chat、时间表述与查询范围不一致、`recorded_facts` 重复、参与人未声明与参数约定位不统一 |

### 7.4 Scenario 014 reconciliation 结论

**已按上轮建议合理解决，无需进一步整改。** `DEBT-001` 家族行并入的 `find_expenses` 分页/截断子分支（来自 DEBT-010）在冻结 Catalog 中并未映射给 `query_debt`，因此记录不声明该 Tool 是**正确**的；README 与记录断言均已**显式声明**只覆盖 `query_debt → get_debt` 主分支，并把 Matrix/Catalog 的差异保留为审核发现，而不是用改写冻结映射的方式"修好"。这与"不得通过添加未授权 Tool 扩大 Scope"的原则一致。

### 7.5 是否出现新的 blocker

**无新的 `GOLD_SEED_BLOCKER`，也无新的记录级 BLOCKER。** 上轮 3 个 BLOCKER 全部关闭。本轮新增的 4 条 MAJOR 中，3 条为记录级一致性 slip，1 条（N-08）为覆盖缺口；均不涉及资金语义错误、不涉及脑补财务事实、不涉及把未授权 Tool 或聊天文字当授权。

### 7.6 P0-B 准入判断

```text
READY_FOR_P0B
```

**判定依据**：任务给定的门槛是"只有仍存在会复制到剩余 39 个 Family 的**生产方法问题**时才判 NOT_READY"。实测：①5 类系统性方法问题全部关闭，规则已落文，其中 evidence 解析更已获得 Validator 强制校验；②本轮 0 BLOCKER，3 条 MAJOR 全为机械可检出的记录一致性 slip，模型目标与资金语义均正确；③受影响的只有 3/15 条记录，且都不改变模型应学到的行为。

**同时给出两项非阻塞建议（建议与 P0-B 同批完成，但不构成准入门槛）**：

1. 修订 `008` / `009` / `011` 三条（外加 6 条 MINOR 清理），并补一条零匹配代表记录或在 P0-B 计划中显式顺延该分支（N-08）；
2. 把 preflight 的 5 个可机械判定项做成离线检查，避免约 3/15 的 slip 比率在剩余 39 个 family 上复制。

### 7.7 本轮边界

未开始 P0-B；未生成任何 Sample；未调用 DeepSeek 或任何模型 API；未修改 `scenarios.json`、Contract、AI Scope、Catalog、Model Output Schema、Dataset Schema、Validation Rules、Coverage Matrix、Validator、业务逻辑、Android、RPC、数据库；未提交 Git。本报告是本轮**唯一新增文件**。
