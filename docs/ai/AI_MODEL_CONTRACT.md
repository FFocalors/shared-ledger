# Shared Ledger AI Model Contract v0.1

> 状态：**Contract draft，待产品决策，未实现 AI Gateway**。日期：2026-09-27。中文语义规范与 JSON Schema 联合构成契约。
> 冻结基线：`55fb28a7c0660462e5842e2eb5c71cfa763e5801`，BUSINESS LOGIC FREEZE v1.2。当前 HEAD 与基线一致；工作区存在用户的 Android/UI 未提交修改，页面检查包含这些修改，本文不修改它们。

## 1. 目标、依据与交付边界

本稿定义自然语言意图、上下文、工具及输出边界，供下一阶段 Dataset Schema 使用；不是模型训练、训练数据集、部署方案或业务规则修订。所有 AI Tool 和 Context 接口均为**建议新增**，映射的业务 RPC/查询则已在本地仓库实现。未连接远端数据库，也未验证生产部署。

根目录没有 `BUSINESS_LOGIC.md`，实际唯一规则文件为 [docs/backend/BUSINESS_LOGIC.md](../backend/BUSINESS_LOGIC.md)。优先级：该冻结规格 → [最终复核 §13](../backend/BUSINESS_LOGIC_FINAL_REVIEW.md) → 累积 migrations 的当前函数、ACL 与测试。历史 RPC 名称存在不代表仍允许客户端调用；不以旧文档或旧 fixture 覆盖冻结规则。

检查范围：全部 43 个 migrations 的定义/替换/授权链；Activity/Expense/Transfer/Financial/Exchange/Attachment Repository、Payload、DTO、ErrorMapper；Navigation、相关 ViewModel、UI State、表单与主要 Screen；[findings 索引](../../verification/findings/README.md)、数据库测试状态及财务/权限/并发/退款/幂等专项；Android 的 Route、ExpenseRefund、TransferPayload、FinalSettlementRequest、草稿与请求持久化测试；6 个 smoke 与 AA regression 场景。附件 A 列出全部 migration 指纹，附件 B 列出重点证据。检查不是重新运行这些业务测试。

交付的四份 JSON：

- [intent_catalog.json](schema/intent_catalog.json)：逐项定义场景、权限、参数、歧义、失败与 Tool 映射。
- [tool_catalog.json](schema/tool_catalog.json)：逐项 input/output Schema、RPC 签名/源位置/参数映射/最终校验。
- [context_envelope.schema.json](schema/context_envelope.schema.json)：Gateway 归一后的模型上下文。
- [model_output.schema.json](schema/model_output.schema.json)：封闭输出联合类型，Tool 名与参数按分支绑定。

JSON Schema 使用 Draft 2020-12，`https://shared-ledger.invalid/ai/v0.1/` 是离线 Schema 命名空间，不是已部署地址。校验器必须启用 `format` 检查，并本地注册相邻 catalog 的 `$id`；禁止运行时访问该域名。

## 2. 产品定位与模型任务

AI 是全局自然语言交互层。Android 当前主要页面将来可以唤起相同入口；微信小程序采用同一语义协议。当前仓库没有该全局 AI 入口，本稿不把它描述为现成功能。

模型负责：意图分类、结构化参数提取、实体候选解析、缺失和冲突检测、逐步 Tool 调用、基于结果解释账务、冻结规则问答、多轮指代和页面/草稿/最近操作 grounding。语音或图片识别、自动银行支付、模型训练和自运行 Agent 不在本稿范围。只识别到“不支持”同样是有效结果。

## 3. AI / deterministic backend 职责边界

| 事项 | 唯一最终责任方 | 模型可做的事 |
| --- | --- | --- |
| ExpenseDebt/BilateralDebt、AA 原币和 base 尾差、Payment/Split 守恒 | 确定性 RPC/投影 | 解析付款人/承担人和明确的金额，解释返回值 |
| FX/base 折算、历史快照、退款累计额度与重算 | 服务端 | 传原币信息，不传 fx_rate、不自行换算 |
| 还款最大额度、FIFO/TARGETED 分配、预存抵扣/返还 | 服务端 | 获取预览，确认后请求登记真实资金事实 |
| Final plan/path、completed、多币种状态 | 服务端 | 引用完整建议项，逐币种解释，不净额化环路 |
| 权限、claim、Creator behalf、归档/永久锁、并发事务、版本 | RPC + 鉴权 Gateway | 发现明显缺失后澄清，不把模型判断作为授权 |
| request_id、重试、确认令牌、结果对账 | Gateway/客户端确定性逻辑 | 不生成/更换资金 request_id，不判断已成功 |
| SQL、表 DML、内部重建函数 | 不对模型开放 | 不提供任意 SQL、RPC 名或表名执行工具 |

Transfer 是对已经真实发生资金的登记，本项目不执行银行付款。“转给他100”还不足以确认款项已发生。完成状态不由模型设置，归档不等于结清，空 Final plan 不证明没有债务。

## 4. 数据语义与不可变约束

- Activity 是财务边界；普通 Activity 的单一单元在 SQL 为 `default`，大型有 `root` 和 `sub_activity`。冻结规格将普通单一单元概括为 root。接口保留真实枚举，不按字面误判普通单元为子活动。大型 root 可记共同消费。
- Participant、登录 User、访问 Member、ParticipantClaim 是不同实体。不能用显示姓名或 User ID 代替 Participant ID。Activity 总名单首次 Expense/sub-activity 后锁定，但既有 Participant 仍可认领/解除认领。
- Refund 是负 Expense。linked refund 要明确 `original_expense_id`，同活动有效正来源、同币、完整 FX 继承、有效累计绝对原币不超来源。没有来源的负调整必须由用户明确选择，不作为绕过退款上限的退路。退款收款人和受益人不必沿用原单，也不保证新债务总是反向。
- 真实 Transfer 及来源历史不可改写，只有 active→voided。Expense/Transfer 恢复均不支持；子活动恢复存在且受真实 Transfer 来源历史限制。
- 真实 Transfer source 或 linked Refund 历史造成永久财务锁，之后 void/删除退款不解锁。单独 PrepaymentUsage 不触发永久锁；仅 title/note/icon_key 可走展示更新。
- 债务原币与 base 独立；base=0 的非零原币 micro debt 仍有效。AA Split 公平尾差与 manual Split 尾差、ExpenseDebt 尾差是不同规则。禁止模型按 base 反推原币。
- 新外币开关限制新 Expense/Prepayment，不冻结历史外币还款、Return、linked Refund、Final 或 void。预存为 Activity、Owner、Custodian、币种账户；Return 固定 Custodian→Owner 且使用账户币种。
- Final 为整个 Activity，一次登记完整建议项；每次成功后重新获取方案。不保证全局最少笔数，不抵销无现金多人环路。
- `transfer_allocations.amount` 是 base；`original_amount` 是来源原币；不可变实际来源 `payment_amount` 是付款币种。模型不能混同三者。`total_prepayment` 仅 base 账户小计；以逐币种余额和服务端 completed 解释状态。

## 5. Intent Catalog

Intent 是用户目标，Tool 是可复用执行接口。Refund 与 Expense 共用写工具；查询/解释共用读取工具；预存作废与普通作废共用 `void_transfer`。恢复等被拒绝意图仍可识别，但没有执行 Tool。没有 update_sub_activity 正式 RPC，不从表权限推导新产品能力。

以下为索引；每项的完整必填/可选字段、上下文、典型表达、典型歧义、clarification/失败条件在机器目录中；参数指针引用 Tool Schema，额外语义如 linked Refund 来源为本节和 intent.notes 的约束。所有执行型 Intent 至少映射一个 write Tool。解释中的数值只能来自列出的读取结果，不能仅依赖 `lookup_business_rule` 生成实时账务答案。

| Intent | 含义 | 分类 | 写/资金/确认 | Tool |
| --- | --- | --- | --- | --- |
| `find_activities` | 查询本人可访问活动 | activity | 否/否/否 | `find_activities` |
| `create_activity` | 创建普通/大型 Activity | activity | 是/否/是 | `create_activity` |
| `join_activity` | 通过邀请码加入活动 | activity | 是/否/是 | `join_activity` |
| `update_activity` | 更新活动设置 | activity | 是/是/是 | `update_activity` |
| `archive_activity` | 归档活动 | activity | 是/是/是 | `archive_activity` |
| `unarchive_activity` | 解除归档 | activity | 是/是/是 | `unarchive_activity` |
| `delete_activity` | 软删除活动 | activity | 是/是/是 | `delete_activity` |
| `remove_member` | 移除访问成员 | member | 是/否/是 | `remove_member` |
| `transfer_creator` | 转移创建者身份 | member | 是/否/是 | `transfer_creator` |
| `add_participant` | 新增参与人 | participant | 是/否/是 | `add_participant` |
| `remove_participant` | 删除参与人 | participant | 是/否/是 | `remove_participant` |
| `claim_participant` | 认领为当前用户 | participant | 是/否/是 | `claim_participant` |
| `unclaim_participant` | 解除当前用户认领 | participant | 是/否/是 | `unclaim_participant` |
| `create_sub_activity` | 创建子活动 | ledger_unit | 是/否/是 | `create_sub_activity` |
| `delete_sub_activity` | 软删除子活动 | ledger_unit | 是/是/是 | `delete_sub_activity` |
| `restore_sub_activity` | 恢复子活动 | ledger_unit | 是/是/是 | `restore_sub_activity` |
| `find_expenses` | 筛选消费、退款、负向调整 | expense | 否/是/否 | `find_expenses` |
| `create_expense` | 创建消费、负调整或 linked Refund | expense | 是/是/是 | `create_expense` |
| `update_expense` | 更新未锁定消费/退款财务字段 | expense | 是/是/是 | `update_expense` |
| `update_expense_presentation` | 仅编辑标题、备注、图标 | expense | 是/否/是 | `update_expense_presentation` |
| `delete_expense` | 逻辑删除消费或退款 | expense | 是/是/是 | `delete_expense` |
| `find_fund_records` | 查询真实 Transfer、退款和自动预存 Usage | transfer | 否/是/否 | `find_fund_records` |
| `get_settlement_options` | 当前方向可付币种、额度及目标账单候选 | transfer | 否/是/否 | `get_settlement_options` |
| `preview_settlement_transfer` | 预览 FIFO/TARGETED 真实还款分配 | transfer | 否/是/否 | `preview_settlement_transfer` |
| `create_settlement_transfer` | 登记已经真实发生的还款 | transfer | 是/是/是 | `create_settlement_transfer` |
| `void_transfer` | 按真实 Transfer 类型作废 | transfer | 是/是/是 | `void_transfer` |
| `preview_prepayment` | 预览先还债后预存的服务端分配 | prepayment | 否/是/否 | `preview_prepayment` |
| `create_prepayment` | 登记 Owner→Custodian 已发生预存 | prepayment | 是/是/是 | `create_prepayment` |
| `execute_final_settlement` | 登记一条完整建议对应的真实付款 | final_settlement | 是/是/是 | `execute_final_settlement` |
| `add_transfer_dispute` | 提出真实 Transfer 的争议 | dispute | 是/否/是 | `add_transfer_dispute` |
| `resolve_transfer_dispute` | 解除争议标记 | dispute | 是/否/是 | `resolve_transfer_dispute` |
| `list_attachments` | 读取现有图片附件元数据 | attachment | 否/否/否 | `list_attachments` |
| `get_currency_context` | 查询服务端汇率与支持币种 | currency | 否/否/否 | `get_currency_context` |
| `query_activity` | 查询活动详情 | activity | 否/是/否 | `get_activity_context` |
| `query_activity_status` | 查询服务端完成状态 | activity | 否/是/否 | `get_activity_context` |
| `query_sub_activity` | 查询子活动 | ledger_unit | 否/否/否 | `get_ledger_unit` |
| `query_participant` | 查询参与人和认领 | participant | 否/否/否 | `find_participants` |
| `query_expense` | 查询消费详情 | expense | 否/是/否 | `get_expense` |
| `explain_expense` | 解释消费与已还进度 | expense | 否/是/否 | `get_expense` |
| `create_refund` | 创建关联退款 | refund | 是/是/是 | `get_expense`, `create_expense` |
| `update_refund` | 编辑未锁定退款 | refund | 是/是/是 | `get_expense`, `update_expense` |
| `delete_refund` | 删除未锁定退款 | refund | 是/是/是 | `get_expense`, `delete_expense` |
| `query_refund` | 查询 linked Refund | refund | 否/是/否 | `find_expenses` |
| `explain_refund` | 解释负 Payment/Split 与退款债务 | refund | 否/是/否 | `get_expense`, `get_debt` |
| `create_negative_adjustment` | 创建不关联来源的负 Expense | refund | 是/是/是 | `create_expense` |
| `query_transfer` | 查询转账 | transfer | 否/是/否 | `get_transfer` |
| `explain_transfer` | 解释真实资金记录 | transfer | 否/是/否 | `get_transfer`, `get_expense` |
| `query_prepayment` | 查询预存 | prepayment | 否/是/否 | `get_prepayment_accounts` |
| `return_prepayment` | 返还预存 | prepayment | 是/是/是 | `get_prepayment_accounts`, `create_prepayment_return` |
| `void_prepayment` | 作废预存或返还 Transfer | prepayment | 是/是/是 | `get_transfer`, `void_transfer` |
| `explain_prepayment` | 解释预存抵扣 | prepayment | 否/是/否 | `get_prepayment_accounts`, `get_debt` |
| `query_debt` | 查询债务 | debt | 否/是/否 | `get_debt` |
| `query_bilateral_debt` | 查询两人逐币种债务 | debt | 否/是/否 | `get_debt` |
| `query_participant_balance` | 查询个人逐币种余额 | debt | 否/是/否 | `get_participant_balance` |
| `explain_debt` | 解释当前债务来源 | debt | 否/是/否 | `get_debt`, `get_expense` |
| `explain_balance` | 解释逐币种余额 | debt | 否/是/否 | `get_participant_balance`, `get_prepayment_accounts` |
| `query_final_settlement` | 查询最终结算 | final_settlement | 否/是/否 | `get_final_settlement` |
| `explain_final_settlement` | 解释服务端最终建议 | final_settlement | 否/是/否 | `get_final_settlement`, `lookup_business_rule` |
| `explain_rule` | 冻结业务规则问答 | assistant | 否/否/否 | `lookup_business_rule` |
| `explain_error` | 解释已归一业务错误 | assistant | 否/否/否 | `lookup_business_rule` |
| `summarize_activity` | 基于服务端结果总结活动 | assistant | 否/是/否 | `get_activity_context`, `find_expenses`, `get_prepayment_accounts`, `get_debt` |
| `restore_expense` | 请求恢复 Expense | assistant | 否/否/否 |  |
| `restore_transfer` | 请求恢复 Transfer | assistant | 否/否/否 |  |
| `update_sub_activity` | 请求编辑子活动名称/备注 | assistant | 否/否/否 |  |
| `update_transfer` | 请求改写资金事实 | assistant | 否/否/否 |  |
| `manage_attachment` | 请求上传或删除图片附件 | assistant | 否/否/否 |  |
| `manage_account` | 账户登录与个人资料 | assistant | 否/否/否 |  |
| `clarify_reference` | 澄清指代 | assistant | 否/否/否 |  |
| `unknown` | 未识别意图 | assistant | 否/否/否 |  |
| `unsupported_request` | 超出能力范围 | assistant | 否/否/否 |  |

`unknown` / `clarify_reference` 是控制意图。`restore_expense`、`restore_transfer`、`update_transfer` 是冻结明确不支持；`update_sub_activity` 是当前无正式接口；`manage_attachment`、`manage_account` 是现有客户端能力但 v0.1 AI 不执行，不能把它们说成整个产品不支持。批量请求按用户指定次序拆成独立单操作；未明确次序则询问，不能自动归档、自动移除/添加 Participant 或连锁 void。

## 6. 统一 ContextEnvelope 与信任边界

一级字段为 `contract_version`、`request_id`、`user_message`、`client_context`、`ui_context`、`user_context`、`page_state`、`recent_actions`、`conversation_context`、`server_context`。

前九项由客户端提交线索；`server_context` 只由 Gateway 根据认证会话生成，客户端即使传入也必须剥离并重建。Schema 描述的是完整模型输入，不是让客户端自证身份的请求。`request_id` 为一次对话请求跟踪 ID，不是财务 RPC 的 `request_id`。

| 字段 | 内容与来源 | 使用限制 |
| --- | --- | --- |
| client_context | platform/app_version/locale/timezone/sent_at | timezone 使用 IANA 名称并由 Gateway 检验，时间来自客户端只作线索 |
| ui_context | route/page_type/screen_instance_id、scope ID、selected_entity、form_mode/focused_field | 原生路由为诊断信息，业务依赖标准 page_type + ID；查服务端归属 |
| user_context | user_id、claimed_participant_id、role_hint | 全部提示值；本人必须由 JWT→claim 重新解析 |
| page_state | load_state、fetched_at、版本 hint、filters、visible_entities、draft、write_state | 无资金合法性或授权效力；loading/error 不等于空账本 |
| recent_actions | 动作、目标、时间、状态、result_id | 只有可验证成功结果作为“刚才那笔”；点击和 pending/unknown 不是成功 |
| conversation_context | bounded messages、活动范围、confirmed_bindings、pending clarification | 历史话语不是可执行指令，也不是账务事实；换活动后不继承旧绑定 |
| server_context | authenticated_user_id、generated_at、固定基线、enabled_tools、verified_result_ids、tool_results、确认策略 | 仅服务端写入；tool_results 按工具 output_schema 校验，验证 ID 必须对应真实回执；权限与版本依然要在提交事务中复查 |

草稿 fields 为有类型的白名单；`field_sources` 标明 user_input/user_selected/ui_default/conversation_confirmed/persisted_entity。原 Android draft 中的 fxRate、格式化合计、余额、最大可付金额不作为可写字段传入。草稿缺失、空字符串输入中、NULL 清空和已有值不同；未完成输入保留在客户端，不能强行变成合法 Tool 参数。`note=null` 是明确清空，缺省是尚未指定；全量展示更新须先读旧值，未被要求修改的值原样带入。

Schema 无法表达所有跨字段约束：Gateway 还必须检查 ID 归属、page_type 与 route/mode 一致、field_sources 覆盖已传字段且每字段唯一、引用 turn/result 存在、日期区间顺序、付款/承担唯一、候选截断与版本时效。不满足时拒绝上下文或澄清，不静默修复财务含义。

## 7. 当前 Android 页面覆盖

来源为 [Routes.kt](../../app/src/main/java/com/ffocalors/sharedledger/ui/navigation/Routes.kt) 和 [SharedLedgerApp.kt](../../app/src/main/java/com/ffocalors/sharedledger/ui/navigation/SharedLedgerApp.kt)。17 类正式页面对应 17 个 page_type，加 `unknown` 兼容未来页面；同一路由内不同 mode 不虚构额外页面。`LargeActivitySmokeTestScreen.kt` 是开发验证 Screen，不是生产 Navigation 能力。

| Android route | page_type | 客户端应提供 | 必须重新读服务端 |
| --- | --- | --- | --- |
| auth | auth | 当前登录视图；不传密码、验证码、token | 未登录仅规则问答 |
| home | home | 列表筛选、选中活动、可见 ID | 活动访问权限、财务状态 |
| personal-info | personal_info | 选中活动/个人概览 scope；账号弹层不传敏感草稿 | claim 与逐币种状态；账号修改回原生流程 |
| join-activity | join_activity | 用户明确输入的8位邀请码、认领选中人 | join 成功后的名单/claim；join 与 claim 分开 |
| create-activity | create_activity | name/type/base_currency/multi_currency_enabled 草稿与来源 | 创建权限/参数有效性 |
| normal-activity/{activityId} | normal_activity | activity_id、单一 default ledger、筛选/选中账单 | 真实 default ID、状态 |
| large-activity/{activityId} | large_activity | activity_id、选中 root/sub；无选择则 ledger_unit_id=null | 真实单元列表；不可默认把“这笔”写入 root |
| create-sub-activity/{activityId} | create_sub_activity | activity_id、name 草稿 | large 类型、Member、名单锁定影响 |
| ledger-unit/{activityId}/{ledgerUnitId} | ledger_unit | 双 scope、选中 Expense/附件 | 单元有效性/历史来源保护 |
| new-expense/{activityId}?... | expense_form | create/edit/refund；ExpenseFormDraft 白名单及来源、expense_id/original_expense_id | FX、永久锁、refund 来源/额度、参与人有效性 |
| expense-detail/{expenseId}?... | expense_detail | selected Expense、可选活动/单元 scope、展示版本 | 缺 activity_id 由 get/解析层查可见归属，进度读 RPC |
| transfer/{activityId}?mode=... | transfer | transfer/receive、明确双方、金额币种、FIFO/TARGETED 及目标、behalf | claim、可付额度、候选、版本；receive 不倒置数据库 from/to |
| transfer-detail/{activityId}/{transferId}?... | transfer_detail | Transfer ID、争议选中项、void_reason 草稿 | active/voided、recorded_by、组件、争议权限 |
| fund-records/{activityId}?ledgerUnitId=... | fund_records | 类型/时间/排序、selected_entity 的真实类型和 ID | Refund/Usage/Transfer 三种实体不能互换；单元只是过滤 |
| prepayment/{activityId}?mode=... | prepayment | fund/return、Owner/Custodian、账户币种、金额和发生时间 | 可用余额/先还债分配、actor、版本 |
| final-settlement/{activityId} | final_settlement | mode、服务端建议 ID、显示版本、确认选中项 | 最新完整方案与版本；没有 ledger_unit 执行范围 |
| activity-management/{activityId} | activity_management | 设置草稿、成员/Participant/子活动选择、归档动作 | Creator/Member、名单锁、真实历史来源 |

当前没有统一上下文采集器，草稿有些在 Compose `rememberSaveable`，有些在 ViewModel。未来接入需明确上报 `draft.revision` 与 `screen_instance_id`，不能仅从 route 推断所有字段。页面清单覆盖完成不表示 Android/小程序已经接入。

## 8. Conversation Context

只保留有界消息（建议上限20条）和最小已确认绑定，不传整段数据库或完整个人资料。明确指令覆盖同范围旧绑定；用户换 Activity、账号退出、实体失效或最新选择冲突时，清理对应绑定。历史中模型自行提出但用户未确认的付款人/金额不升级为事实。金额、币种、参与人名单或目标版本改变时旧操作确认失效。

“他/她”只能解析为本会话同活动已经明确的人，不能通过姓名推断性别。“我”需服务端 claim，不存在就询问是否认领/选择操作角色；不能暗中自动 claim。跨活动只能重新解析，即使同名也不是同一 Participant。

## 9. Interaction Context / 最近操作

区分 pending、succeeded、failed、unknown、committed_refresh_failed。最近点击、失败尝试和上传中附件不能充当最近成功账务事实。`recent_actions` 是线索，Gateway 按已保存 result/operation 核对 actor/activity/entity。confirmed-write 但刷新失败时可说“已登记，详情刷新失败”，不能说“失败了再来一笔”。“刚才那个”与 selected_entity 不同，询问用户指的是哪一个。

“上一笔”先明确是当前列表上一条、时间最近还是用户最近登记；只有 UI 已明确指向唯一条目、当前筛选排序已知且用户用语一致时可使用该 ID。不能用数据库 UUID 排序当发生顺序。`昨天` 按用户时区解析为 [昨日00:00, 今日00:00)，查询结果有多笔则给候选；记录日期没有时分时不猜真实资金发生时刻。

## 10. Entity Resolution

优先使用本轮明确 ID/用户选择，再参考同范围 selected_entity、用户手填草稿、已确认会话绑定、可验证最近成功动作；这不是无条件覆盖优先级。任意来源冲突都返回 clarification。名字仅用于检索，必须返回带实体类型/活动范围的真实 ID。禁止编造 ID、按列表第一项选择、用模糊匹配分数代替用户选择。

同名 Participant 返回候选姓名、顺序及必要的认领区别；不要泄露非成员身份或联系方式。存在多候选/分页截断时不能宣称唯一。root/sub 名称同样走作用域验证。selected_entity 为 Usage 时，不能把它送入 void_transfer。

## 11. Clarification Rules

所有执行型 Intent 在关键字段缺失、实体歧义或事实未确认时都必须 clarification；不是只有某几个固定 Intent 才需澄清。

| 字段/场景 | 可自动使用的证据 | 必须询问的情况 |
| --- | --- | --- |
| Activity/LedgerUnit/Expense/Transfer | 当前明确选择、同范围且服务端验证的 ID | 首页无目标、大型未选单元、多匹配、上下文冲突 |
| 付款人、参与名单、本人是否参与、分摊方式 | 用户已手填/点选，或本会话明确确认且无冲突 | UI 自动选首人/全员AA，不算明确选择；仅“张三李四一起”不足 |
| 金额、币种、时间、真实发生与否 | 本轮明确内容或已确认草稿；“现在”由确定性时间服务转换 | 币种不明、多付款只给总额、只有日期却需发生时刻；计划转账尚未发生 |
| 手动每人金额 | 用户明确指定各金额 | 不能由模型平摊/凑整/替用户决定尾差；选择AA则交RPC |
| Refund 来源、收款人、受益人 | 用户选中的原单及明确分配 | 未知来源不自动变成负调整；不按原比例猜收款/受益名单 |
| Owner/Custodian、返还账户/币种 | 确认的账户维度 | “退给我”但未claim、多账户、方向不明 |
| TARGETED、Final mode、behalf | 明确选择/确认的同版本方案 | FIFO 与 TARGETED 不擅自替换；Final 整项选择不清 |
| note/icon、分页 | 可建议 note=null、icon=money、limit=20、cursor=null | 这些非资金默认值必须在预览可见；不能改动已有备注 |
| 权限/金额上限/版本/FX | 仅最新服务端结果 | 客户端仅有缓存时先读Tool，不让用户确认替代后端校验 |

可从会话继承的是明确确认的语义值，不是模型上一轮猜测。用户一次可回答多个缺失字段；合并后重新验证，不重复询问已经明确的内容。上述示例“晚饭300，张三李四一起”要澄清付款人、是否包括本人、分摊方式，若币种未明确还需币种。页面在 CNY 活动也不能把未触碰的 currency 默认值当用户选择；是否允许特定默认值自动采用留在 Q3。

## 12. Tool Catalog

所有 Tool 均需新 Gateway 封装；“existing_rpc”表示业务可以落到现有正式 RPC，**不是 AI Tool 已部署**。查询组合、规则检索、确认/去重/结果裁剪都属于 `requires_new_ai_gateway_adapter=true`。没有数据库新能力的需求借该标记偷偷开放，未支持的能力没有写 Tool。

| Tool | 用途 | 读写 | 对应 RPC / Query | 特别约束 |
| --- | --- | --- | --- | --- |
| `find_activities` | 查询本人可访问活动 | read | `activities + activity_members (RLS)` | 成员范围读取 |
| `get_activity_context` | 活动、名单、认领、LedgerUnit 和财务状态 | read | `activities`, `activity_members`, `participants`, `participant_claims`, `ledger_units`, `activity_financial_status`, `profiles` | 成员范围读取 |
| `create_activity` | 创建普通/大型 Activity | write | `create_activity` | 名称/币种/类型校验，服务端建立 root 与 Creator 成员关系 |
| `join_activity` | 通过邀请码加入活动 | write | `join_activity_by_code` | 加入不等于认领；邀请码只发给 Gateway，不写入长期会话摘要。 |
| `update_activity` | 更新活动设置 | write | `update_activity_settings` | 首次财务写入后 base_currency 不可变；未归档/未删除 |
| `archive_activity` | 归档活动 | write | `archive_activity` | archive 允许未结清，但展示服务端逐币种 warning；delete 要求当前未归档 |
| `unarchive_activity` | 解除归档 | write | `unarchive_activity` | archive 允许未结清，但展示服务端逐币种 warning；delete 要求当前未归档 |
| `delete_activity` | 软删除活动 | write | `delete_activity` | archive 允许未结清，但展示服务端逐币种 warning；delete 要求当前未归档 |
| `remove_member` | 移除访问成员 | write | `remove_activity_member` | 移除 User 成员不同于删除 Participant；不能暗示历史账务被删除。 |
| `transfer_creator` | 转移创建者身份 | write | `transfer_activity_creator` | 成员范围读取 |
| `find_participants` | 在 Activity 内解析参与人 | read | `participants + participant_claims` | 成员范围读取 |
| `add_participant` | 新增参与人 | write | `create_participant` | 名单未锁定；participant_order 由服务端分配 |
| `remove_participant` | 删除参与人 | write | `delete_participant` | 名单未锁定；未认领且无 Payment/Split/Transfer 引用 |
| `claim_participant` | 认领为当前用户 | write | `claim_participant` | 同 Activity 一人一账号；名单锁定不阻止认领 |
| `unclaim_participant` | 解除当前用户认领 | write | `unclaim_participant` | 仅当前 auth.uid 的认领；不是移除成员 |
| `get_ledger_unit` | 读取 root 或子活动 | read | `ledger_units` | 成员范围读取 |
| `create_sub_activity` | 创建子活动 | write | `create_sub_activity` | large Activity、有效 Member；触发总名单锁定 |
| `delete_sub_activity` | 软删除子活动 | write | `delete_sub_activity` | 必须为 sub_activity，不能操作 root；有真实 Transfer 来源历史则拒绝 |
| `restore_sub_activity` | 恢复子活动 | write | `restore_sub_activity` | 必须为 sub_activity，不能操作 root；有真实 Transfer 来源历史则拒绝 |
| `get_expense` | 读取消费/退款及服务端还款进度 | read | `get_expense_repayment_progress`, `expenses`, `ledger_units`, `payments`, `splits`, `activities` | 仅 expense_id 时 Gateway 从可见 Expense→LedgerUnit 解析 Activity，再调用进度 RPC p_activity_id、p_expense_id；若提供 activity_id 必须一致；已删除读取不推出可恢复。 |
| `find_expenses` | 筛选消费、退款、负向调整 | read | `expenses + ledger_units + payments + splits` | 成员范围读取 |
| `create_expense` | 创建消费、负调整或 linked Refund | write | `create_expense_auto_rate` | Payment/Split 独立守恒、同 Activity 有效名单、金额精度与符号；服务端 FX；linked Refund 同 Activity 有效正来源、同币及完整 FX 继承、有效退款累计上限；永久 financial_locked、归档、历史来源保护 |
| `update_expense` | 更新未锁定消费/退款财务字段 | write | `update_expense_auto_rate` | Payment/Split 独立守恒、同 Activity 有效名单、金额精度与符号；服务端 FX；linked Refund 同 Activity 有效正来源、同币及完整 FX 继承、有效退款累计上限；永久 financial_locked、归档、历史来源保护 |
| `update_expense_presentation` | 仅编辑标题、备注、图标 | write | `update_expense_presentation` | 即使财务锁定仍可展示更新；Expense 当前版本及未删除/未归档 |
| `delete_expense` | 逻辑删除消费或退款 | write | `delete_expense` | 未 financial_locked，无真实 Transfer 来源、无永久 linked Refund 来源历史 |
| `get_transfer` | 读取真实资金记录、组件与争议 | read | `transfers`, `transfer_components`, `transfer_disputes`, `transfer_expense_allocations`, `activities` |  source_allocations 读取不可变历史来源，void 后仍保留；不把它当作当前有效贡献。 |
| `find_fund_records` | 查询真实 Transfer、退款和自动预存 Usage | read | `transfers`, `transfer_components`, `expenses`, `ledger_units`, `prepayment_usages`, `prepayment_accounts`, `transfer_source_expenses`, `expense_debts (Usage→expense_id)`, `transfer_expense_allocations`, `activities` |  Usage 通过 expense_debt_id 关联 Expense；prepayment=(prepayment_amount,prepayment_currency)，debt=(debt_amount,debt_currency)，base=(base_amount,Activity.base_currency)，不得混用 amount。 source_allocations 读取不可变历史来源，void 后仍保留；不把它当作当前有效贡献。 |
| `get_settlement_options` | 当前方向可付币种、额度及目标账单候选 | read | `list_settlement_options`, `list_transfer_expense_candidates` | list_settlement_options(p_activity_id) 后按双方过滤；payment 为服务端最大额度。 |
| `preview_settlement_transfer` | 预览 FIFO/TARGETED 真实还款分配 | read | `preview_expense_repayment` | 目标为当前候选；额度、模式、版本；预览不保留额度 |
| `create_settlement_transfer` | 登记已经真实发生的还款 | write | `create_expense_repayment_v2` | 事务内重查版本、候选、当前额度、actor、完整 payload 和 request_id；确认款项已实际发生；不调用银行支付 |
| `void_transfer` | 按真实 Transfer 类型作废 | write | `void_settlement_transfer`, `void_prepayment_transfer` | active→voided 一次；理由非空；资金历史保留，Expense 不解锁；预存来源仍被有效 Return 占用时拒绝，不自动作废 Return |
| `get_prepayment_accounts` | 读取逐币种预存账户与 Usage | read | `prepayment_accounts`, `prepayment_usages`, `activities`, `expense_debts (Usage→expense_id)` |  Usage 通过 expense_debt_id 关联 Expense；prepayment=(prepayment_amount,prepayment_currency)，debt=(debt_amount,debt_currency)，base=(base_amount,Activity.base_currency)，不得混用 amount。 |
| `preview_prepayment` | 预览先还债后预存的服务端分配 | read | `preview_prepayment` | 同 Activity 不同有效双方；新外币开关与精度 |
| `create_prepayment` | 登记 Owner→Custodian 已发生预存 | write | `create_prepayment_v2` | 任一 Member 可登记；不要求认领；behalf 必须为 null；按服务端债务和预存投影分配；版本、request replay |
| `create_prepayment_return` | 登记 Custodian→Owner 已实际返还 | write | `create_prepayment_return_v2` | 方向固定 Custodian→Owner，金额不超账户当前可用余额，账户原币；已存在外币账户在关闭新外币开关后仍可返还；版本、request replay |
| `get_debt` | 读取当前双边债务并可读取单笔债务 | read | `get_expense_repayment_progress`, `bilateral_debts`, `activities` | 仅当 expense_id 指定才调用进度 RPC；双边净债务与某笔 ExpenseDebt 不等价。 |
| `get_participant_balance` | 读取 base 参考及逐币种应收应付 | read | `participant_financial_status`, `activities` | 成员范围读取 |
| `get_final_settlement` | 获取整个 Activity 的服务端完整建议 | read | `preview_final_settlement_v2` | 成员范围读取 |
| `execute_final_settlement` | 登记一条完整建议对应的真实付款 | write | `execute_final_settlement_v2` | Member，不要求认领双方；建议 ID 来自同 actor/activity/mode/version 的服务端读取；注入条目双方、完整金额、币种，事务重查计划；一次一项，不自动执行剩余项 |
| `add_transfer_dispute` | 提出真实 Transfer 的争议 | write | `add_transfer_dispute` | participant 必须为转账一方；Transfer 有效；只记争议不改资金/completed |
| `resolve_transfer_dispute` | 解除争议标记 | write | `remove_transfer_dispute` | 成员范围读取 |
| `list_attachments` | 读取现有图片附件元数据 | read | `attachments` | 成员范围读取 |
| `get_currency_context` | 查询服务端汇率与支持币种 | read | `get_exchange_rate`, `list_supported_exchange_currencies`, `get_exchange_rate_sync_status` | 映射 p_base_currency/p_quote_currency；查询结果不是 Expense 写入快照授权；不向模型开放 FX 同步。 |
| `lookup_business_rule` | 检索冻结规则或已归一错误说明 | read |  | 成员范围读取 |

读 Tool 只做有界查询、RPC 读取或固定规则检索。`get_activity_context` / `get_debt` 等组合读需核对前后 financial_version，不能拼出跨版本金融快照；元数据和 claim 还需单独刷新，不能认为 financial_version 覆盖所有权限变化。

`get_final_settlement` 的 suggestion_id 由 Gateway 绑定 actor/activity/mode/version/原始完整条目，不是数据库已有 plan 主键。执行仅接受这个引用，Gateway 取回原始金额和方向再调用 RPC。用户“全部结算”先看计划，逐项确认真实付款，不能一次创建一串假 Transfer。

## 13. Tool Input / Output Schema 与 RPC 映射

每个 `tools[i].input_schema` / `output_schema` 都是 JSON Schema；共同类型定义在 catalog `$defs`，稳定引用为 `tool_catalog.json#/$defs/<tool_name>_input` / `_output`。作为独立 schema 使用时必须带 catalog 的 `$defs` 或使用绝对引用，不能丢失解析上下文。input 使用封闭对象，拒绝 SQL、fx_rate、service key、模型自造确认令牌和财务 request_id。

金额一律十进制字符串（不允许科学计数法或二进制浮点金额），币种三位大写；传输最多4位小数，base 1位精度由服务端按 Activity 币种检查，不能通过四舍五入“修复”不合法输入。版本使用非负整数字符串，Gateway 严格解析 bigint，绝不把缺失/解析失败填成0。Schema 不代替精度、非零、同号、唯一与守恒校验。

成功结果包含 `status=success/result_id/observed_at/financial_version/data`。`financial_version=null` 表示该结果不携带或无法提供此版本，不能升级成版本0。列表返回 next_cursor/truncated；空数组表示成功读取为空，error 不是空数组。输出数组上限为100，超限必须分页或明确报结果过大，不能静默丢行；活动快照、单笔多人账单、预览分配与 Final 建议超过协议上限时 v0.1 拒绝返回并走客户端，不能交模型处理截断版资金计划。

写成功 data 为 receipt：operation_id 是 Gateway 追踪标识，不保证 RPC 幂等；entity/version 来自实际回执。`changed=null` 表示 RPC 未提供且无法可靠断言。查询刷新失败与未知提交用独立 status，不与业务拒绝混同。返回实体均为语义 DTO，数据库表名和 SQL 仅保留在研发目录中，不作为模型可调用名称。

确定性映射约定：

1. `create/update_expense` 只调用 auto_rate；去掉仅用于归属核对的 activity_id。AA 传名单和空 manual_splits，manual 传金额和空 aa_participant_ids。Refund 的负号来自明确语义，Gateway 可确定性规范化，但不得替用户变更实际分配。
2. `update_expense_presentation.expected_version` 是 Expense version。普通财务 update_auto_rate 没有此参数，详见 Q4，不能虚构原子 CAS。
3. Activity archive/unarchive、FX/final read、Expense repayment progress 使用签名中 `p_` 前缀；子活动 ledger_unit_id→sub_activity_id；其他字段按 catalog 的 parameter_mapping。额外 scope 字段先校验再剥离。
4. void 根据重读的 Transfer.type 分派：settlement 使用 void_settlement_transfer；prepayment/prepayment_return/final_settlement 使用 void_prepayment_transfer。不能作废 Usage；不先自动作废有效 Return。
5. v2 的 request_id 由 Gateway 生成并持久化；expected_financial_version 来自已验证服务端读/预览。create_prepayment 强制 behalf=null；Final 不要求 claim，本稿不暴露多余 behalf 选择。
6. get_expense 将 Expense 原币/base/FX/Payment/Split 及 get_expense_repayment_progress 的 owed/offset/settled/prepayment/remaining 分开输出。get_debt 双边和单单进度分开。预览 payment/original/base 三组 Money 分别带币种。
7. activity_financial_status.total_debt→base_debt_reference；total_prepayment→base_prepayment_subtotal；保留 prepayment_by_currency。participant_financial_status 的兼容汇总→base_reference，保留 balance_by_currency。不生成不存在的跨币合计。
8. Prepayment preview 的 new_balance→new_balance、financial_version→source_financial_version；数值都属于请求币种。Final 的 amount→payment，ordinary_amount/prepayment_return_amount 使用 payment.currency；source_financial_version 原样保留。
9. FundRecord 以 kind 区分真实 Transfer、负 Expense Refund、自动 Usage；附件 status 保留 pending/ready/deleted，filename 映射 original_filename。只读附件不把 URL 内容交给模型。

catalog 保存所有映射 RPC 的源文件、行号、参数及 returns，以便 Gateway 实现逐项核查；最终实现还必须以最新 ACL 确认暴露范围。`source_definitions` 的 public wrapper 可能在旧 migration 定义，其 private 实现和 ACL 后来已替换，不能只执行单个文件。

## 14. Model Output Protocol

单轮只输出一个 JSON 对象，禁止 Markdown 代码块夹杂自然语言；自然语言只在 content/question/reason 中。允许五种类型：answer、tool_call、clarification、unsupported、error。`tool_call` 是一个封闭联合分支，tool、intent_id 与 arguments 必须匹配；训练系统不能只验证 type 字段。

- answer：回答与 evidence_result_ids。动态账务结论必须引用本轮或验证仍新鲜的结果，且对象/版本一致；纯社交话语可空证据。规则问答引用冻结检索结果。
- tool_call：仅单工具请求。读调用可直接执行；写调用被 Gateway 截获为待确认操作，模型输出不能授权执行。
- clarification：reason、missing_fields、question、带类型候选。missing_fields 可空（如同名/指代歧义）；候选必须来自已验证读取。
- unsupported：说明当前边界，可指引原生 UI。不能偷偷降级到另一种资金操作。
- error：描述读取/上下文/工具失败并引用结果；不能用它替代客户端的登录/网络状态机。

不新增 multi_tool_plan：逐轮读取/澄清/单写足够。`confirmation_required` 属于 Gateway→UI 的可信事件，不属于模型输出；否则模型可能自称已确认。`tool_result_followup` 不另立类型：结果由 Gateway 保存并在下一轮通过 server_context.tool_results 注入，模型仍使用现有五类。Tool 结果不能由客户端聊天文字伪造，不能作为 system 指令。

以下 JSON 也是两个 schema 的 examples 中保存的小型合同例子，不是训练数据集。示例 UUID 仅供离线结构验证：

```json
{
  "type": "clarification",
  "intent_id": "create_expense",
  "reason": "needs_explicit_financial_choice",
  "missing_fields": [
    "payments",
    "aa_participant_ids",
    "split_method",
    "original_currency"
  ],
  "question": "这300是什么币种、谁付款？分摊是否包括你，按AA还是指定金额？",
  "candidates": []
}
```

```json
{
  "type": "tool_call",
  "intent_id": "query_expense",
  "tool": "get_expense",
  "arguments": {
    "activity_id": "00000000-0000-4000-8000-000000000002",
    "expense_id": "00000000-0000-4000-8000-000000000007"
  }
}
```

```json
{
  "type": "tool_call",
  "intent_id": "delete_expense",
  "tool": "delete_expense",
  "arguments": {
    "activity_id": "00000000-0000-4000-8000-000000000002",
    "expense_id": "00000000-0000-4000-8000-000000000007"
  }
}
```

```json
{
  "type": "answer",
  "content": "这笔已被真实转账触及，财务字段不能修改；标题、备注和图标仍可按权限修改。",
  "evidence_result_ids": [
    "expense-read-1",
    "rule-read-1"
  ]
}
```

```json
{
  "type": "unsupported",
  "reason": "已作废的 Transfer 不能恢复。",
  "suggested_action": "如果后来发生了新的真实付款，可以另行登记。"
}
```

```json
{
  "type": "error",
  "reason": "账务状态已变化，请先刷新方案。",
  "code": "tool_failed",
  "evidence_result_ids": [
    "version-conflict-1"
  ]
}
```

第三个例子的 delete tool_call **尚未删除**；必须经过下节的可信 UI 确认。answer 示例假设两个已验证结果已存在；Schema 通过不证明证据真的存在，Gateway 负责检查。

## 15. Confirmation Policy（建议方案，待 Q1 确认）

建议 v0.1 所有写操作都二次确认，读/规则问答/预览不确认。该策略是 AI 防误操作提案，不改变 RPC 业务权限。机器目录 confirmation_required 反映这份待决策方案，发布前需由产品确认。

| 操作 | 待展示内容 | 确认后的限制 |
| --- | --- | --- |
| Expense/Refund 新增、财务编辑/删除 | 活动/单元、原币金额、付款/承担名单、分摊方式、原单链接、修改前后 | 金额/名单不明先澄清；永久锁/Refund 上限 RPC 决定 |
| Transfer/Prepayment/Return/Final | 真实已发生、双方方向、币种金额、预览分配、版本，Final 单条完整建议 | 不代支付、不批量自动执行、不自行选最大额度 |
| void（包括预存来源/返还/Final） | 原记录、理由、仅移除当前效果、历史保留 | 重复void报错，依赖Return不能级联作废 |
| Activity 删除/归档/解除归档 | 目标活动、未结债务/预存逐币 warning、可见性/只读变化 | 归档不是结清，不强制先清零 |
| 子活动删除/恢复、名单/认领、成员/Creator 修改 | 真实对象、影响、名单锁定/访问变化 | 原 RPC 权限约束不变；认领不暗中执行 |
| 展示字段编辑、争议 | 前后文本/目标参与方 | 不改变资金；争议权限冲突待裁定 |

可信流程：模型提出写 Tool → Gateway Schema/身份/对象校验并读取预览 → Gateway 固化规范 payload 及摘要 → UI 显示确认卡 → 用户点击确认 → Gateway 复核会话绑定与对象/版本 → 正式 RPC → 回执/异常状态。

Gateway→UI 的建议事件包含 proposal_id、actor、activity、tool、canonical_arguments、payload_digest、服务端预览引用、expires_at、display_summary；客户端确认只提交 proposal_id 与用户动作，不回传可修改金额。proposal_id 绑定 actor/conversation/activity/tool/payload/版本/有效期，单次消费；取消、退出、切换身份或编辑 payload 失效。自然语言“确认”仅在唯一待办且确定性确认流程支持时才可转成 UI 确认动作，模型不能自写 confirmed=true。

前述事件、持久化与确认端点只是 Gateway 草案，没有假称已实现。确认过期时间、原生点击与文字确认的交互细节留待 Q1/Q5。即使持有确认记录，RPC 仍在事务内重验；新财务版本须重新预览、重新确认，不能替换版本后悄悄重试。

## 16. Error Handling、并发与重试

后端现有常见 SQLSTATE 与 message 不构成稳定业务枚举；新增大写 error.code 是 **Gateway 归一建议**。不能仅凭 `23514` 就断言超过转账上限，它也可能代表 Refund 上限/永久锁/其他约束。按 rpc + code + 已知错误条件映射，未知条件保守返回 CONSTRAINT_VIOLATION。不把原始 SQL、堆栈、私有对象名直接交模型。

| 现有来源 | Gateway 类别 | 接收方与处理 |
| --- | --- | --- |
| 28000 / 认证失效 | AUTH_REQUIRED | 客户端登录，不由模型收集密码或自动重发写请求 |
| 42501 / RLS | FORBIDDEN | 客户端刷新会话/权限，模型只给安全说明，不探测对象存在性 |
| P0002 / PGRST116 | NOT_FOUND | 刷新可见对象；可解释“不可用”，不能断言他人数据被删除 |
| 22023 | INVALID_ARGUMENT，明确FX缓存缺失时 FX_UNAVAILABLE | 模型澄清参数；客户端可显示汇率服务状态 |
| 23514 | CONSTRAINT_VIOLATION | 模型解释具体已知约束；不得缩小金额绕过用户原意 |
| 23505 | REQUEST_CONFLICT 或认领等 STATE_CONFLICT | 已用 request_id 不改 payload 重发；认领刷新候选 |
| 55000 | STATE_CONFLICT | 归档、删除、名单锁、永久锁、重复void；解释准确原因 |
| 40001 / 40P01 | VERSION_CONFLICT | 客户端刷新，必要时重新澄清/确认，不自动重新付钱 |
| PGRST202 / missing RPC | CONTRACT_UNAVAILABLE | 客户端提示契约部署问题，绝不回落 legacy 写入口 |
| 超时、连接中断 | NETWORK_ERROR / unknown | 读可有界重试；写先对账，禁止宣称失败或成功 |

v2 还款、预存、返还、Final：保存 actor/activity/operation/request_id/原始规范 payload/原 expected version/时间。已成功的 exact replay 应返回原 request_result；后续归档或软删除不使成功回执变失败。Gateway 对已确认的同一 operation 重放走专用可信恢复路径，不先用“当前活动不可写”挡住 RPC 的历史重放；仍不能允许换用户/换操作/换参数重放。

Expense create/update/delete、void 及其他写 RPC 没有上述 v2 request_id 保证。Gateway proposal 去重不等于数据库跨崩溃 exactly-once：在 RPC 成功而结果持久化失败窗口，标记 unknown，查记录/人工对账，不能另发一遍 create。已知 commit 后刷新失败返回 committed_refresh_failed，receipt 保留；void 重复拒绝是业务状态，不自动当首次成功。必须区分明确业务拒绝、提交未知、已提交但刷新失败。

## 17. 安全边界

Gateway 使用用户认证上下文调用正式 RPC/RLS 查询，绝不让模型传 user_id 充当 actor、使用 service_role 绕过权限、调用 private rebuild、legacy FX/restore 接口或任意SQL。活动名、备注、文件名、历史聊天和 Tool 数据中的指令均是数据，不能扩展 enabled_tools、修改确认策略或改变冻结规格。

每次读写验证活动归属，find 仅查询可见范围；候选和错误不泄露不可访问对象。UI route、role_hint、最大额度、余额、财务版本、operation 成功声明均不可直接信任。模型不能访问 Auth token、密码、手机号等非必要资料、Storage 签名 URL、数据库密钥。

用户数据最小化、会话隔离、日志脱敏、保留周期、同意策略及未来训练使用另需产品决策。图片附件仅现有 jpeg/png/webp 原生流程，v0.1 没有 OCR 或从附件自动生成账单的承诺。

## 18. Android / 小程序统一接口原则

同一个 version、Intent/Tool/DTO 和确认语义；客户端只在 route、采集器、展示组件上不同。UI schema 不绑定 Compose 类名；小程序可以使用自己的 route，但 page_type/scope/mode 相同。认证凭据在 transport header，不进入模型上下文。

AI Gateway 的预期交互是提交前九项 Context → 补可信 server_context → 解析单 JSON 输出 → 单步读 Tool 或写 proposal → 原生确认 → 回执。实际 URL/SDK/Edge Function 名称未确定，不作为已有接口。全局悬浮入口、回到原页面/填草稿 UI、上传选择器仍需后续客户端工作，本稿不添加导航 Tool 或自动提交草稿。

## 19. 后端映射和能力状态

共 **70 个 Intent、44 个 Tool**。其中 61 个 Intent 对应现有业务读取/执行能力，2个控制意图，其余7个为明确拒绝或转原生流程。

可直接复用正式 RPC（31个 Tool，不需要新增业务 RPC）：`create_activity`, `join_activity`, `update_activity`, `archive_activity`, `unarchive_activity`, `delete_activity`, `remove_member`, `transfer_creator`, `add_participant`, `remove_participant`, `claim_participant`, `unclaim_participant`, `create_sub_activity`, `delete_sub_activity`, `restore_sub_activity`, `create_expense`, `update_expense`, `update_expense_presentation`, `delete_expense`, `get_settlement_options`, `preview_settlement_transfer`, `create_settlement_transfer`, `void_transfer`, `preview_prepayment`, `create_prepayment`, `create_prepayment_return`, `get_final_settlement`, `execute_final_settlement`, `add_transfer_dispute`, `resolve_transfer_dispute`, `get_currency_context`。

现有查询/读取组合（12个 Tool）：`find_activities`, `get_activity_context`, `find_participants`, `get_ledger_unit`, `get_expense`, `find_expenses`, `get_transfer`, `find_fund_records`, `get_prepayment_accounts`, `get_debt`, `get_participant_balance`, `list_attachments`。

冻结文档适配：`lookup_business_rule`。全部44个 Tool 均需 Gateway adapter，包含字段投影、范围校验、错误归一、确认闸门；这与后端业务能力已存在不矛盾。

以下不是待加适配器就能开启的业务：恢复 Expense/Transfer、Transfer 财务编辑、LedgerUnit 级预存/独立名单/备注、任意文件URL、银行支付/对账、自动完成/自动归档、跨币日常抵销、无现金多人环债冲销。旧函数、私有函数、测试 fixture 不作为功能依据。

## 20. Dataset Schema 后续约束与验收门槛

现在可以设计 Dataset Schema 草案，但不能把未决产品策略当已冻结训练标签。样本应携带 contract_version、baseline_commit、source turn、输入 Envelope、已验证 Tool 结果、目标单 JSON、字段证据来源、预期 clarification、确认/回执状态以及 unsupported 分类。财务数字标签由确定性 fixture/RPC 生成，模型标签不自行计算债务。

至少覆盖：同名/无claim/跨活动指代、草稿默认与用户明确选择差异、negative adjustment 对比 linked Refund、退款真实收款人与受益人、base=0 微额、AA/manual 尾差不同、关闭外币后的历史清偿、纯环债、永久锁与 Usage 非锁、返还来源作废保护、Final 整项及刷新、成功回执丢失与 exact replay、未归档/已归档、权限变化、分页截断与上下文注入。

MASS500/MASS2000 是历史业务验证证据，不自动等于合格对话训练集：Compiler 金额/参与人漂移、focus miss、Final plan 退化及可观测性限制仍须清洗和确定性标注；不能把 Judge PASS 直接当权威目标。划分数据集时按活动/对话/业务形状防泄漏，保留源版本，不在此阶段生成训练数据。

机器验收：Intent→Tool 引用闭合；所有 write Intent 有 write Tool；Tool→当前源码 RPC/Query 或明确 adapter；所有 input/output 及 Envelope/模型 Schema 通过元 Schema；正例通过、负例拒绝；所有文档 JSON 示例通过对应 schema；跨字段、时效、真实确认、金额守恒与权限另由确定性运行时验收。Schema 不证明事务正确。

## 21. 不一致与 Open Questions（集中待决策）

### 21.1 已发现差异，不修改现有规则或实现

| 编号 | 证据 | 差异与本稿处理 |
| --- | --- | --- |
| D1 | BUSINESS_LOGIC §4；ActivityModels.ActivityPermissions.forRole(Member)；ActivityManagementScreen | 规格/RPC 允许未锁定名单由 Member 增删，UI canManageParticipants=false 限制普通成员。Contract 按规格，后续是否修 UI 单独决定。 |
| D2 | BUSINESS_LOGIC §4；finalization integration migration 的 add/remove_transfer_dispute_impl | 规格概述 Member 可争议，RPC 更严格：必须关联 Transfer 一方且自己认领该方或是记录者；解除还要求提出者或 Creator。未自行裁决，两个争议 Tool 标记 enabled_after_decision=false；Gateway 不得绕 RPC。 |
| D3 | BUSINESS_LOGIC §2；foundation_types/create_activity_impl | 普通单元规格称 root，实现枚举为 default。保留 default/root/sub_activity 并在语义层说明，不建议迁移改名。 |
| D4 | BUSINESS_LOGIC §4/§19；auto_rate RPC 签名与 ExpensePayload | 财务编辑被概述为受版本约束，但 update_expense_auto_rate 没有 expected_version/expected_financial_version；仅 presentation 更新和 v2 资金操作有显式版本入口。不能承诺一般 Expense 原子乐观校验；需要并发交互方案。 |
| D5 | NewExpenseScreen.createDefaultExpenseDraft/allocateRefundPayerAmounts；NewExpenseDraftTest | 默认首人/本人付款、全员AA；退款默认可按原付款比例分配。都是 UI 默认行为，不是 AI 明确语义依据或退款必须同比例的业务规则；Contract 要求字段来源。 |
| D6 | FinalSettlementScreen.FinalSettlementPlanExplanation；FinalSettlementRequestTest | UI 使用“每位参与人的净应收、净应付生成”概括，容易误读为任何环债都能清零；冻结规格保留环债，AI 文案按服务端计划和限制解释。属于解释不足，不认定资金算法 bug。 |
| D7 | TEST_STATUS.md 首段与尾部 | 首段为30文件/223断言，尾部仍写29 active；使用 final review §13 的30/223，标作历史文档计数残留，不改测试。 |

本次未发现并确认新的资金算法缺陷，也没有通过运行生产数据证明完全一致。当前工作区未提交 UI 变化不属于冻结提交测试覆盖；不复用历史264测试通过来声称它们已验证。

### 21.2 需要产品/维护者决定

1. **Q1 写确认范围与形式**：是否采纳 v0.1 所有写操作二次确认？如只对资金/破坏性操作确认，需明确创建活动、认领、展示编辑、争议等例外；文字“确认”能否替代原生点击。默认草案保守，未擅自作为既定产品政策。
2. **Q2 权限表述冲突**：D1 UI 是否之后对齐 Member 名单管理；D2 争议权限以现实现细化规格还是另作业务裁决。争议写工具在裁定前不启用；不会自行改变冻结权限。
3. **Q3 财务字段默认值**：是否允许明确展示后的 base currency/发生时间/FIFO 等被当作用户默认选择；付款人、参与人/本人是否参与和分摊方式建议必须明确。当前草案只自动采用非资金展示/分页默认。
4. **Q4 Expense 并发编辑**：在没有现有 CAS RPC 的情况下，AI 编辑是否先仅导向原生流程，或接受读取前后/确认版本复查仍无法关闭的竞态窗口？本稿不给不存在的事务保证；如要新增后端契约，属于后续单独任务，不能本阶段改 migration。正式启用 update_expense 前必须明确接受范围。
5. **Q5 上下文与隐私**：历史保留期限、允许的摘要字段/候选人数上限、跨设备最近操作、proposal 有效期、去重持久化和恢复窗口、最终 Gateway/认证接入方式；schema 中20条历史/100条列表是可验证草案限制。
6. **Q6 首期 AI 能力范围**：是否按本稿把账号/图片上传删除留原生流程，是否开启成员管理/Creator 转移等低频高影响能力；如何向用户显示 draft 与不可执行能力。现有能力被识别不等于全部必须首期开放。

结论：具备进入 **Dataset Schema 设计稿** 的条件；Q1–Q6 收口、争议权限与 Expense 并发策略定稿、协议重新校验之后，才适合把此稿升级为训练/发布固定契约。当前不建议开始正式生成训练数据或训练。

## 附件 A：全部 migration 检查清单

以下 SHA-256 仅用于本次本地源码追溯，不表示已重新应用 migration。按文件时间累积分析替换，当前数据库实施层以最后生效函数及最终 ACL 为准。

| Migration | SHA-256 |
| --- | --- |
| `20260830100421_backend_foundation_types.sql` | `effbf39c0609aa074e78612bf2d7c510cc3a955ca874b43c9bc391d304b3bcf4` |
| `20260830100423_profiles_and_auth.sql` | `e5cf0d9230156b150cf1afb92428c0c5043193cc972588d5c80d14a8260fc65e` |
| `20260830100424_activities_and_members.sql` | `ab242220864266a058c0203227955b0f2ddf99aff86fb2ef42bc9f99f5ae21fb` |
| `20260830100426_ledger_units_and_participants.sql` | `6e64bcc140927653b53b6ed459f4d6caf9151b53378dfde27675a0824db90ad5` |
| `20260830100429_foundation_rls.sql` | `2b92e78d3d7b83f5dbb3a360560f4b17898047277a15b348ad2d5c83e61faa49` |
| `20260830105311_activity_lifecycle_rpc.sql` | `7fe62353eab45a8a29bda2ff2f18a35eca4156376f03ccea8e07a97be5b7d198` |
| `20260830115348_expense_core_schema.sql` | `5f360d3b8e78e28b4da694f49fc2bdb455b5788ee88a36667ae479403e540edc` |
| `20260830115402_expense_core_rpc.sql` | `afb83d71404d4b6a9476807eb0bf6eb98f43360767d08e789cdd01db81e04d09` |
| `20260830115418_expense_core_rls.sql` | `11d9d3dc363f45cf0a149ae4b3157f6377bd4bb2cfd9c2702d4185592a83535e` |
| `20260830151327_base_amount_normalization.sql` | `46f54b6a6e1ec46d227d016b8d93d004777a76b20e16e02b480a96025b34acf6` |
| `20260830191659_backend_debt_projection.sql` | `58268ac227b17d5484940189218ee3aa88be8a827b79e432d91d90b35e919959` |
| `20260831034645_backend_settlement_transfer.sql` | `891252d21de940979e9a33bc9bd57b67528823022bda0117472a1b8d8d6abf97` |
| `20260831055425_backend_prepayment.sql` | `6496a004e6caa032d52634c7e5e80251a3d01ae63d892a3c6ea8d285d5780c0c` |
| `20260831120000_phase5_fk_indexes.sql` | `eb61a8c44086f1102767f2ef9fe4bb27879747b4e147e58cebb7d235fe07607c` |
| `20260831160108_backend_final_settlement_archive.sql` | `97b0e0a5412a435e6bb976e7163fcecdec77b9a1af21a0f4433cd2d40bba82b1` |
| `20260901124212_backend_finalization_integration_readiness.sql` | `6cdb4600575dd03b7e19762e82d2e0b80d73499126b675270df99e58efd367d5` |
| `20260905151820_expense_deleted_read_restore.sql` | `0e3d72fc29c10de00d14efb1d6a53048a1290cc5c4ab9aa332b571d6c8913a36` |
| `20260908063410_transfer_restore_contract.sql` | `7324c856779a11e16de7edfd379701194bfcc0bb2a60b396ef9a37d774238a46` |
| `20260908092201_allow_members_create_sub_activity.sql` | `83935dc51de2bd421cbae951bcf08bf57e92fc9eaf0585edc5b356fe07fc72cb` |
| `20260910133739_fair_aa_base_allocation.sql` | `266404746e4457b84bb7460756837c8d61047d7067b31421ff00caf6ed9c3e6f` |
| `20260913112306_sub_activity_delete_restore.sql` | `498e170f9723a747fcdf9de0e4f38e4dfd34e37e57f1ef589c2bb9a523f1d373` |
| `20260913112419_ecb_exchange_rate_expense_snapshots.sql` | `6f5b11b4c7cb09dfb96ccfc61c2f6965b40255caa7bf33985ae78fefeaa58025` |
| `20260913120850_schedule_ecb_exchange_rate_sync.sql` | `3d13c23963d249a32728de4590a2f717545a2dbb08f465ea548d61e6cf5b2316` |
| `20260913121250_fix_ecb_cron_net_http_post.sql` | `65094ec31aaf8470513c3ad5d0a7754eaa933a5dd880cdd393a91aedde2d0c0e` |
| `20260913123459_fix_exchange_rate_cache_update_where.sql` | `12c03e358b6ef2763d5f636c81817fed9bafadf95c828cbbd05a933d84000f3b` |
| `20260918054229_profiles_avatar_style_presets.sql` | `ea84572be10304f9b443113267e31ac64e611bd0cde16089196a2de88b530773` |
| `20260919094626_expense_icon_keys.sql` | `6015fd998f9944a9d3413f5e7a32b031ed223a51e5a0e93a5b423f9110b8aaf7` |
| `20260919164707_multi_currency_settlement.sql` | `0bbd478a18adbedb645b5e905c07af76433fa42a532642126a4778ebaf1c07e8` |
| `20260920112458_fix_original_currency_debt_projection.sql` | `4d79f5548a4dad4d6ae2b7e00baf7ed1a9bb6470b132444dbda03b7027105435` |
| `20260920120259_fix_multi_currency_allocation_invariants.sql` | `ea962f18b93e3e36a84fa5817ad3240aff9c7d86c069df7fea3b4918f9d76fe0` |
| `20260920142845_multi_currency_prepayment_final_settlement_core.sql` | `2e41d6cdf18acd1de97bf095c3c5255bfdb48ecea634f3902c8acdb8d38cfad0` |
| `20260920142942_immutable_transfer_delete_restore_contract.sql` | `8e481330fb27387fba5b399459e0e4eed02871c636ace2aa6273db368451cdaa` |
| `20260920151825_fix_transfer_source_expenses_indexes.sql` | `33879e71a100527127733bfe497be97046e589a39da38e417637caaf89bf2fe6` |
| `20260920152349_fix_prepayment_currency_priority.sql` | `28483dca957af7f14cb2a3a32ee551401288959ca16ee6b1725b9c634a0f9f1a` |
| `20260921022101_allow_members_create_prepayment.sql` | `dbe15e28717e5c625e2919e241a1a3fab52aa56a3f56eba79cfed38259cd6c53` |
| `20260921043414_expense_financial_lock_presentation_update.sql` | `eb738fc9e5ee6e09239d7991cd16b76050ec9d47768878ff5d973d9667b3a563` |
| `20260921051720_targeted_expense_repayment_contract.sql` | `d7d198ce22395e512d4049a92c3af22f728914d8da8b36e52f509a404be4be34` |
| `20260922031227_fix_final_settlement_transfer_mode.sql` | `df2c2b4855bb10549c85dd074c1a0ac1529a6e8316a534b498e1959574773ff9` |
| `20260922072033_final_settlement_member_actor_gate.sql` | `7df8287e5c69bd576c03952da6c9c66a181ee6c807d38208c5f57fc8716b2475` |
| `20260923022250_business_logic_finalization.sql` | `4e000b18ec5a66e09a77838b26b854d21c731e4b72a712f2bb160fd314c20b28` |
| `20260923032928_refund_limits_and_legacy_rpc_permissions.sql` | `db76ecfaeb258e0398d36e8779cb89d21e1f1c289c302e114cd7701ce6a9f7af` |
| `20260924020249_fix_aa_original_currency_debt_preservation.sql` | `5cb53e9da9b30fb9cbc3596d445f127a6ade13f087a4f500dff549055920e038` |
| `20260925133211_fix_negative_expense_base_debt_allocation.sql` | `d6a153948c005ec5e9d1c50767103d6864c7d1dc2b36010b6219312c4b62a5d6` |

## 附件 B：证据与验证

- 权限/组织：[ActivityRepository](../../app/src/main/java/com/ffocalors/sharedledger/data/activity/ActivityRepository.kt)、[ActivityModels](../../app/src/main/java/com/ffocalors/sharedledger/data/activity/ActivityModels.kt)、[名单/争议/附件RPC](../../supabase/migrations/20260901124212_backend_finalization_integration_readiness.sql)。
- Expense：[Models](../../app/src/main/java/com/ffocalors/sharedledger/data/expense/ExpenseModels.kt)、[Payload](../../app/src/main/java/com/ffocalors/sharedledger/data/expense/ExpensePayload.kt)、[Repository](../../app/src/main/java/com/ffocalors/sharedledger/data/expense/ExpenseRepository.kt)、[ExpenseViewModel](../../app/src/main/java/com/ffocalors/sharedledger/ui/expense/ExpenseViewModel.kt)。
- 资金：[TransferPayload](../../app/src/main/java/com/ffocalors/sharedledger/data/transfer/TransferPayload.kt)、[FinancialRemoteDataSource](../../app/src/main/java/com/ffocalors/sharedledger/data/financial/FinancialRemoteDataSource.kt)、[FinancialDtos](../../app/src/main/java/com/ffocalors/sharedledger/data/financial/FinancialDtos.kt)、[FinancialReadViewModel](../../app/src/main/java/com/ffocalors/sharedledger/ui/financial/FinancialReadViewModel.kt)。
- 关键测试：[RPC ACL](../../supabase/tests/database/rpc_client_contract.sql)、[Refund](../../supabase/tests/database/linked_refund_contract.sql)、[幂等](../../supabase/tests/database/idempotency_request_replay_contract.sql)、[并发](../../supabase/tests/database/critical_financial_concurrency.sql)、[排序与多币状态](../../supabase/tests/database/critical_financial_ordering.sql)、[AA原币](../../supabase/tests/database/aa_original_currency_debt_contract.sql)、[微额AA](../../supabase/tests/database/mass500_micro_aa_debt_allocation.sql)、[恢复撤权](../../supabase/tests/database/transfer_restore_contract.sql)。
- Android：[FinalSettlementRequestTest](../../app/src/test/java/com/ffocalors/sharedledger/ui/screens/FinalSettlementRequestTest.kt)、[ExpenseRefundTest](../../app/src/test/java/com/ffocalors/sharedledger/data/expense/ExpenseRefundTest.kt)、[TransferPayloadTest](../../app/src/test/java/com/ffocalors/sharedledger/data/transfer/TransferPayloadTest.kt)、[NewExpenseDraftTest](../../app/src/test/java/com/ffocalors/sharedledger/ui/screens/NewExpenseDraftTest.kt)。
- 历史证据为43迁移、30 pgTAP文件/223断言、6并发文件及264 Android tests，通过结论引用 final review，不是本次运行结果。

本次离线验证（2026-09-27）：使用 `jsonschema 4.23.0`、Draft202012Validator、FormatChecker 和 RFC3339 格式验证，本地注册 Schema 引用，结果全部通过。

| 检查 | 结果 |
| --- | --- |
| Schema 元定义 | 107 项通过：88 个 Tool 输入/输出、2 个主 Schema、17 个共享类型 |
| 结构正例 | 323 项通过：逐 Tool 输入/结果各状态、模型单 Tool 调用、可信结果注入 Envelope、文档和 Schema examples |
| 拒绝负例 | 281 项符合预期：缺少必填、额外 SQL/确认标记、非法时间、错误页面 mode/选中实体、恢复接口、退款正负号/来源、空 TARGETED 列表等 |
| 引用闭合 | 107 项 Intent/后端源码引用检查通过；70 个 Intent 的 Tool/参数引用有效，执行型意图均有写 Tool |
| 页面结构 | 17 类正式页面及 unknown 共18种结构通过；字段来源/真实路由/ID归属仍需运行时验证，未进行设备端测试 |
| 文档链接与边界 | 相对文件链接有效；43 个 migration 指纹已列出；工具映射无 legacy/restore 写 RPC |

这组数量是合同结构检查，不是业务事务断言数量。没有重跑 Android、pgTAP、真实 Auth/Edge Function 或生产数据；没有修改、提交或部署业务代码。Schema 检查与正反例输入只在临时校验环境运行，没有创建训练数据集或项目依赖。
