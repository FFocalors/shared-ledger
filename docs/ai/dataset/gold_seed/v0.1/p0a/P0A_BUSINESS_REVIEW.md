# P0-A Canonical Scenario 独立业务审核报告

> 状态：**INDEPENDENT BUSINESS REVIEW — 只读审核**。本轮不生成 Scenario / Sample，不调用 Teacher，不修改 Contract / AI Scope / Intent Catalog / Tool Catalog / Model Output Schema / Dataset Schema / Validation Rules / Coverage Matrix / Validator / 业务逻辑 / Android / RPC / 数据库，也**不修改** `scenarios.json`。
> 审核对象：`docs/ai/dataset/gold_seed/v0.1/p0a/scenarios.json`（15 条 Canonical Scenario）与同目录 `README.md`。
> 版本基线：BUSINESS LOGIC `1.2` / AI Contract `0.1.2` / AI Scope `0.1` / Dataset `0.1`；冻结 SHA `55fb28a7c0660462e5842e2eb5c71cfa763e5801`。

## 1. 审核方法

本轮是**独立业务审核**，不是重复 Schema 校验。方法分三层：

1. **机器复核**：独立重跑 Offline Validator；并用脚本对 15 条记录做交叉一致性检查（实体引用完整性、diff 一致性、Payment/Split 守恒、去重键唯一性、结构指纹、tool 角色合法性）。
2. **逐条独立审核**：15 条每条由一名独立审核者按 15 个维度审查（真实性与 Intent、Tool 路径、Lookup 三结果、Clarification 必要性、财务脑补、State 完整性、Proposal 层级与 diff、D4、GATED、Query/Explanation 计算泄漏、Pending Policy、Scope、Ground Truth 证据、内部一致性），产出发现与 PASS / REVISE / REJECT 判定。
3. **对抗式复核**：每条发现由独立验证者尝试反驳（无法从文件证实即不予采信）。

**重要**：自动化验证阶段的索引映射被证实不可靠（一条标注为 "001" 的裁决理由实际在讨论 014）。因此本报告 §4/§5 的**每一条判定都由我回到 `scenarios.json`、Catalog、Schema 与 Coverage Matrix 逐条复核后重新裁定**，未直接采信自动化 upheld/refuted 标签；其中一条自动化发现被判为**错误**并驳回（§5.4）。

判定只有三种：`PASS` = 无 BLOCKER 与 MAJOR；`REVISE` = 存在 MAJOR；`REJECT` = 存在 BLOCKER。

## 2. Validator 的覆盖边界（为什么必须有人工业务审核）

本轮**独立重跑**了 Offline Validator 的 `DatasetValidator.validate_scenario`，对 15 条记录逐条调用，结果与批次自述一致且可复现：

```text
15/15 records  errors = 0  warnings = 0  valid = True
```

这条 PASS 是真实的，但它**只覆盖结构**。核对 `validator.py` 与 `scenario.schema.json` 后确认，以下三类问题在 Schema 层**结构性不可见**，只能靠本轮审核发现：

| 不可见的原因 | 后果 |
| --- | --- |
| `scenario.schema.json#/$defs/state.facts` 定义为 `{"type":"object","additionalProperties":true}` —— 自由字段袋 | Validator **无法**要求"用户已提供的事实必须被记录"，State 缺字段不会被判错 |
| `state` / `operation` / `ground_truth` 只约束**字段存在**，不约束**字段内容之间的业务关系** | Validator **无法**发现 diff 漏列了按守恒规则必须变化的字段 |
| `title` / `description` 是自由文本，不与 `scope.intent_ids` 做一致性校验 | Validator **无法**发现标题/描述写的是一件事、Intent 与 Ground Truth 写的是另一件事 |

Validator 确实覆盖了：Schema/版本/SHA、Catalog 引用、Scope 与 Tool 暴露、**Tool 角色（PRIMARY / SUPPORTING_LOOKUP）合法性**、输出到 Intent/Tool 的映射、proposal 的 confirmation 与 execution_policy、D4 限制、clarification 注解一致性、proposal 成功语义措辞、隐私与泄漏、去重。**本轮发现的全部问题都在它覆盖不到的那一侧**——事实上一处 tool 角色越权都没有。

## 3. 机器复核结果（本轮独立执行）

| 检查 | 结果 |
| --- | --- |
| Offline Validator（逐条） | **15/15，0 error，0 warning**（复现批次自述） |
| 实体引用完整性（被引用的 UUID 是否都在 `state.entities` 声明） | **通过**，无悬空引用 |
| `expected_diff` 与 `proposal.preview.diff` 深度相等 | **通过**（5 条 proposal 全部一致） |
| Payment / Split 守恒（after 状态的 `payments` 合计 = `manual_splits` 合计 = `original_amount`） | **通过**（001/002/009 自洽） |
| 币种与 `occurred_at` 是否显式（Pending Policy 依赖） | **通过**：所有 proposal 的金额、币种、发生时间均为显式值，未依赖未冻结的默认预填 |
| `canonical_facts_sha256` / `dedup_key` / `scenario_family_id` 唯一性 | **通过**，15/15 唯一 |
| 结构指纹（intent + 输出类型 + tool 集 + 操作类型 + lookup 结果 + missing_fields + 确认级别 + split_method） | **15 个指纹互不相同**，无结构性重复 |
| 元数据一致性（SILVER / business_validated=false / draft / unassigned / active / example_only=false） | **通过**，15 条完全一致 |
| 批次 README 的 Difficulty 分布声明（easy 2 / normal 8 / hard 5 / ood 0） | **通过**，与 Coverage Matrix 对应 family 难度逐条吻合 |
| Lookup 三结果覆盖 | **通过**：unique = 001、003；multiple = 005、006；zero = 012；另有 007 证明"UI Context 已足够、不发 lookup" |
| Tool 角色合法性 | **通过**，0 处越权 |
| Proposal 层级与确认语义 | **通过**：001/002 = L1；009 = D4（`execution_allowed=false`、`reason=d4_atomic_update_not_supported`、`success_label=false`）；010/011 = L2；5 条 `final_authorization` 均为 `trusted_ui_event_required` |

**Pending Policy**：15 条**均未**依赖 Activity 本位币预填或当前时间预填。004 的澄清问的是 `split_method`，不是因为币种/时间缺失。→ **无 `PENDING_POLICY_VIOLATION`**。

**模型自行计算账务**：015 的答案以两个 verified result id 为依据、`no_model_calculation: true`；014 的 `model_calculates_debt: false`；009 的预览不重算债务。→ **未发现 `MODEL_CALCULATION_LEAK`**。

**Clarification 校准**：6 条澄清逐条判定——003（缺 payer）、004（缺 split_method）、005（同名歧义）、006（多候选）、008（旧绑定失效）、012（零匹配）**全部属于 `MUST_CLARIFY`**；5 条 proposal/answer 记录也**没有**出现应问未问（under-clarification）。→ **未发现过度澄清，也未发现澄清不足**。

### 3.1 与 Coverage Matrix 的 Tool 声明对账

15 条中有 6 条的 `scope.tool_ids` 与 Coverage Matrix 对应 family 的 Tool 列不一致：

| Scenario | Matrix 声明 | 记录声明 | 方向 |
| --- | --- | --- | --- |
| 001 (`EXP-CREATE-001`) | `create_expense` | `create_expense, find_participants` | 记录**多**一个 lookup |
| 003 (`EXP-CLARIFY-001`) | `create_expense` | `find_participants` | 记录**少** primary 写 Tool |
| 005 (`ENT-001`) | `find_participants, create_expense` | `find_participants` | 记录**少** primary 写 Tool |
| 012 (`DEL-001`) | `find_expenses, delete_expense` | `find_expenses` | 记录**少** primary 写 Tool |
| 014 (`DEBT-001`) | `get_debt, find_expenses` | `get_debt` | 记录**少**一个只读 Tool |
| 015 (`DEBT-004`) | `get_participant_balance, get_prepayment_accounts, get_debt` | `get_participant_balance, get_prepayment_accounts` | 记录**少**一个只读 Tool |

其中"少"的 5 条多数是**批次自定且更严格**的约定（README 明确"Clarification 只列本路径真正读取的 Tool"），该约定**符合** Contract（`tool_ids` 应反映本轮实际执行路径），但与 Matrix 行不一致；001 则相反，记录了 Matrix 没有的 lookup。**结论：tool 集的口径需要在 Matrix 与记录之间统一，并写进批量生产规则。**

## 4. 逐条审核表（15/15，无抽样）

| scenario_id | family_id | verdict | severity | intent | tool_path | clarification | proposal_level | ground_truth | context | duplicate_check | evidence | required_change |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `scenario_gs_p0a_001` | EXP-CREATE-001 | **PASS** | MINOR | CORE `create_expense` 正确（正金额 + `original_expense_id=null` → L1） | `find_participants`(SUPPORTING_LOOKUP, read/L0) → `create_expense`(PRIMARY)，合法且必要（姓名→participant_id 只能靠服务端候选） | 不适用；十个必填参数齐备，不该澄清 | L1 正确 | 无脑补：payer/AA 名单/金额全部来自 `state.facts.operation_arguments`；未让模型算 AA 尾差 | 自洽；`ledger_unit_id` 与 Activity 同域 | 结构指纹唯一，无近重复 | 真值可追溯，但 `evidence_refs` 未含 Contract §17.1；锚点不可解析 | MINOR：把 lookup 的 `query="李四"` 记进 `state`（现仅存在于 `ground_truth.expected_business_result`）；`evidence_refs` 补 Contract §17.1 |
| `scenario_gs_p0a_002` | EXP-CREATE-002 | **PASS** | — | CORE `create_expense` 正确 | 仅 `create_expense`(PRIMARY)；不声明 lookup | 不适用；逐人金额、币种、时间齐备 | L1 正确 | 无脑补；`payments=120`、`manual_splits=40+80` 与 `original_amount=120` 三方守恒（§6） | 自洽 | 指纹唯一 | 真值可追溯（§6/§7 手动分摊）；锚点不可解析 | 无（建议与 001 统一"参与者解析来源"的记录方式） |
| `scenario_gs_p0a_003` | EXP-CLARIFY-001 | **REJECT** | **BLOCKER** | CORE `create_expense` 正确 | 仅 `find_participants`(SUPPORTING_LOOKUP)，未附带未调用的写 Tool，符合批次约定 | **必须澄清**（payer 属 P6 禁止推断）——判定正确；但问题本身引用了无来源事实 | 不适用 | **金标 question 断言"这笔 60 CNY 的桌游费用"，而全记录除该 question 外不存在任何金额或标题**（`state.facts.operation_arguments` 仅 `{activity_id, query:"李四"}`） | 不足以支撑金标：金额/币种/发生时间均无事实来源 | 指纹唯一 | **INSUFFICIENT_GROUND_TRUTH_EVIDENCE**：金标引用的事实无法由 state 推导；锚点不可解析 | 把用户已提供的金额、标题、币种、参与人写入 `state.facts`；并确认币种是否为用户显式给出（若非显式，按 P8 币种亦须进 `missing_fields` 且 `policy_status` 需相应处理） |
| `scenario_gs_p0a_004` | EXP-CLARIFY-003 | **REVISE** | MAJOR | CORE `create_expense` 正确 | `tool_ids=[]` 正确（纯澄清不需要 Tool） | **必须澄清**（split_method 属 P6）；但 `reason` 与所声明家族冲突 | 不适用 | `reason=missing_fields` 与其冻结家族 `EXP-CLARIFY-003` 明写的 `reason=needs_explicit_financial_choice` **不一致**（AA/手动是必须由用户做的财务选择，不是单纯缺字段） | 不足：`occurred_at` 是 `create_expense` 必填项且 P8 定为"裁决前先澄清"，但 state 无任何时间来源，金标却断言"只缺 split_method" | 指纹唯一 | 家族级冻结取值未被遵循（COVERAGE_DRIFT）；锚点不可解析 | `reason` 改为 `needs_explicit_financial_choice`；在 state 记录 `occurred_at` 来源，或把 `occurred_at` 一并列入 `missing_fields`；state 的 `payer_participant_id`/`participant_ids` 应改用 Catalog 的 `payments`/`manual_splits`/`aa_participant_ids` 语义 |
| `scenario_gs_p0a_005` | ENT-001 | **REVISE** | MAJOR | CORE `create_expense` 正确 | 仅 `find_participants`（多候选，合法） | **必须澄清**（同名歧义）；但"付款人角色"这一前提在记录中无来源 | 不适用 | 未断言无来源的金额（question 不含数字），但 question 预设"张伟是实际付款人"，而 state 只记录了检索串 | 不足：`state.facts.operation_arguments` 仅 `{activity_id, query:"张伟"}`，用户已给的金额/参与人/分摊方式与付款人角色均未记录 | 与 003/006 同为"多候选→澄清"，但候选实体类别与 intent 不同 → 非重复 | 锚点不可解析 | 在 state 记录用户已提供的字段（金额、参与人、分摊方式）以及"某位张伟付款"这一事实，使 `ambiguous_entity` 与 `missing_fields=[]` 可被复核 |
| `scenario_gs_p0a_006` | EXP-READ-002 | **REVISE** | MAJOR | **`query_expense` 与其声明的冻结家族冲突**：`EXP-READ-002` 行的 intent→tool 是 `find_expenses → find_expenses`，家族说明并明写"两种结果都保持 intent=find_expenses 不变" | `find_expenses` 为该 intent 的合法 SUPPORTING_LOOKUP，路径本身合法 | **必须澄清**（多候选，P10）；`reason=ambiguous_entity`、候选带日期 ✓ | 不适用 | 两个候选带 `occurred_on`，消歧依据充分 ✓ | state 只记 `{activity_id, query:"火锅"}`，本形状下候选即解析结果，可接受 | 与 012 共用 `find_expenses`+clarification，但候选实体类别与 intent 不同 → 非重复 | 锚点不可解析 | 二选一：把记录 intent 改为 `find_expenses`（与家族一致），或改挂到 intent 为 `query_expense` 的家族并同步修订家族行 |
| `scenario_gs_p0a_007` | EXP-READ-003 | **REVISE** | MAJOR | CORE `query_expense` 正确 | 仅 `get_expense`(PRIMARY)；`expected_business_result.lookup_required=false` 显式证明"UI Context 已足够、不发 lookup" ✓ | 不适用 | 不适用（L0 tool_call） | 无计算泄漏 | **不足**：本记录全部价值在"详情页 selected_entity 唯一确定目标"，但 `state` 中不存在任何 UI 事实（`page_type`/`screen_instance_id`/`selected_entity`），该前提只能从 description 的自然语言断言取得 | 指纹唯一 | 锚点不可解析 | 在 `state` 记录 UI 上下文事实；`rule_tags` 的 `interaction_context` 无对应事实，应删除或补 draft/recent_actions 事实 |
| `scenario_gs_p0a_008` | ICTX-008 | **REVISE** | MAJOR | CORE `clarify_reference` 正确（旧绑定失效属指代不可解析） | `tool_ids=[]` 正确（纯澄清） | **必须澄清**（P11 旧绑定不得沿用）——行为正确；但缺失项命名不是业务字段 | 不适用 | `missing_fields=["current_form_instance"]` 是上下文对象而非业务字段；question 未点名本路径真正未知的资金字段 | 自洽（`stale_draft`/`current_ui` 的 `screen_instance_id` 不同，逻辑正确） | 指纹唯一 | 锚点不可解析 | `missing_fields` 改为真实业务字段（如当前表单的 `payer`/`amount`）；`evidence_refs` 补 AI Contract §8/§9/§11 |
| `scenario_gs_p0a_009` | EXP-EDIT-001 | **REJECT** | **BLOCKER** | CORE `update_expense` 正确（D4） | `scope` 声明 `get_expense`(SUPPORTING_LOOKUP) + `update_expense`，但 `operation` 只有 `update_expense` 一步，**`get_expense` 从未执行、也无结果**，而 diff 的 `before` 正需要它 | 不适用 | **L1 + D4 全部正确**：`execution_allowed=false`、`reason=d4_atomic_update_not_supported`、`successful_execution_label_allowed=false`、`final_authorization=trusted_ui_event_required`，preview 为将来式，未暗示点击即执行 ✓ | **diff 不完整**：`operation.arguments` 把 `payments`/`manual_splits` 都设为 120，但 `preview.diff` 只列 `original_amount` 100→120。按 §6 Payment/Split 守恒，这两项必然同时 100→120，必须出现在 diff（家族说明要求"精确 diff"）。另：`state` 未记录被编辑支出的当前事实，diff 的 `before=100` 只有 `expected_business_result.source_expense_amount` 一处依据 | 不足：无源账目快照，D4 的 before/继承字段不可追溯 | 指纹唯一 | 锚点不可解析 | ①`state` 记录被编辑支出的当前事实（100、付款与分摊名单、锁状态、版本）；②`preview.diff` 与 `expected_diff` 补齐 `payments`、`manual_splits` 等所有变化字段；③把 `get_expense` 的读取步骤与结果体现在记录中，或从 `scope.tool_ids` 移除 |
| `scenario_gs_p0a_010` | PRE-GATED-001 | **PASS** | MINOR | GATED `create_prepayment` 正确 | 仅 `create_prepayment`(PRIMARY)；`expected_financial_version` 是 Catalog 必填入参，`request_id` 正确缺席（Gateway 生成） | 不适用（字段齐备，不该澄清） | L2 正确（`level=2`、`required=true`、`final_authorization=trusted_ui_event_required`） | 无脑补；Owner/Custodian/金额/币种/时间均显式 | `description` 断言"聊天同意不能执行登记"，但 state 无任何会话事实——该断言在本记录内不可追溯 | 指纹唯一 | `expected_financial_version="12"` 的来源（`financial_version_hint`）未记录；锚点不可解析 | MINOR：在 `state` 记录该 chat 前提，或从 description 移除该断言；记录 `expected_financial_version` 来源 |
| `scenario_gs_p0a_011` | TRF-007 | **PASS** | MAJOR | GATED `void_transfer` 正确 | `get_transfer`(SUPPORTING_LOOKUP，确认 active) → `void_transfer`(PRIMARY)，合法且必要 | 不适用 | L2 正确 | 语义正确（作废不可逆、未声称已作废），但 **diff 字段名越出冻结投影**：用了 `transfer.status`，而 `tool_catalog.json#/$defs/transfer` 只有 `is_voided` 与 `void_reason`，没有 `status` | 自洽（`supporting_lookup_result.status="active"` 同样用了非冻结字段名） | 指纹唯一 | 锚点不可解析 | `transfer.status` 改为冻结投影字段（`is_voided`），`supporting_lookup_result` 同步改用冻结字段名 |
| `scenario_gs_p0a_012` | DEL-001 | **REJECT** | **BLOCKER** | GATED `delete_expense`（机器可读层） | `find_expenses`(SUPPORTING_LOOKUP, 零匹配) 合法 | **必须澄清**（零匹配，不得编造对象）——方向正确 | 不适用（澄清，无 proposal） | **标签层与意图层互相矛盾**：`title="退款来源零匹配时澄清原支出"`、`description` 通篇讲 `create_refund`（"保持退款 Intent，不能改为负向调整"），而 `scope.intent_ids`/`tool_ids`/`model_output.intent_id` 全是 `delete_expense`；README 亦登记为 DEL-001"零匹配删除目标"。同一记录不可能同时成立 | 不足且不真实：lookup 的 query 是元语言占位串 `"要删除的支出"`（同批 003/005/006 用真实检索串"李四/张伟/火锅"），"零匹配"更像占位符产物而非用户指代失败 | 与 006 共用 `find_expenses`+clarification，但 intent 不同 → 非重复 | **证据不支持金标**：`evidence_refs` 指向的 `DEL-001` 冻结行是 `proposal_generation` / `output_type=proposal` 的"单个 L2 删除提案"，本记录输出 `clarification`；DEL-001 家族主形状在 P0-A **完全未落地** | ①先裁定本记录服务哪个家族，并让 `title`/`description` 与 `intent`/`ground_truth`/README 四者一致；②把占位 query 换成真实用户可能给出的指代串；③若保留 DEL-001，需另有一条记录落地其 L2 删除提案主形状 |
| `scenario_gs_p0a_013` | UNS-001 | **PASS** | MINOR | CORE `unsupported_request` 正确 | `tool_ids=[]` 正确（拒绝，不调用 Tool、不探测对象） | 不适用 | 不适用 | 无脑补；`suggested_action` 存在，未假装执行 | `requested_action` 提到"张三"但 `state.entities` 无该参与人——对拒绝类记录可接受（不探测正是要求） | 指纹唯一 | 锚点不可解析 | 无阻塞改动；可选：锚点改为真实小节 |
| `scenario_gs_p0a_014` | DEBT-001 | **PASS** | MINOR | CORE `query_debt` 正确 | 仅 `get_debt`(PRIMARY) | 不适用 | 不适用（L0 tool_call） | **无计算泄漏**：`answer_must_reference_verified_result=true`、`model_calculates_debt=false`；"state 里没有债务事实"是**正确设计**（服务端结果属 Sample 层 `server_context`，不是 Canonical state 的义务） | 自洽 | 指纹唯一 | 锚点不可解析 | MINOR：`DEBT-001` 家族行另声明了 `find_expenses` 与并入的 DEBT-010（截断/P16）形状，本记录未兑现——补一条记录或收窄家族行 |
| `scenario_gs_p0a_015` | DEBT-004 | **REVISE** | MAJOR | CORE `explain_balance` 正确 | **`operation.tool_id` 与 `operation.arguments` 不匹配**：`tool_id=get_prepayment_accounts`，但 arguments 是 `{activity_id, participant_id}`，而 `get_prepayment_accounts_input` 只接受 `{activity_id, owner_participant_id, custodian_participant_id, currency}`；`participant_id` 是 `get_participant_balance` 的入参 | 不适用 | 不适用（answer） | **答案事实无 state 来源**：question 解释 20 CNY 预存余额与"账户方向"，但 `state.entities` 只有一个 participant（P001），没有 `prepayment_account` 实体、没有 Custodian 方——而 §12 规定预存账户维度是 (Activity, Owner, Custodian, currency)，缺 Custodian 时该账户不可能存在 | 不足：canonical world 无法产生金标断言的预存事实 | 指纹唯一 | 锚点不可解析 | ①改正 `operation.tool_id`/`arguments` 使二者匹配；②在 state 补第二参与人（Custodian）与 `prepayment_account` 事实，使 20 CNY 余额可达 |

## 5. 发现明细

### 5.1 BLOCKER（3 条，均不得以现状进入 Gold Seed）

**B-01 `scenario_gs_p0a_003` — 金标澄清问题断言了无来源的财务事实**
`ground_truth.model_output.question = "这笔 60 CNY 的桌游费用由哪位参与人实际付款？"`，但全记录除该 question 外**不存在任何金额或标题**（`state.facts.operation_arguments` 仅 `{activity_id, query:"李四"}`；`description` 却自述"金额与参与人可确定"）。若照此实例化，模型会被训练成"输出一个包含输入中并不存在的事实的问题"。属任务清单中"财务事实脑补 / Ground Truth 错"。修正很小：把用户已提供的金额、标题、币种、参与人写进 `state`。

**B-02 `scenario_gs_p0a_009` — D4 的 diff 不完整，且所声明的 lookup 未发生**
同一 proposal 的 `operation.arguments` 已把 `payments` 与 `manual_splits` 设为 120，但 `preview.diff` 只列 `original_amount`。按 BUSINESS_LOGIC §6，Payment 与 Split 是独立事实且必须各自等于原币金额，因此这两项**必然**同时 100→120，必须出现在 diff 里（其冻结家族说明要求"精确 diff"）。同时 `scope` 声明了 `get_expense` 这个 SUPPORTING_LOOKUP，但 `operation` 只有 `update_expense` 一步、无该读取的执行与结果，而 diff 的 `before` 正需要它；`state` 也没有记录被编辑支出的当前事实。
**注意**：本记录的 D4 五项硬约束（`execution_allowed=false`、`reason=d4_atomic_update_not_supported`、`successful_execution_label_allowed=false`、有无结构化 diff、不暗示已执行）**全部正确**——问题只在 diff 的完整性与 pre-state 的可追溯性。

**B-03 `scenario_gs_p0a_012` — 标签层与意图层互相矛盾，且证据不支持金标**
`title`/`description` 通篇是 `create_refund`（"退款来源零匹配"、"不能改为负向调整"），而 `scope.intent_ids`、`scope.tool_ids`、`ground_truth.model_output.intent_id`、`expected_business_result`（`deletion_proposed:false`/`expense_deleted:false`）与 README 全部是 `delete_expense`。同一记录不可能同时成立。此外 lookup 的 query 是元语言占位串 `"要删除的支出"`（同批其他记录用真实检索串），且 `evidence_refs` 指向的 `DEL-001` 冻结行规定金标是"单个 L2 删除提案"，与本记录的 `clarification` 冲突——**DEL-001 家族的主形状在整个 P0-A 中没有任何记录落地**。

### 5.2 MAJOR（9 条）

| ID | Scenario | 问题 | 证据 |
| --- | --- | --- | --- |
| M-01 | 004 | `reason` 与冻结家族冲突：家族写明 `needs_explicit_financial_choice`，记录用 `missing_fields` | Coverage Matrix `EXP-CLARIFY-003` 家族说明原文"金标为 clarification(reason=needs_explicit_financial_choice)"；记录 `model_output.reason="missing_fields"` |
| M-02 | 004 | `occurred_at` 无任何事实来源，金标却断言"只缺 split_method" | `state.facts.operation_arguments` 无 `occurred_at`；`create_expense` 的 required 含 `occurred_at`；P8 要求缺失时先澄清 |
| M-03 | 005 | state 只记录检索串，用户已给的金额/参与人/分摊方式与"张伟付款"这一前提均无记录，`missing_fields=[]` 无法复核 | `state.facts.operation_arguments = {activity_id, query:"张伟"}` |
| M-04 | 006 | Intent 与所声明的冻结家族冲突（家族：`find_expenses`；记录：`query_expense`），该家族的意图监督信号在本批缺失 | Matrix `EXP-READ-002` 行 + 家族说明"两种结果都保持 intent=find_expenses 不变" |
| M-05 | 007 | UI Context 家族的**唯一判别事实**（页面、实例、selected_entity）不在 `state` 中，只能靠 description 的自然语言断言 | `state.facts.operation_arguments = {expense_id}`；全批仅 008 在 state 里带 UI 事实 |
| M-06 | 008 | `missing_fields=["current_form_instance"]` 是上下文对象而非业务字段；question 未点名真正未知的资金字段 | `model_output.missing_fields`；`state.facts.operation_arguments.stale_draft` 含 payer/amount |
| M-07 | 011 | diff 使用了冻结投影中不存在的字段名 | `tool_catalog.json#/$defs/transfer` 属性为 `is_voided`/`void_reason`，无 `status`；记录用 `transfer.status` |
| M-08 | 015 | `operation.tool_id` 与 `operation.arguments` 不匹配（`participant_id` 不是 `get_prepayment_accounts` 的入参） | `get_prepayment_accounts_input.required=["activity_id"]`、`properties=[activity_id, owner_participant_id, custodian_participant_id, currency]` |
| M-09 | 015 | canonical world 无法产生金标断言的 20 CNY 预存：state 只有一个 participant、无 `prepayment_account`、无 Custodian，而 §12 要求账户维度含 Custodian | `state.entities` 仅 A001/L001/U001/P001；`expected_business_result.verified_results` 断言 20 CNY 余额 |

### 5.3 批次级系统性发现（影响全部 15 条）

| ID | 发现 | 证据 | 需要的规则 |
| --- | --- | --- | --- |
| S-01 | **`state` 不记录金标所依赖的"已给定事实"** —— 这是本轮最高频、最结构性的缺陷（003、004、005、007、009、010、012 均属此类） | `state.facts` 是自由字段袋（`additionalProperties: true`），方法没有"哪些事实必须记录"的规则；同批 001/002/004/009/010 记了完整字段，003/005/006/012 只记了 lookup query | **规则 A**：`state.facts` 必须逐字段记录金标输出所依赖的每一个"用户已提供 / 已确认 / 缺失"的事实与其来源（user_input / user_selected / ui_default / 缺失），缺失项必须显式标记为缺失 |
| S-02 | **记录未与其声明的 Coverage Matrix family 逐字段对账**（004 的 reason、006 的 intent、012 的 title/description、014/015/001 的 tool 集） | Matrix 行与家族说明中存在冻结取值（primary_task、intent、output_type、confirmation level、reason），记录未逐项比对 | **规则 B**：每条记录必须与 family 行的 intent / tool 集 / output_type / 确认级别 / 家族说明中的受控取值逐项对账，并把对账结果写进记录 |
| S-03 | **非模型字段使用了非冻结字段名**（011 `transfer.status`、015 的非法入参组合、004 的 `payer_participant_id`/`participant_ids`、008 的 `current_form_instance`） | 与 `tool_catalog.json#/$defs/*` 与 Catalog 入参名不符 | **规则 C**：`state`、`operation.arguments`、`expected_business_result` 中的字段名与取值一律取自冻结 Catalog / Model Output Schema，不得自造 |
| S-04 | **`evidence_refs` 全部不可解析** —— 15 条共 42 处引用、去重 38 条锚点，实测**无一条**能在目标文档中定位（`#expense-split-rules`、`#manual-split`、`#prepayment`、`#void-transfer`、`#ledger-integrity`、`#debt-and-settlement`、`#context-and-stale-binding`、`#participant-identity`、`#unsupported-boundaries`、`#participant-balance-and-prepayment`、`#expense-delete-locks`、`#expense-payer-and-participants` 均不存在；BUSINESS_LOGIC.md 的小节标题是数字编号，Matrix 也没有 `#EXP-CREATE-001` 这类锚点） | `grep` 全量检索确认 0 命中 | **规则 D**：`evidence_refs` 必须写成可解析的引用（`文件#小节号` 或行号），并在写入前用脚本校验可解析 |
| S-05 | **模板化字段虚化了机器校验**：`preconditions`、`minimal_state_reason`、`deterministic_assertions` 三条在 15 条中是同一份模板 | 15 条记录的这三处内容逐字相同，未写家族特有的"要防的错误" | **规则 E**：`deterministic_assertions` 必须写成本记录特有的、可判定的断言 |

### 5.4 被驳回的发现（记录在案，避免后续误改）

- **"014 的 state 没有债务事实，因此无法支撑金标"** —— **驳回**。`query_debt` 的金标是发起 `get_debt` 读取；服务端结果按 Dataset Schema §13 属于 Sample 层 `input.server_context`，**不是** Canonical `state` 的义务。本条把 Sample 层的职责错加给 Scenario，若据此修改反而会破坏"模型必须读而不能自己算"的训练目标。
- **"005 的澄清把 payer 收窄成候选集、隐藏了真正缺失的字段"** —— **部分驳回**。`reason=ambiguous_entity` + `missing_fields=[]` 对"付款人身份在两位同名者之间不确定"是**恰当**的（缺的是实体唯一性，不是字段）；真正的问题是 state 未记录"某位张伟付款"这一前提（已并入 M-03），而非澄清行为本身错误。
- **"009 断言了用户未提供的 split_method/付款人/时间，属财务脑补"** —— **部分驳回**。`update_expense` 的入参 schema 要求全量字段，继承未变字段是协议必然；这**不是**脑补。真正的问题是继承值的来源（pre-state）未记录、且 diff 漏列（已并入 B-02/M 系列）。

### 5.5 场外发现：Coverage Matrix 自身的一处内部矛盾（需 Matrix 维护者修正，本轮不改）

`GOLD_SEED_COVERAGE_MATRIX_V0.1.md` 中 `EXP-CLARIFY-002` 的家族说明仍保留一段 **v0.1.2 之前的旧结论**：

> "修正 tool：intent=create_expense 的合法 Tool 只有 create_expense，**find_participants 只服务 query_participant**，声明它会触发 INTENT_TOOL_MISMATCH（Dataset Validation Rules §4）"

这与 v0.1.2 冻结 Catalog（`create_expense.supporting_lookup_tools = [find_participants]`）、Contract §17.1 以及同文件 §9.1 的复核结论**直接冲突**。危害是实际的：若后续 39 个 family 的作者照此注记行事，会**系统性漏声明合法 lookup**。建议由 Matrix 维护者删除或改写该句（属文档修正，不在本轮范围）。

## 6. 这是局部数据问题，还是生产方法的系统性问题？

**结论：系统性，但属"记录完整性/对账"层面，不属于"业务判断"层面。** 这个区分很重要，因为它决定 P0-B 应该"先改方法"还是"先改数据"。

**支持"系统性"的证据**：15 条中 **11 条需要改动**（3 BLOCKER + 8 含 MAJOR）；缺陷可归入 5 个可复现的模式（S-01 ~ S-05），且模式由方法本身产生——`state.facts` 无记录契约、记录不与 family 对账、字段名不取自冻结来源、`evidence_refs` 不校验可解析、断言模板化。相同的生产方法会以相同概率在剩余 39 个 family 上重复这 5 类缺陷。

**支持"业务判断本身是好的"的证据（同样重要）**：
- 6 条 Clarification **全部**判定正确，**既无过度澄清也无澄清不足**；
- 15 条的 Tool 路径**全部**合法，**0 处越权**、0 处把 lookup 当 Intent；
- 5 条 proposal 的 L1 / L2 / D4 **全部**正确，D4 五项硬约束全中，无一条暗示已执行；
- **无一处** Pending Policy 依赖、**无一处**模型自行计算账务、**无一处**把聊天文字当授权；
- lookup 三结果（unique / multiple / zero）与"UI Context 已足够"四态齐全。

也就是说：**这批数据"答对了业务题"，但在"把答案记成可复核的记录"上不达标。** 因此修复方向是给生产方法补规则（S-01 ~ S-05 对应规则 A ~ E），**不需要重新设计方法，也不需要修改任何冻结资产**。

## 7. 统计

| 项 | 数量 |
| --- | ---: |
| 审核 Scenario | **15 / 15**（无抽样） |
| PASS | **4**（001、002、013、014） |
| REVISE | **8**（004、005、006、007、008、010、011、015） |
| REJECT | **3**（003、009、012） |
| BLOCKER 发现 | **3**（记录级） |
| MAJOR 发现 | **9**（记录级，另 5 类批次级） |
| MINOR 发现 | **7**（001×2、002、007、010、013、014 各计） |
| 建议 `APPROVE_AS_GOLD` | **3**（001、002、013） |
| 建议 `KEEP_SILVER` | **12** |
| 建议 `REJECT`（弃用） | **0** —— 3 条 BLOCKER 均可修复，无需丢弃 |
| 近重复 / 真重复 | **0 真重复**；2 组同族不同支（005↔006↔012 的"读+澄清"形状，但 intent 与候选实体类别不同） |
| Coverage Drift | **4**（004、006、012、015）+ 3 处轻量（001、014、015 的 tool 集口径） |
| Pending Policy 误用 | **0** |
| 模型自行计算账务 | **0** |
| Tool 过度/不足授权 | **0 越权**；**0 缺失**（lookup 必要性逐条成立） |

## 8. 结论与建议

### 8.1 升级建议（本轮不修改任何状态）

**建议 `APPROVE_AS_GOLD`（3 条）**：`scenario_gs_p0a_001`、`scenario_gs_p0a_002`、`scenario_gs_p0a_013`。
依据：业务 Ground Truth 明确、Context 自洽、Tool 路径合理、无 Pending Policy、无未解决歧义；仅存批次级 `evidence_refs` 锚点卫生问题（S-04）与 001 的 lookup query 未记录（MINOR）。
**这三条仍不由我升级**——`business_validated=true` 与 lifecycle 提升应在 Codex 的修订/治理步骤中执行。若维护者希望先消除批次级锚点问题再统一升级，则三条改为 `KEEP_SILVER` 亦合理。

**建议 `KEEP_SILVER`（12 条）**：其余全部，按 §4/§5 的 `required_change` 修订后重新审核。

**不建议 `REJECT`（弃用）任何一条**：3 条 BLOCKER 都是记录完整性与标注问题，业务判断正确，修订成本低。

### 8.2 是否建议 Codex 修订 P0-A

**建议修订**，且修订项已逐条给出（§4 最后一列 + §5.1/5.2）。优先级：B-01/B-02/B-03 → M-01~M-09 → MINOR。

### 8.3 `GOLD_SEED_BLOCKER`

**未发现新的 `GOLD_SEED_BLOCKER`。** 既有的 `COVERAGE_BLOCKER-01` 已由 v0.1.2 解除且本轮再次确认（0 越权、Validator PASS）。需要修的是：

- **`GOLD_SEED_BLOCKER` 候选（文档级，非数据级）**：Coverage Matrix 中 `EXP-CLARIFY-002` 家族说明的过期结论（§5.5）。它会**系统性地误导**后续 39 个 family 的作者漏声明合法 lookup。建议在 P0-B 开始**之前**修正该句（一行文档改动，属 Matrix 维护者范围）。

### 8.4 对 P0-B 的准入判断

```text
NOT_READY_FOR_P0B
```

**判定依据（明确 blocker）**：任务给定的标准是——若暴露的是"少量单条数据错误"则可修完继续；若暴露"系统性 Scenario Production 方法错误"（含 **Context 构造方法错误**、**Ground Truth 来源不可靠**）则须先修生产方法。本轮实测：

- 11/15（73%）需改动，3 条 BLOCKER；
- 缺陷归入 **5 个可复现的方法模式**，其中 S-01 正是"Context/State 构造方法错误"（gold 依赖的事实不被记录），S-02 使"Ground Truth 与其声明家族不一致"，S-04 使"证据不可解析"；
- 这些模式由生产方法产生，会在剩余 **39 个 P0 family** 上以相同概率重复。

**解除条件（完成后即可进入 P0-B）**：
1. 把 S-01 ~ S-05 对应的**规则 A ~ E 写入生产方法**（可作为 `p0a/README.md` 或 Dataset Planning 文档中的一节，不修改冻结 Schema）；
2. 修正 §5.5 的 Matrix 过期注记；
3. 修订 3 条 BLOCKER 记录并重新审核通过。

**必须强调**：本判定**不是**因为业务语义有问题（业务判断是达标的），也不是因为比例或语言丰富度；仅因"记录不可复核"这一系统性方法缺陷会原样复制到下一批。方法与数据修订量都很小，预计一轮修订即可解除。

### 8.5 本轮边界

未生成任何 Scenario / Sample；未调用 DeepSeek 或任何模型 API；未修改 `scenarios.json`、Contract、Scope、Catalog、Model Output Schema、Dataset Schema、Validation Rules、Coverage Matrix、Validator、业务逻辑、Android、RPC、数据库；未提交 Git。本报告是**唯一新增文件**。
