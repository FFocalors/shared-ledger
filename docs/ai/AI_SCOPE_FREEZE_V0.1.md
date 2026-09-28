# Shared Ledger AI Scope Freeze v0.1

> 状态：**首期能力范围已冻结为设计契约**；AI Gateway、客户端入口与模型均尚未实现。基于 BUSINESS LOGIC FREEZE v1.2（提交 `55fb28a7c0660462e5842e2eb5c71cfa763e5801`）和 [AI Model Contract v0.1.2](AI_MODEL_CONTRACT.md)（当前仓库版本）。
> 本文决定第一代 4B 级模型的训练与首期开放范围；完整 Contract 的 70 个 Intent、44 个 Tool 及现有 JSON Schema 保留。业务行为和权限仍以 [BUSINESS_LOGIC.md](../backend/BUSINESS_LOGIC.md) 与[最终复核](../backend/BUSINESS_LOGIC_FINAL_REVIEW.md)为准。

## 1. Scope Freeze 目标

让首期模型优先可靠地完成自然语言记账、结构化查询、基于服务端结果的解释、页面/交互/会话指代解析、澄清及单步 Tool Calling。范围分级只约束 **AI 是否训练、是否暴露 Tool、写入是否允许推进到确认和执行**；不会变更现有 Android/RPC 能力。三种 scope 与 confirmation level 相互独立。

本稿把上一版“所有写操作确认”的待决议建议收口为 L0/L1/L2；所有首期写操作仍需可信 UI 点击，区别是确认卡的信息和风险强度。旧 Tool 目录中的 `confirmation_required`、`confirmation_policy=proposed_all_writes` 表示“写入不得直达”，新增 `confirmation_level` 与本稿给出首期细则。若字段有歧义，以本稿的首期范围/确认分级为准；不改变旧业务语义。

## 2. v0.1 产品定位与三档范围

| Scope | 模型目标 | 首期 Tool 行为 |
| --- | --- | --- |
| `CORE` | 高频训练与评测：意图、字段、指代、澄清、查询、解释；正 Expense 创建/编辑理解 | 读 Tool 可按需调用；L1 写先输出 proposal；Expense 财务编辑暂止于不可执行 proposal |
| `SUPPORTED_BUT_GATED` | 能识别、提取字段、查询候选、生成待确认的单项操作 | 读 Tool 为 L0；L2 写先输出 proposal，经结构化确认卡及服务端校验；既有能力不等于 AI 已部署 |
| `DEFERRED` | 识别请求并解释边界或引导原生页面；不训练执行 Tool Call | Tool 不进入首期 `enabled_tools`；模型不得输出执行性 Tool Call |

`CORE` 是模型学习优先级，**不是自动执行许可**。Refund 共用 `create_expense`，但 Refund 意图始终是 GATED；同一 Tool 的实际确认级别必须结合 Intent、金额符号和原单来源确定。静态 `model_output.schema.json` 仍覆盖完整 Contract，首期 Gateway 还必须执行本 Scope allowlist；JSON Schema 通过不代表首期允许调用。

## 3. CORE 能力

CORE 有 **24 个 Intent、12 个 Tool**。消费侧训练正 Expense 的单/多付款人、AA、手动分摊、普通/大型活动、已明确选中的 LedgerUnit、当前草稿和已验证 Expense 的连续修改；服务端仍负责 Payment/Split 守恒、AA 尾差与 FX。`create_expense` 要求正金额且 `original_expense_id=null` 才是普通 L1 记账路径。

`update_expense` Intent 保留 CORE，以学习“把这笔金额改成…”的实体定位、原值读取、变更 diff 和结构化 proposal；该 proposal 固定 `execution_allowed=false`，`update_expense` Tool 的实际写入关闭，详见 D4。`update_expense_presentation` 可在 L1 生成允许确认后推进的 proposal。用户仅要求编辑**未提交表单**时，模型可解释/组织草稿字段并由原生表单展示，当前协议没有 `edit_draft` Tool，不能宣称已改写或提交 UI 草稿。

查询侧重点是 Activity 状态、当前 Expense、两人债务与逐币种余额、个人预存和规则/错误解释。债务来源、可用余额及 completed 只能读取服务端 Tool 结果，禁止模型自行重算。`summarize_activity` 仅在按需取得有界且完整的结果后回答；结果截断时不宣称“全部”。`clarify_reference`、`unknown`、`unsupported_request` 虽无 Tool，也是 CORE 安全控制意图。`find_activities`、`query_sub_activity`、`query_participant` 为范围与实体解析提供读取路径。

## 4. SUPPORTED_BUT_GATED 能力

GATED 有 **21 个 Intent、13 个 Tool**。包括真实发生的 FIFO/TARGETED 还款与 void、预存/返还、负 Expense 退款或调整、Expense 删除、Final Settlement 单项执行，以及它们的候选预览和历史查询。查询/解释本身是 L0；同组资金写入为 L2，必须先输出 proposal。模型不得将“准备转账”解释为“已发生转账”，也不得为了绕过拒绝更改金额、方向或选择另一笔 Expense。

`get_final_settlement` 返回整个 Activity 的服务端建议；`execute_final_settlement` 只能引用一条完整建议，确认后重新校验版本和实际资金发生。Refund 必须区别 linked refund 与未关联负调整：来源不明先问，不能降级为负调整。负金额创建请求即使错误地标成 `create_expense` 也按 L2 拦截并要求正确意图；`create_expense` Tool 为共享 CORE Tool、风险按分支升级。

`update_refund` 可识别、显示原单及变更 diff，但与普通 Expense 财务编辑共用缺少显式原子版本参数的 RPC；因此首期实际更新写入同样暂停。`create_refund`、`delete_refund` 则仍按已有正式 RPC、永久锁和 L2 确认政策设计。所有这些是未来 AI 接口的设计范围，当前没有可执行 Gateway。

## 5. DEFERRED 能力

DEFERRED 有 **25 个 Intent、19 个 Tool**。涵盖 Activity 创建/加入/设置/归档/删除、子活动创建/删除/恢复、成员移除与 Creator 转移、Participant 增删和 Claim/Unclaim、Dispute 写入、附件/账号管理与独立汇率查询。原生 Android 页面和后端能力可以继续使用；首期 AI 仅解释并引导至对应原生流程，不能调用相关写 Tool。

`restore_expense`、`restore_transfer`、`update_transfer` 是现有业务明确不支持；`update_sub_activity` 缺少正式 RPC。这些 Intent 被识别后返回现有 `unsupported` 结构，不假装存在原生执行入口。`manage_attachment` 仅说明图片附件仍由原生流程处理；`manage_account` 不把认证信息送进模型。DEFERRED 不表示数据库产品能力被删除。

## 6. Intent Scope Matrix

| 分类 | CORE | SUPPORTED_BUT_GATED | DEFERRED | 合计 |
| --- | ---: | ---: | ---: | ---: |
| activity | 3 | 0 | 6 | 9 |
| assistant | 6 | 0 | 6 | 12 |
| attachment | 0 | 0 | 1 | 1 |
| currency | 0 | 0 | 1 | 1 |
| debt | 5 | 0 | 0 | 5 |
| dispute | 0 | 0 | 2 | 2 |
| expense | 6 | 1 | 0 | 7 |
| final_settlement | 0 | 3 | 0 | 3 |
| ledger_unit | 1 | 0 | 3 | 4 |
| member | 0 | 0 | 2 | 2 |
| participant | 1 | 0 | 4 | 5 |
| prepayment | 2 | 4 | 0 | 6 |
| refund | 0 | 6 | 0 | 6 |
| transfer | 0 | 7 | 0 | 7 |
| **合计 Intent** | **24** | **21** | **25** | **70** |

首期范围字段写入 [intent_catalog.json](schema/intent_catalog.json)：`ai_scope_v0_1`、`confirmation_level`、`training_priority`、`first_release_tool_call_allowed`、`first_release_write_execution_allowed`。其中 `first_release_*` 是**未来 Gateway 策略许可**，不表示当前系统已部署；D4 阻断的编辑 Intent 可形成非执行预览，但 `first_release_tool_call_allowed=false`，不得调用写 Tool。Intent ID、语义、参数与原有映射保持不变。

| Intent ID | 分类 | 首期 Scope | 确认级别 | 首期处理路径 |
| --- | --- | --- | ---: | --- |
| `find_activities` | activity | CORE | L0 | 读取 `find_activities` → 回答 |
| `create_activity` | activity | DEFERRED | L1 | 解释/原生页面；不调用 Tool |
| `join_activity` | activity | DEFERRED | L1 | 解释/原生页面；不调用 Tool |
| `update_activity` | activity | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `archive_activity` | activity | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `unarchive_activity` | activity | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `delete_activity` | activity | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `remove_member` | member | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `transfer_creator` | member | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `add_participant` | participant | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `remove_participant` | participant | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `claim_participant` | participant | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `unclaim_participant` | participant | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `create_sub_activity` | ledger_unit | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `delete_sub_activity` | ledger_unit | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `restore_sub_activity` | ledger_unit | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `find_expenses` | expense | CORE | L0 | 读取 `find_expenses` → 回答 |
| `create_expense` | expense | CORE | L1 | 生成 `create_expense` proposal；UI 确认后服务端校验 |
| `update_expense` | expense | CORE | L1 | 读取→变更 diff/预览；写入待 D4 |
| `update_expense_presentation` | expense | CORE | L1 | 生成 `update_expense_presentation` proposal；UI 确认后服务端校验 |
| `delete_expense` | expense | SUPPORTED_BUT_GATED | L2 | 生成 `delete_expense` proposal；UI 确认后服务端校验 |
| `find_fund_records` | transfer | SUPPORTED_BUT_GATED | L0 | 读取 `find_fund_records` → 回答 |
| `get_settlement_options` | transfer | SUPPORTED_BUT_GATED | L0 | 读取 `get_settlement_options` → 回答 |
| `preview_settlement_transfer` | transfer | SUPPORTED_BUT_GATED | L0 | 读取 `preview_settlement_transfer` → 回答 |
| `create_settlement_transfer` | transfer | SUPPORTED_BUT_GATED | L2 | 生成 `create_settlement_transfer` proposal；UI 确认后服务端校验 |
| `void_transfer` | transfer | SUPPORTED_BUT_GATED | L2 | 生成 `void_transfer` proposal；UI 确认后服务端校验 |
| `preview_prepayment` | prepayment | SUPPORTED_BUT_GATED | L0 | 读取 `preview_prepayment` → 回答 |
| `create_prepayment` | prepayment | SUPPORTED_BUT_GATED | L2 | 生成 `create_prepayment` proposal；UI 确认后服务端校验 |
| `execute_final_settlement` | final_settlement | SUPPORTED_BUT_GATED | L2 | 生成 `execute_final_settlement` proposal；UI 确认后服务端校验 |
| `add_transfer_dispute` | dispute | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `resolve_transfer_dispute` | dispute | DEFERRED | L2 | 解释/原生页面；不调用 Tool |
| `list_attachments` | attachment | DEFERRED | L0 | 解释/原生页面；不调用 Tool |
| `get_currency_context` | currency | DEFERRED | L0 | 解释/原生页面；不调用 Tool |
| `query_activity` | activity | CORE | L0 | 读取 `get_activity_context` → 回答 |
| `query_activity_status` | activity | CORE | L0 | 读取 `get_activity_context` → 回答 |
| `query_sub_activity` | ledger_unit | CORE | L0 | 读取 `get_ledger_unit` → 回答 |
| `query_participant` | participant | CORE | L0 | 读取 `find_participants` → 回答 |
| `query_expense` | expense | CORE | L0 | 读取 `get_expense` → 回答 |
| `explain_expense` | expense | CORE | L0 | 读取 `get_expense` → 回答 |
| `create_refund` | refund | SUPPORTED_BUT_GATED | L2 | 读取原单→生成 `create_expense` proposal；UI 确认后服务端校验 |
| `update_refund` | refund | SUPPORTED_BUT_GATED | L2 | 读取→变更 diff/预览；写入待 D4 |
| `delete_refund` | refund | SUPPORTED_BUT_GATED | L2 | 读取原单→生成 `delete_expense` proposal；UI 确认后服务端校验 |
| `query_refund` | refund | SUPPORTED_BUT_GATED | L0 | 读取 `find_expenses` → 回答 |
| `explain_refund` | refund | SUPPORTED_BUT_GATED | L0 | 读取 `get_expense`, `get_debt` → 回答 |
| `create_negative_adjustment` | refund | SUPPORTED_BUT_GATED | L2 | 生成 `create_expense` proposal；UI 确认后服务端校验 |
| `query_transfer` | transfer | SUPPORTED_BUT_GATED | L0 | 读取 `get_transfer` → 回答 |
| `explain_transfer` | transfer | SUPPORTED_BUT_GATED | L0 | 读取 `get_transfer`, `get_expense` → 回答 |
| `query_prepayment` | prepayment | CORE | L0 | 读取 `get_prepayment_accounts` → 回答 |
| `return_prepayment` | prepayment | SUPPORTED_BUT_GATED | L2 | 读取账户→生成 `create_prepayment_return` proposal；UI 确认后服务端校验 |
| `void_prepayment` | prepayment | SUPPORTED_BUT_GATED | L2 | 读取原记录→生成 `void_transfer` proposal；UI 确认后服务端校验 |
| `explain_prepayment` | prepayment | CORE | L0 | 读取 `get_prepayment_accounts`, `get_debt` → 回答 |
| `query_debt` | debt | CORE | L0 | 读取 `get_debt` → 回答 |
| `query_bilateral_debt` | debt | CORE | L0 | 读取 `get_debt` → 回答 |
| `query_participant_balance` | debt | CORE | L0 | 读取 `get_participant_balance` → 回答 |
| `explain_debt` | debt | CORE | L0 | 读取 `get_debt`, `get_expense` → 回答 |
| `explain_balance` | debt | CORE | L0 | 读取 `get_participant_balance`, `get_prepayment_accounts` → 回答 |
| `query_final_settlement` | final_settlement | SUPPORTED_BUT_GATED | L0 | 读取 `get_final_settlement` → 回答 |
| `explain_final_settlement` | final_settlement | SUPPORTED_BUT_GATED | L0 | 读取 `get_final_settlement`, `lookup_business_rule` → 回答 |
| `explain_rule` | assistant | CORE | L0 | 读取 `lookup_business_rule` → 回答 |
| `explain_error` | assistant | CORE | L0 | 读取 `lookup_business_rule` → 回答 |
| `summarize_activity` | assistant | CORE | L0 | 读取 `get_activity_context`, `find_expenses`, `get_prepayment_accounts`, `get_debt` → 回答 |
| `restore_expense` | assistant | DEFERRED | L0 | 解释/原生页面；不调用 Tool |
| `restore_transfer` | assistant | DEFERRED | L0 | 解释/原生页面；不调用 Tool |
| `update_sub_activity` | assistant | DEFERRED | L0 | 解释/原生页面；不调用 Tool |
| `update_transfer` | assistant | DEFERRED | L0 | 解释/原生页面；不调用 Tool |
| `manage_attachment` | assistant | DEFERRED | L0 | 解释/原生页面；不调用 Tool |
| `manage_account` | assistant | DEFERRED | L0 | 解释/原生页面；不调用 Tool |
| `clarify_reference` | assistant | CORE | L0 | clarification / unsupported / error |
| `unknown` | assistant | CORE | L0 | clarification / unsupported / error |
| `unsupported_request` | assistant | CORE | L0 | clarification / unsupported / error |

## 7. Tool Scope Matrix

| 分类 | CORE | SUPPORTED_BUT_GATED | DEFERRED | 合计 |
| --- | ---: | ---: | ---: | ---: |
| activity | 2 | 0 | 6 | 8 |
| assistant | 1 | 0 | 0 | 1 |
| attachment | 0 | 0 | 1 | 1 |
| currency | 0 | 0 | 1 | 1 |
| debt | 2 | 0 | 0 | 2 |
| dispute | 0 | 0 | 2 | 2 |
| expense | 4 | 2 | 0 | 6 |
| final_settlement | 0 | 2 | 0 | 2 |
| ledger_unit | 1 | 0 | 3 | 4 |
| member | 0 | 0 | 2 | 2 |
| participant | 1 | 0 | 4 | 5 |
| prepayment | 1 | 3 | 0 | 4 |
| transfer | 0 | 6 | 0 | 6 |
| **合计 Tool** | **12** | **13** | **19** | **44** |

[tool_catalog.json](schema/tool_catalog.json) 为每项补充 `ai_scope_v0_1`、`training_priority`、`confirmation_level`、`confirmation_level_by_intent` 和 `first_release_execution_allowed`。Intent 与 Tool 的 PRIMARY/SUPPORTING_LOOKUP 映射统一以 Intent Catalog 为权威；Tool Catalog 不重复维护允许 Intent 列表。读 Tool 即使为高风险写意图准备候选，仍是 L0；共享写 Tool 的顶层级别取最高风险分支，实际级别按 Intent 和 payload。**DEFERRED Tool 不暴露到首期 enabled_tools**；每个 Intent 仅接受 Intent Catalog 明列的 PRIMARY / SUPPORTING_LOOKUP Tool。

| Tool ID | 分类 | 模式 | 首期 Scope | 确认级别 | 首期处理 |
| --- | --- | --- | --- | ---: | --- |
| `find_activities` | activity | read | CORE | L0 | 按需查询；无需确认 |
| `get_activity_context` | activity | read | CORE | L0 | 按需查询；无需确认 |
| `create_activity` | activity | write | DEFERRED | L1 | 不进入 enabled_tools |
| `join_activity` | activity | write | DEFERRED | L1 | 不进入 enabled_tools |
| `update_activity` | activity | write | DEFERRED | L2 | 不进入 enabled_tools |
| `archive_activity` | activity | write | DEFERRED | L2 | 不进入 enabled_tools |
| `unarchive_activity` | activity | write | DEFERRED | L2 | 不进入 enabled_tools |
| `delete_activity` | activity | write | DEFERRED | L2 | 不进入 enabled_tools |
| `remove_member` | member | write | DEFERRED | L2 | 不进入 enabled_tools |
| `transfer_creator` | member | write | DEFERRED | L2 | 不进入 enabled_tools |
| `find_participants` | participant | read | CORE | L0 | 按需查询；无需确认 |
| `add_participant` | participant | write | DEFERRED | L2 | 不进入 enabled_tools |
| `remove_participant` | participant | write | DEFERRED | L2 | 不进入 enabled_tools |
| `claim_participant` | participant | write | DEFERRED | L2 | 不进入 enabled_tools |
| `unclaim_participant` | participant | write | DEFERRED | L2 | 不进入 enabled_tools |
| `get_ledger_unit` | ledger_unit | read | CORE | L0 | 按需查询；无需确认 |
| `create_sub_activity` | ledger_unit | write | DEFERRED | L2 | 不进入 enabled_tools |
| `delete_sub_activity` | ledger_unit | write | DEFERRED | L2 | 不进入 enabled_tools |
| `restore_sub_activity` | ledger_unit | write | DEFERRED | L2 | 不进入 enabled_tools |
| `get_expense` | expense | read | CORE | L0 | 按需查询；无需确认 |
| `find_expenses` | expense | read | CORE | L0 | 按需查询；无需确认 |
| `create_expense` | expense | write | CORE | L2 | 按 intent + 金额符号 + original_expense_id 判 L1/L2 |
| `update_expense` | expense | write | SUPPORTED_BUT_GATED | L2 | 仅生成 D4 不可执行 proposal；禁止实际写 RPC |
| `update_expense_presentation` | expense | write | CORE | L1 | proposal + 可信 UI 点击后才允许 RPC |
| `delete_expense` | expense | write | SUPPORTED_BUT_GATED | L2 | proposal + 可信 UI 点击后才允许 RPC |
| `get_transfer` | transfer | read | SUPPORTED_BUT_GATED | L0 | 按需查询；无需确认 |
| `find_fund_records` | transfer | read | SUPPORTED_BUT_GATED | L0 | 按需查询；无需确认 |
| `get_settlement_options` | transfer | read | SUPPORTED_BUT_GATED | L0 | 按需查询；无需确认 |
| `preview_settlement_transfer` | transfer | read | SUPPORTED_BUT_GATED | L0 | 按需查询；无需确认 |
| `create_settlement_transfer` | transfer | write | SUPPORTED_BUT_GATED | L2 | proposal + 可信 UI 点击后才允许 RPC |
| `void_transfer` | transfer | write | SUPPORTED_BUT_GATED | L2 | proposal + 可信 UI 点击后才允许 RPC |
| `get_prepayment_accounts` | prepayment | read | CORE | L0 | 按需查询；无需确认 |
| `preview_prepayment` | prepayment | read | SUPPORTED_BUT_GATED | L0 | 按需查询；无需确认 |
| `create_prepayment` | prepayment | write | SUPPORTED_BUT_GATED | L2 | proposal + 可信 UI 点击后才允许 RPC |
| `create_prepayment_return` | prepayment | write | SUPPORTED_BUT_GATED | L2 | proposal + 可信 UI 点击后才允许 RPC |
| `get_debt` | debt | read | CORE | L0 | 按需查询；无需确认 |
| `get_participant_balance` | debt | read | CORE | L0 | 按需查询；无需确认 |
| `get_final_settlement` | final_settlement | read | SUPPORTED_BUT_GATED | L0 | 按需查询；无需确认 |
| `execute_final_settlement` | final_settlement | write | SUPPORTED_BUT_GATED | L2 | proposal + 可信 UI 点击后才允许 RPC |
| `add_transfer_dispute` | dispute | write | DEFERRED | L2 | 不进入 enabled_tools |
| `resolve_transfer_dispute` | dispute | write | DEFERRED | L2 | 不进入 enabled_tools |
| `list_attachments` | attachment | read | DEFERRED | L0 | 不进入 enabled_tools |
| `get_currency_context` | currency | read | DEFERRED | L0 | 不进入 enabled_tools |
| `lookup_business_rule` | assistant | read | CORE | L0 | 按需查询；无需确认 |

## 8. Confirmation Levels

| 等级 | 范围 | 客户端/Gateway 行为 | 例子 |
| --- | --- | --- | --- |
| L0 | 所有只读/搜索/规则问答，包括 GATED 范围内的查询 | 无二次确认；服务端鉴权、实体范围与结果来源仍需校验 | `get_debt`、`get_expense`、`get_final_settlement` |
| L1 | 正常正 Expense 创建、可开放后的未锁定正 Expense 编辑、展示字段编辑；未提交草稿仅本地预览 | AI 输出含完整参数与 diff 的 proposal→Gateway 校验→用户点击 UI 确认→Gateway 再校验→写 tool_call/RPC。当前财务编辑 proposal 被 D4 单独标为不可执行 | `create_expense` 正向、`update_expense_presentation` |
| L2 | 真实资金、Refund/负调整、删除、void、Final、归档及多人高影响管理 | AI 输出 L2 proposal；确认卡列出活动、双方/目标、方向、原币金额/币种、来源和影响；用户**显式点击**后可信确认事件绑定规范 payload，再由服务端事务校验 | `create_settlement_transfer`、`create_prepayment`、`void_transfer`、`delete_expense` |

DEFERRED 写 Tool 虽标记相应风险级别，首期仍不可执行；proposal 或确认卡都不是开放 DEFERRED 功能的开关。L1/L2 均不得由模型生成或接受 `confirmed=true`。聊天中的“确定、可以、执行吧、就这样、没问题”只能帮助定位唯一待确认方案，**不能作为最终授权**。确认事件必须由可信 UI 控件生成并绑定用户、Activity、Intent、Tool、规范参数、版本和过期时间；Gateway 验证后才能承认写 `tool_call` 并调用正式 RPC。[模型输出 Schema](schema/model_output.schema.json) 允许六类输出；L1/L2 写意图先使用结构化 `proposal`，其中 `confirmation.required` 只声明需要确认，不声明已经确认。

对于 `create_expense`：`create_expense` + 正金额 + `original_expense_id=null` 才走 L1。负金额、linked refund、意图与 payload 不一致都不能通过改 Intent 名称降低级别；应询问或按 GATED L2 路径处理。`update_expense` 的正编辑目标是 L1，退款编辑是 L2，但 D4 解除之前都不调用写 RPC。任何 UI 确认仍不能替代服务器权限、额度、归档、锁、FX 与版本校验。

## 9. Clarification Policy

以下情况必须先澄清：未确定付款人、付款人分额、承担人/本人是否参加、AA 还是手动及手动金额；同名 Participant 或多个匹配 Expense；“我”无法经当前 Activity 的 claim 验证；“他/她/他们”“这笔/上一笔/刚才那笔”无唯一候选；大型活动未指定可确认的 LedgerUnit；Transfer 双方/币种/金额/真实发生状态不明；Refund 原单/实际收款人/受益人不明；Owner/Custodian 或 Final 方案项不唯一。缺少字段时不得拼凑符合总额的 Payment/Split。

解析顺序：本轮明确表达与用户手选实体→同 Activity 当前 selected entity/已手填草稿→已确认会话绑定→可验证的最近成功操作→有界服务端候选。任意来源冲突均问用户，不按列表第一项或姓名猜测。UI 自动选首人/全员AA、退款按原比例默认分配都只是 `ui_default`，不能替代用户选择。`UNKNOWN` 或提交结果未知要先对账，不能把它称为“最近成功”。

“这个/这里/当前活动”需页面 scope 与服务端对象归属一致；“上一笔”需明确是列表顺序、发生时间还是最近登记；“昨天”按用户时区形成查询区间，多个结果返回候选。换 Activity、账号或实体失效时旧绑定失效。`clarification` 使用完整 Contract 的既有字段，不生成新输出类型。

## 10. Default Value Policy

| 分类 | 字段/行为 | 冻结处理 |
| --- | --- | --- |
| `ALLOWED_DEFAULT` | 新记录 `note=null`、受支持的默认 `icon_key=money`、搜索 `limit/cursor`、非财务显示排序 | 可由确定性 UI/Gateway 设置并在预览可见；不覆盖已有记录或把截断列表说成全量 |
| `REQUIRES_CONFIRMATION` | 未指明币种时提出经服务端验证的 Activity.base_currency；未指明发生时刻时提出 Gateway 记录的当前时间/用户时区 | 候选方案是显示在结构化预览、用户点击后才进入写 payload；是否启用该预填方案仍是 OPEN_DECISION，裁决前先澄清。原 UI 默认值不算授权 |
| `FORBIDDEN_INFERENCE` | payer、Payment 各人金额、Participant、是否包括本人、split_method、manual split、Transfer 对方/金额/方向、FIFO/TARGETED/目标单、Prepayment Owner/Custodian、Refund 收款/受益、Final 付款发生与否、behalf | 无明确且经验证的来源就 clarification；不借助币种/时间候选补出其他财务选择 |

linked Refund 的币种/历史 FX 由所选原 Expense 和服务端规则决定，属**后端派生事实**，不是模型默认值。UI 选定的完整有效实体 ID 可以作为指代解析依据，但仍需 Gateway 检查归属与当前状态。`occurred_at` 与币种候选在用户确认前不可写入 Tool 调用；若当前 Model Output Schema 要求必填，先 clarification 或生成非执行预览，不能填任意时间让 Schema 通过。是否允许 Gateway 直接预填并用一次 L1/L2 点击确认，留作 OPEN_DECISION；在裁决前采取澄清路径。

## 11. Context Minimum Principle

客户端仅发送本轮 `user_message`、平台/时区、当前 route/page_type、活动/单元/选中实体 ID、用户实际编辑的草稿字段与来源、相关 recent action ID/状态。`user_context.user_id` 和 role 只是提示，Gateway 根据 JWT 重新验证；客户端不传 token、密码、Storage URL、全活动账目、完整转账史、推算债务或最大还款额。

Gateway 按当前 Intent 调用最少读 Tool：解析人名才查 Participant 候选，说明“这笔”才读 Expense，债务问题才读逐币投影，资金写入前才读最新额度和版本。大型活动只给当前 LedgerUnit 及必要父 Activity ID；Final 是完整 Activity 范围，不能把 LedgerUnit 当可结算范围。Tool 结果以 `result_id`、来源和观察时间绑定，只有当前任务必要的 DTO 进入模型。`get_activity_context` 可返回名单/单元，但不能成为每轮默认全量注入；过大结果拒绝或分页，不伪造完整快照。

## 12. Conversation Context Policy

首期默认**不永久保存完整聊天文本**。会话期保留有界最近消息、当前 Activity 和用户确认过的实体绑定/结构化摘要；页面/活动变化后收缩上下文，跨活动旧绑定不能成为新账本事实。新会话应允许用户从空历史重新开始。Tool 返回的金额/版本不靠聊天摘要重建，只用带来源的 Gateway 结果。

长期保存期限、是否跨设备同步、删除与隐私同意方式均为 `OPEN_DECISION`，本文没有制定持久化政策。模型训练不得直接抓取真实聊天或全活动数据；后续 Dataset Schema 先使用经同意且去标识、业务结果可校验的样本设计。

## 13. UI Context Policy

现有 Android [Routes.kt](../../app/src/main/java/com/ffocalors/sharedledger/ui/navigation/Routes.kt) 与 [SharedLedgerApp.kt](../../app/src/main/java/com/ffocalors/sharedledger/ui/navigation/SharedLedgerApp.kt) 对应的 17 类正式页面，加 `unknown`，沿用 [ContextEnvelope Schema](schema/context_envelope.schema.json) 的 page_type。首页要明确选中 Activity；普通详情解析 `default` 单元，大型详情区分 root/sub；消费表单区分 create/edit/refund；Transfer 区分 transfer/receive；Prepayment 区分 fund/return；Final 只在 Activity 范围。expense-detail 可只带 expense_id，再由 Gateway 读可见归属。

页面草稿 `field_sources` 要区分 user_input/user_selected/ui_default/conversation_confirmed/persisted_entity。`screen_instance_id` 与 draft revision 防止拿前一页的草稿修改当前页面。页面 loading/error/stale、客户端 financial_version_hint、权限提示或缓存余额都不是服务端写入依据。小程序沿用同一 page_type/ID/来源语义，route 字符串可以不同。当前 Android 尚无统一 AI Context 采集器，本文是接入约定。

## 14. Safety Boundaries

模型只负责提取、澄清、选择允许的 Tool 和解释结果；债务、AA 尾差、Payment/Split 守恒、退款限额、预存 Usage、Final 计划、汇率折算、完成状态与权限/并发判断由确定性服务端完成。Gateway 要同时验证 Intent 与 Tool 的 Scope、Intent Catalog 中的 PRIMARY / SUPPORTING_LOOKUP 映射、实际金额符号/Refund 来源、确认级别、已验证 ID 归属和权限；DEFERRED Tool 不出现在本轮 `server_context.enabled_tools`。客户端或聊天内容不能覆盖服务器 allowlist。

真实资金操作使用现有 v2 `request_id`/原 payload/version 的幂等规则，Gateway 负责保存并对账；Expense 创建/编辑及 void 没有同等幂等保证。确认后网络失败不可直接新建一笔，必须先查状态。不能调用 legacy 手工 FX、恢复、private rebuild、任意 SQL 或表 DML；不能让文档/备注/历史聊天中的指令扩展工具权限。AI 没有支付、转账对账、自动归档能力。

## 15. Current Known Limitations

- AI Model Contract 当前仍是完整能力草案，Tool 及确认接口均未实现；本 Scope 不把规则变成已上线功能。
- `update_expense_auto_rate` 没有显式 expected Expense/financial version 输入，读取→确认→写入存在竞态窗口。仅可训练理解/diff/预览，首期写执行标记 false，不声称具备原子 CAS。
- Refund 与正 Expense 共用 Tool；必须按 Intent/payload 双重判定，不能靠单个 Tool scope 自动确定风险。
- `get_activity_context`、`find_fund_records` 组合读可能涉及多表及分页；应按需查询和明确不完整，不能把过期或截断结果用于最终资金解释。
- v0.1.2 输出 Schema 为 `answer/proposal/tool_call/clarification/unsupported/error`；“引导原生流程”仍用 `unsupported.suggested_action` 或说明性 `answer`，不增加未定义的 `native_flow_required` 类型。

## 16. Blocking / Non-blocking Findings

| 原 Contract 差异 | 本 Scope 判定 | 对首期的处理 |
| --- | --- | --- |
| D1 Member 名单管理 UI 与规格/RPC 不一致 | `DEFERRED_WITH_FEATURE` | Participant 写管理延期；CORE `query_participant` 只读，按服务端可见范围 |
| D2 争议 RPC 比业务概述权限严格 | `DEFERRED_WITH_FEATURE` | 两个 Dispute 写 Tool 延期且保留既有 `enabled_after_decision=false`，不得放宽 RPC |
| D3 普通 LedgerUnit 在实现中为 `default`，规格概括为 root | `NON_BLOCKING` | CORE grounding 保留实际枚举，按 Activity 类型解释，不改数据库 |
| D4 Expense 财务编辑缺少显式原子版本参数 | `BLOCKING`（仅 AI 财务编辑写执行） | CORE 识别/diff 保留并输出 proposal；固定 `execution_allowed=false`，`update_expense`/`update_refund` 写执行关闭，直到策略裁定或后续正式后端契约解决 |
| D5 表单首人/AA 与退款比例 UI 默认 | `NON_BLOCKING`，有强制前置条件 | CORE/GATED 写入只接收用户明确字段；ui_default 不转成财务授权，缺失则问 |
| D6 Final 解释可能使人以为环债自动清零 | `NON_BLOCKING` | GATED 解释只依服务端方案及冻结规则，不承诺最少笔数或环债自动抵销 |
| D7 数据库测试状态首尾计数残留 | `NON_BLOCKING` | 采用最终复核的 30 文件/223 断言历史结果，不作为本阶段重跑结果 |

这七项不引入业务逻辑修改。D4 是当前首期 AI **写入许可**的阻断项；不推断数据库资金算法有新缺陷。若后续证据证明冻结规格与当前 RPC 存在真正不可调和冲突，应停用关联 AI 写路径并单独复核，不能在 Dataset 中标成可成功执行。

## 17. Dataset v0.1 Training Scope

下列是**采样方向**，不是本阶段生成的数据，也不是已批准的生产数据配比。以 CORE 约80%、GATED 约16%、DEFERRED 边界识别约4% 为初始目标；DEFERRED 只含识别/拒绝/原生流程引导，没有执行性 Tool Call。正式配比要在 Dataset Schema、覆盖矩阵和评测计划中验证后确定。

| 能力切片 | 初始占比 | 重点 |
| --- | ---: | --- |
| Intent 与参数提取 | 22% | 正 Expense、读查询及 GATED 请求的完整字段 |
| 单步 Tool 选择与参数 | 18% | 核对 ID、币种、source、Intent/Tool 允许列表 |
| UI 与 Interaction Context | 17% | 当前页面、草稿来源、最近成功/未知状态 |
| Clarification 与歧义 | 17% | 缺付款人、同名人、重复账单、跨活动冲突 |
| Entity Resolution | 10% | User/Participant 区分、账单/Transfer 类型 |
| Conversation Context | 7% | 已确认绑定、多轮更正、换活动失效 |
| 结果解释 | 6% | 原币/base、逐币余额、失败与未知提交 |
| Rule QA | 3% | 冻结规则与不支持能力 |

相比初始 20/20/15/15/10/8/7/5 建议，略增 CORE 的字段、UI 与澄清，降低规则问答和复杂 Tool 比例，符合 4B 模型首先可靠填槽/消歧的目标。每个样本将来应带 `ai_scope_v0_1`、Intent、上下文来源、服务端证据引用、预期输出/确认级别及业务基线版本；所有 L1/L2 写样本终点先是结构化 `proposal`，不能用“已执行”作标签。数据量、真实用户数据授权和评测门槛待后续阶段决定。

## 18. Dataset v0.1 Excluded Scope

不生成 DEFERRED 功能的执行 Tool Call 正例；不训练模型自行算债务/AA 尾差/FX、编 SQL、直接改表、自动创建多笔 Final、假装真实转账已发生、在无 claim 情况下默认“我”、按 UI 默认替用户决定分摊、仅靠聊天文字授权高风险操作。旧 legacy RPC、Expense/Transfer 恢复、跨币日常抵销与无现金环路冲销都不进入首期执行数据。既有 MASS 验证场景不能不经核验直接充当对话训练标签。

## 19. Open Decisions

1. `OPEN_DECISION`：币种缺失时是否允许以当前服务端 Activity.base_currency 预填、发生时间缺失时是否允许以 Gateway 当前时间预填并在一次 L1/L2 卡片中确认；冻结阶段在裁决前使用 clarification。
2. `OPEN_DECISION`：D4 未来若开启 Expense 财务编辑写路径，需要何种并发保证。当前没有原子 expected-version 参数，不能用客户端版本 hint 伪装 CAS；本阶段不改 RPC。
3. `OPEN_DECISION`：会话摘要/全文的存储期限、跨设备同步、用户重开会话和删除策略，以及 proposal/确认事件的有效期与恢复窗口。
4. `OPEN_DECISION`：后续版本是否开放 Creator/Member/Participant/Dispute/Attachment/账号等 DEFERRED 能力；D1/D2 在开放前须先完成规格、UI 与 RPC 对齐决策。

已冻结的原则不待上述决策：L2 需要可信 UI 显式点击，聊天文字不能最终授权；服务端为唯一账务合法性来源；DEFERRED Tool 首期不执行。

## 20. Freeze Conclusion 与验证

**AI Scope Freeze v0.1: READY（Dataset 与 Offline Validator 输入范围）**。首期分类保持 **24 CORE / 21 GATED / 25 DEFERRED Intent**，及 **12 CORE / 13 GATED / 19 DEFERRED Tool**。这不等于 Gateway 已实现或财务编辑可执行。D4 在写路径启用前保持 `BLOCKING`，但由 v0.1.2 proposal 正式表达其 preview-only 训练目标；其他未决策略在训练标签中以明确的 `OPEN_DECISION` 表示，不擅自填成定案。

离线一致性检查记录：两份 catalog JSON 可解析；70/44 项 scope 均合法且完整；每个 CORE 业务 Intent 至少有非 DEFERRED 读取/拟执行路径，控制 Intent 有 clarification/unsupported 路径；所有 DEFERRED Intent 的执行许可为 false；高风险写 Tool 为 L2，读 Tool 为 L0；两份矩阵与 JSON 从同一目录生成，`git diff --check` 通过。未运行数据库/Android 代码测试，因为本次只修改 AI 文档与目录标注。
