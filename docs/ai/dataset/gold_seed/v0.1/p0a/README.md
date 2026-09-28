# P0-A Canonical Scenario Batch (v0.1)

本目录包含 15 条合成 Canonical Scenario，不含语言 Sample 或 Teacher 输出。版本固定为 BUSINESS LOGIC 1.2、AI Contract 0.1.2、AI Scope 0.1、Dataset 0.1；所有记录 `split=unassigned`、`policy_status=active`。001、002、013 曾被标记为 GOLD/reviewed，真实性复核后已降为 `SILVER`、`business_validated=false`、`draft`；目前 15 条均为 SILVER/draft，没有 GOLD 记录。Scenario 的生产状态只由 `lifecycle.status` 表示。本批不生成 Samples、API/Teacher 输出或 Manifest，也不分配最终 split。P0-B 的 39 条 Canonical Scenario 独立记录在同级 `p0b/`，详见该目录 README。

## Canonical production method

### State Recording Contract

`state.facts` 只记录本轮可追溯的事实、来源及必要服务端读取结果。每个支撑业务判断的值必须能归到 `user_input`、`user_selected`、`ui_context`、`conversation_confirmed`、`persisted_entity` 或 `server_result`；缺失值可用 `missing` 标记，失效上下文可用 `stale_context` 标记。值缺失时明确记录对应正式字段名，不以页面默认、列表顺序、模型补全、当前时间或“合理值”替代。页面草稿只有在 `field_sources` 指明用户来源且 `screen_instance_id` 仍有效时才可用于业务参数。服务端账务结果需保留工具名、真实查询参数、`result_id`、完整影响判断的数据和版本；不得凭摘要补出读取字段。

### Coverage reconciliation

按稳定 `scenario_id` 和 `scenario_family_id` 查找记录，不用 JSON 数组序号定位。每次修订按以下顺序核对：Coverage Matrix Family 的目标与意图 → 最新 Intent Catalog 的 PRIMARY / SUPPORTING_LOOKUP → Tool Catalog 的 input/output 字段 → Contract 与规则中的决策边界 → Scenario state、operation、scope、ground truth 与 assertion。对 Family 的并列或合并分支，只记录本 Scenario 实际覆盖的分支；无法由冻结 Catalog 表达的差异写入审核发现，不通过添加未授权 Tool、改变 Intent 或扩大 Scope 解决。Clarification 只授权当前路径实际使用的 Tool；Proposal 的 primary write tool 仍须出现在 scope 中，即使 D4 会禁止执行。

### Frozen vocabulary

用于业务状态、参数、输出和差异的字段名、枚举及 Tool 名必须逐字取自 v0.1.2 Catalog、Context Envelope、Model Output Schema 或 Dataset Schema。来源标记只能使用上文约定的来源值。Scenario Schema 虽允许 `state.facts` 扩展内容，但扩展内容只能采用本节定义的 `recorded_facts` 结构：`{field, value, source}`，不得在此之下另造业务字段或枚举。`missing_fields` 写正式输入字段名；不把 `current_form_instance`、`transfer.status` 等说明性标签当业务状态。用户提及实体的原话可放在 `recorded_facts.value` 并标成 `user_input`，歧义候选 ID 只能取自读取结果。

### Resolvable evidence references

每条 `trust.evidence_refs` 都必须指向仓库内真实文件和真实位置，格式为 `path#Lnn`（Markdown/JSON 源行）或 JSON Schema / Catalog 的精确 JSON Pointer `path#/...`。提交前逐项打开引用目标，确认行号或 Pointer 指向支持当前结论的内容；章节标题文本、臆造锚点、文件不存在、泛化到无关章节的引用都不合格。独立业务审核是人工治理状态，结构/程序校验和 `frozen_rule` 标记不能代替它。

### Scenario-specific assertions

`ground_truth.deterministic_assertions` 每条都必须是本场景可判定的命题，能够由该 Scenario 的 state、tool result、正式 Contract/Catalog 或 expected result 检查。至少覆盖本例的关键决策和禁止推断：澄清条件/唯一性、UI 或交互来源有效性、Proposal 的级别及非执行状态、D4 全量差异、服务端结果原样解释、零匹配不等同于删除等。禁止用相同的泛化句替代场景事实；也不得断言 Scenario 未记录的来源、权限或成功写入。

### Preflight and production self-check

逐条输出前检查：

1. Scenario ID 与 Family ID 对应，Family 目标与当前场景相符；Core/Gated scope 和 Intent/Tool 角色可从冻结 Catalog 推得。
2. 来源账齐全：本轮输入、页面/交互状态、对话确认、查找参数和候选、缺失字段均有实际值及来源；事实不齐时澄清。
3. 所有 Tool 参数符合其 input schema；Supporting Lookup 是 read/L0，Tool 查询参数与被记录结果一致，结果足以支撑候选或解释。
4. Output type、confirmation、execution policy、proposal diff 与冻结规则一致。L1/L2 Proposal 仍只是待确认提案；D4 Proposal 明确不可执行。
5. 每个差异字段逐项列出真实 before/after；删除只针对已唯一定位且未锁定、权限条件已服务端验证的目标。
6. Assertions 有本场景特有、可判定的事实；每条 evidence ref 均可解析且直接支持结论；无臆造账务状态。
7. 全批 15 个 Scenario ID 唯一，版本与冻结基线一致，split 为 `unassigned`，合成标识无真实个人数据。

### Content Authenticity Preflight

每条 Scenario 在进入批量校验前，还要过内容真实性检查。机器只拦截有确定性证据的问题，不替代业务审核：

1. **输入来自业务目标**：`user_message` 必须是自然的用户请求，不能等于 Family ID、Matrix 标题或策划任务文本。机器可对精确复用和明显元数据做拒绝；话术是否像真实用户由人工确认。
2. **输出面向用户**：answer、clarification、proposal summary 不得泄漏 Family ID、Coverage Matrix、Scenario/Ground Truth 等生产元数据。机器可检测固定元词与 ID；人工检查语义是否回应本轮目标。
3. **业务标题与查询**：Expense title、Tool query 使用业务词汇，不能写 `L1/L2/D4`、proposal 标签、Family/训练术语或箭头流程。固定标记由机器拒绝；查询是否足以定位所需规则/实体由人工判断。
4. **Assertion 可判定且特有**：每条 assertion 指向本 Scenario 的具体金额、方向、候选结果、状态、diff、权限或输出分支。机器可检查 Family ID/标题替换和批次重复；无法由记录机械核对的语义由人工逐条检查。
5. **Evidence 有内容**：引用必须解析到实际行或 JSON Pointer，并直接支持所声明事实；只有 Markdown 标题、JSON 根花括号、空壳或无关内容不算证据。机器拒绝可辨认的标题/分隔符行；事实相关性由人工核对。
6. **实体没有幽灵项**：每个声明实体都须被输入事实、读取结果、操作参数或 Ground Truth 使用；机器统计引用并拒绝未引用实体。引用是否真实、是否同 Activity/权限范围由人工检查。
7. **标签与行为一致**：`clarification`、D4、UI/Interaction/Conversation 等规则标签须有对应的输出和可读状态事实。机器检查枚举/结构上的明显冲突；上下文是否充分及业务理由是否成立由人工检查。

机器可判定项的 ERROR 必须修复；不得通过 Family 命名、措辞变化或新增空字段规避。人工 Preflight 记录自然语言可信度、每个 Ground Truth 字段的来源、操作语义、规则适用性和差异完整性。无法从冻结文档、Catalog、服务端读取结果或确定性测试支撑的字段应删除/澄清，不能补造事实。

## Coverage traceability

| Coverage Matrix P0 Family | Scenario ID | 本 Scenario 覆盖分支 |
|---|---|---|
| `EXP-CREATE-001` | `scenario_gs_p0a_001` | 明确创建事实；唯一 `find_participants` Supporting Lookup 后，同 Intent L1 Proposal。 |
| `EXP-CREATE-002` | `scenario_gs_p0a_002` | 每人金额明确的手工分摊。 |
| `EXP-CLARIFY-001` | `scenario_gs_p0a_003` | 金额、币种、时间、标题与参与人明确，唯一参与人查询仍不能补缺付款人。 |
| `EXP-CLARIFY-003` | `scenario_gs_p0a_004` | `needs_explicit_financial_choice`：已知创建事实但分摊方式未定。 |
| `ENT-001` | `scenario_gs_p0a_005` | 支出创建中同名付款人有多候选；不绑定任一候选。 |
| `EXP-READ-002` | `scenario_gs_p0a_006` | `find_expenses` 多候选，保持 `find_expenses` Intent 并澄清。 |
| `EXP-READ-003` | `scenario_gs_p0a_007` | 有效 expense_detail UI selected_entity 提供唯一目标，读取 `get_expense`。 |
| `ICTX-008` | `scenario_gs_p0a_008` | screen_instance_id 改变使旧草稿失效；`clarify_reference` 无 Tool 澄清。 |
| `EXP-EDIT-001` | `scenario_gs_p0a_009` | 已读取存储支出后，金额、付款及手工分摊完整 before/after 的 D4 非执行预览。 |
| `PRE-GATED-001` | `scenario_gs_p0a_010` | 明确发生时间、方向与版本来源的预存 L2 Proposal。 |
| `TRF-007` | `scenario_gs_p0a_011` | 活跃 Transfer 读取及明确理由的作废 L2 Proposal。 |
| `DEL-001` | `scenario_gs_p0a_012` | 唯一未锁定本人支出删除的 L2 Proposal；`find_expenses` 仅是 Supporting Lookup。 |
| `UNS-001` | `scenario_gs_p0a_013` | 拒绝直接改库或篡改显示余额。 |
| `DEBT-001` | `scenario_gs_p0a_014` | 只读债务查询；本例仅覆盖 Family 的 `query_debt → get_debt` 主分支。 |
| `DEBT-004` | `scenario_gs_p0a_015` | 正确匹配两种读取参数，以不同 result_id 解释多币种债务和预存账户。 |

Family 有合并/并列分支时，本表只声明以上可由所选 Intent 和正式 Tool 路径覆盖的分支，不扩张 Scope。特别是 `DEBT-001` 的 `find_expenses` 分页子分支属于合并进 Family 的 DEBT-010 行为，Catalog 未将其映射给 `query_debt`；Scenario 014 不声称覆盖该分支，也不添加该 Tool。该 Matrix/Catalog 差异作为审核发现保留，不能用本 Scenario 改写冻结映射。

## Matrix-derived difficulty

Difficulty 继承 Coverage Matrix；冻结 `scenario.schema.json` 不定义 `difficulty` 属性并拒绝附加字段。分布：easy 2（EXP-CREATE-001、EXP-EDIT-001），normal 8（EXP-CREATE-002、EXP-CLARIFY-001、EXP-CLARIFY-003、EXP-READ-003、PRE-GATED-001、TRF-007、DEL-001、DEBT-001），hard 5（ENT-001、EXP-READ-002、ICTX-008、UNS-001、DEBT-004），ood 0。

## Supporting Lookup, D4, and lifecycle

Supporting Lookup 来自 Catalog 映射；此批只使用当前正式 scope 中授权的 read/L0 Tool。候选、未命中和解释均须对应本 Scenario 实际查询及真实结果。DEL-001 的 lookup 只负责从 `find_expenses` 结果中定位删除目标；不存在命中时不得编造 Expense 或输出删除 Proposal。

Scenario 009 的 `update_expense` 是 D4 提案目标 Tool，`get_expense` 是 `update_expense.supporting_lookup_tools` 读取当前持久化支出的实际 Tool。Proposal 将 `original_amount`、`payments`、`manual_splits` 三项金额从已验证的当前值 100 CNY 改为 120 CNY；三个 before/after 均完整相等于 `expected_diff`。它保持 `execution_allowed=false`、`reason=d4_atomic_update_not_supported`，不代表调用或写入成功。

`SILVER` 表示来源锚定冻结规则且通过程序校验，但仍待独立业务审核；不能单凭 `frozen_rule` 或 Validator 结果改为 `GOLD`/`reviewed`。原先经独立审核记录为 PASS 的 `scenario_gs_p0a_001`、`scenario_gs_p0a_002`、`scenario_gs_p0a_013` 在后续真实性检查中发现低质量证据行、未使用实体和 Family ID assertion，均降为 `SILVER`、`business_validated=false`、`draft`，并移除 Gold 级人工审核标记。本轮只将 001/002 的证据改为实际 Expense 规则行，删除三条记录中未引用的用户实体，并重写 013 的边界断言；它们仍须独立复核，当前 P0-A 没有 GOLD 记录。独立审核身份不能由本次生产者兼任。

## Validation and review record

使用 `DatasetValidator.validate_scenario` 对数组中每个正式 Scenario 校验；批次的 schema/role/path/diff 自检按 Scenario ID 归集，不依赖数组位置。合并 54 条时也使用 `validate_dataset` 执行完整记录与批次校验，Samples 列表为空，不伪造 Sample。CLI `validate scenario` 仅接受单对象，`validate dataset` 需要目录内样本文件。本轮按最新复审修订后，P0-A 15 条、P0-B 39 条及合并 54 条均为 0 errors/0 warnings；Validator 单测 43/43 通过，Examples 0 errors（3 条既有重复/语义组复核 warning）。这些机器结果不替代下一轮独立业务复审。修订者不得把自己的修订标为已独立审核。
