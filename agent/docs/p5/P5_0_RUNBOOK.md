# P5.0 真机验收 Runbook（USB，不启用 LAN）

状态：**可执行**（确定性开发桥已实现）
日期：2026-10-25
适用提交：本文件所在提交（`git rev-parse HEAD`）

## 1. 环境前提

| 项 | 要求 |
|---|---|
| 手机 | USB 调试已授权，只连接一台设备 |
| Agent | `D:/project/Android/shared-ledger-agent`，分支 `agent`，venv 已安装 |
| 模型 | 不要求可用：`记账` 桥不会调用模型 |
| Supabase | Agent 的 `AGENT_SUPABASE_AUTH_BASE_URL` / `AGENT_SUPABASE_API_KEY` 与 App 当前项目一致 |
| 业务数据 | 只在一个**专用测试 Activity** 中写入；不要使用真实账本 |
| 网络 | `adb reverse tcp:8765 tcp:8765`；**不运行** `dev-up.ps1 -Lan` |

## 2. 预览来源：p5_dev 确定性桥

P2 的非 v3 profile 支持完整的 `expense.create` 语义。开启开发桥后，Agent 对以 `记账` 开头的输入**不调用模型**，而是按当前服务端 scope 直接生成 live 预览：

```text
记账 <标题> <金额> [付款人=<名字>] [分摊=<名字1>,<名字2>] [账本=<名字>]
```

示例：

```text
记账 午餐 12.50
记账 打车 30 付款人=Rin 分摊=Alex
记账 晚餐 88 付款人=Alex 分摊=所有人
```

默认值：

- 付款人 = 当前 Activity 的第一个参与人
- 分摊 = 当前 Activity 的全部参与人（等额）
- 账本单元 = 第一个可用账本单元
- 币种 = Activity 基础币种

限制：

- 只支持基础币种；出现 `USD/美元/$/EUR/欧元/JPY/日元` 会拒绝走桥，交给普通路径。
- 只支持等额分摊；手动分摊留给后续切片。
- 名字必须与当前 scope 的显示名精确或唯一匹配；匹配不到或多义时拒绝走桥。
- 预览摘要带 `【P5 开发验证】`，`policy_version=p5-dev-intent-v1`。它不是产品模型输出，只用于验证写通路。

## 3. Agent 配置

在 `agent/.env`（不要提交）设置：

```dotenv
AGENT_PROVIDER_MODE=p2
AGENT_AGENT_ENABLED=true
AGENT_DISABLE_REVISION=1
AGENT_EXECUTION_ENABLED=true
AGENT_LIVE_WRITE_ENABLED=true
AGENT_P5_DEV_INTENT_ENABLED=true
AGENT_P2_V3_CANDIDATE_ENABLED=false
AGENT_SUPABASE_AUTH_BASE_URL=https://<project>.supabase.co/auth/v1
AGENT_SUPABASE_API_KEY=<publishable/anon key>
```

启动（普通 PowerShell，不要从沙箱进程启动）：

```powershell
cd D:\project\Android\shared-ledger-agent\agent\deploy\scripts
powershell -ExecutionPolicy Bypass -File .\dev-up.ps1
```

确认：

```powershell
curl.exe http://127.0.0.1:8765/health/ready
adb reverse --list
```

`health/ready` 必须报告存储、Auth 与运行时可用；`business_api_available` 必须为 `true`。

## 4. App 配置

`local.properties`：

```properties
agent.baseUrl=http://127.0.0.1:8765
agent.demo=false
```

重建 debug 并安装：

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

打开一个**专用测试 Activity**，再打开 Agent 面板。

## 5. 验收步骤与四条结果

| # | 操作 | 预期 | 证据 |
|---|---|---|---|
| 1 | 输入 `记账 午餐 12.50`，等待确认卡 | 卡片显示金额、币种、付款人、分摊，摘要以 `【P5 开发验证】` 开头；业务库无新 Expense；Agent 日志没有 `create_expense_auto_rate` | 卡片截图；`select count(*) from expenses ...` |
| 2 | 连续点击确认 3 次 | 只有 1 次 RPC、1 条 Expense；三次返回同一 `execution_id` | Agent 日志请求计数；Expense 行；执行回执 |
| 3 | 重新发一条 `记账 ...`，在另一台设备/客户端修改同一 Activity 的任意财务字段，再确认 | 不发 RPC；App 显示预览失效；Proposal `closed`；Turn `CANCELLED` | Agent 日志无 RPC；`activities.financial_version` 前后值 |
| 4 | 确认请求发出后立即断网/拔 USB（或在测试传输层注入超时） | App 只显示“正在核对结果”；Turn `RECOVERING`；重复确认不再发 RPC | 状态 JSON；日志中只有一次派发 |

补充拒绝分支（任选一条）：非成员账号、已归档 Activity、外币命令、负金额都应被拒绝且不产生写入。

## 5.1 P5.1 改账（消费财务编辑）

命令：

```text
改账 <标题> <新金额> [付款人=<名字>] [分摊=<名字1>,<名字2>]
```

示例：

```text
改账 午餐 15.00
改账 打车 30 付款人=Rin 分摊=Alex
```

规则：

- `<标题>` 是目标选择器：当前 Activity 内未删除 Expense 的标题必须**唯一**；标题本身不被修改。
- 未指定 `付款人=` 时沿用当前唯一付款人，并把金额改为新金额；多付款人时拒绝。
- 未指定 `分摊=` 时，等额分摊沿用参与人；手动分摊拒绝，要求显式指定。
- 外币、匹配不到、标题不唯一、`financial_locked`、已删除、关联退款都会直接返回一条拒绝消息，不调用模型。

验收：

| # | 操作 | 预期 |
|---|---|---|
| 5 | 输入 `改账 <现有标题> <新金额>`，等待确认卡 | 卡片摘要以 `【P5 开发验证·改账】` 开头；预览 before/after 金额；业务库未变；无 RPC |
| 6 | 连续确认 3 次 | 只有 1 次 `update_expense_auto_rate`；三次同一 `execution_id` |
| 7 | 预览后，在另一客户端修改同一 Expense 的金额或付款人，再确认 | 不发 RPC；Proposal `closed`；App 提示重新发起 |
| 8 | 对已锁定或已删除的 Expense 发 `改账` | Turn 完成一条拒绝消息；无 RPC；无提案卡 |

如果当前 Expense 是手动分摊且命令没有 `分摊=`，或标题匹配到多笔，也会被拒绝；这是设计行为，不是故障。

## 5.2 P5.2 展示更新（改名 / 改图标 / 改备注）

命令：

```text
改名 <标题> <新标题>
改图标 <标题> <icon_key>
改备注 <标题> <备注文本>
```

示例：

```text
改名 Lunch Dinner
改图标 Lunch dining
改备注 Lunch 团队午餐
```

规则：

- `<标题>` 是目标选择器：当前 Activity 内未删除 Expense 的标题必须唯一；标题可以包含空格，解析使用“最长唯一前缀”。
- 只修改 `title` / `note` / `icon_key`；请求体不包含任何财务字段。
- **`financial_locked` 的 Expense 允许改展示**，这是该 RPC 的用途。
- 已删除、Activity 归档、关联退款不在 Agent 预检拒绝，由 RPC 实际返回；App 会看到对应的拒绝结果。
- `icon_key` 只能是：`money dining shopping transport hotel ticket fuel entertainment medical gift grocery flight`。
- 匹配不到、标题重名、新值为空、没有实际变化、非法 icon_key：Turn 完成一条拒绝消息，不调用模型。

验收：

**四条通用检查点**

1. **未确认不写**：生成预览但不点确认 → 业务库无变化、无 RPC。
2. **重复确认只写一次**：连续确认 3 次 → 只有 1 次 `update_expense_presentation`，三次同一 `execution_id`。
3. **版本冲突作废旧预览**：预览后修改同一 Expense → 预检 0 次 RPC、Proposal `closed`、Turn `CANCELLED`；若 40001 在派发后返回，也关闭为 `closed`，不显示成功。
4. **未知不冒充成功**：确认后断网/注入超时 → Turn `RECOVERING` + `UNKNOWN`；重复确认不再发 RPC。

**展示更新专项**

| # | 操作 | 预期 |
|---|---|---|
| 9 | 对一笔**已锁定**（有退款或真实转账来源）的消费执行 `改图标 <标题> dining` | 生成预览卡；确认后成功；金额/付款/分摊/发生时间完全不变；`financial_locked` 仍为 true |
| 10 | 对未锁定消费执行 `改名 <标题> <新标题>` | 成功；Expense version +1；只有展示字段变化 |
| 11 | 执行 `改名 <标题> <当前同名>`、`改图标 <标题> not_an_icon`、`改名 不存在 X`、标题重名 | Turn 完成拒绝消息；无 RPC；无提案卡 |
| 12 | 预览后，在另一客户端修改同一 Expense 的展示或财务字段，再确认 | 预检版本冲突：0 次 RPC、Proposal `closed`、Turn `CANCELLED` |

证据模板追加：

```text
展示命令: 改名/改图标/改备注 <标题> <新值>
  旧值 -> 新值:
  expected_version:
  execution_id:
  resolution: succeeded / rejected / closed / unknown
  financial_locked: true / false
  财务字段是否变化: 否
```

## 5.3 P5.3 逻辑删除

命令：

```text
删除 <标题>
```

示例：

```text
删除 Lunch
删除 团队午餐
```

规则：

- `<标题>` 必须精确等于当前 Activity 内一笔消费的标题；标题可以包含空格。
- 只有**未锁定**的消费可删；`financial_locked`（真实 Transfer 来源或关联退款历史）拒绝。
- 只有 **Expense 创建者或 Activity Creator** 可删；其他成员拒绝。
- 已删除的消费再删：服务端返回 `changed=false`，视为幂等成功，不重复投影、不报错。
- Activity 已归档/已删除：不在 Agent 预检拒绝，由 RPC 实际返回；App 会看到 `rejected`。
- 匹配不到、重名、已锁定、已删除、非创建者/非 Creator：Turn 完成拒绝消息，不调用模型。
- 不提供恢复；没有 `restore_expense` 可调。

**四条通用检查点**

1. **未确认不写**：生成删除预览但不点确认 → 消费仍存在、无 RPC。
2. **重复确认只写一次**：连续确认 3 次 → 只有 1 次 `delete_expense`，三次同一 `execution_id`。
3. **版本冲突作废旧预览**：预览后修改 Expense 或 Activity 的财务状态 → 0 次 RPC、Proposal `closed`、Turn `CANCELLED`。
4. **未知不冒充成功**：确认后断网/注入超时 → Turn `RECOVERING` + `UNKNOWN`，不重发；核对发现已被删除时落 `closed`，不显示成功。

**删除专项**

| # | 操作 | 预期 |
|---|---|---|
| 13 | 对未锁定、自己创建的消费执行 `删除 <标题>` | 预览显示 `is_deleted: false → true`；确认后成功；消费变为已删除；`changed=true` |
| 14 | 对锁定消费执行 `删除 <标题>` | Turn 完成拒绝消息；无 RPC；无提案卡 |
| 15 | 用非创建者/非 Activity Creator 的账号执行 `删除 <标题>` | Turn 完成拒绝消息；无 RPC |
| 16 | 对已删除的消费再次执行删除（或服务端在竞态中返回 `changed=false`） | 视为幂等成功；不重复重建投影；不报错 |

证据模板：

```text
删除命令: 删除 <标题>
  expense_id:
  expected_expense_version:
  expected_activity_financial_version:
  execution_id:
  changed: true / false
  resolution: succeeded / rejected / closed / unknown
  权限身份: 创建者 / Activity Creator / 其他
  financial_locked: false
```



```text
提交: <git rev-parse HEAD>
设备: <型号 / Android 版本>
App: <versionName> debug
Agent 启动时间:
Activity ID: <专用测试 Activity>
命令: 记账 <标题> <金额> [付款人=...] [分摊=...]
预览:
  proposal_id:
  command_digest:
  expected_financial_version:
执行:
  execution_id:
  expense_id:
  expense.version:
四条结果: 1 PASS / 2 PASS / 3 PASS / 4 PASS
备注:
```

## 5.5a P5.5a 真实还款/转账（只做新增）

命令：

```text
还款 <付款人> <收款人> <金额> <币种> [FIFO|TARGETED]
```

示例：

```text
还款 Alex Rin 10.0 USD
还款 Alex Rin 10.0 USD TARGETED
```

规则：

- 付款人/收款人按当前 Activity 的显示名精确匹配；必须有效、不同、且不能重名。
- 金额必须为正数；币种三字母；模式只能是 FIFO/TARGETED。
- TARGETED 使用当前候选列表的全部 `expense_id`；没有候选时拒绝。
- 服务端预览负责额度、分配、汇率和 `authorize_phase5_actor`；Agent 不自行判断代理。
- `on_behalf_of_participant_id` 固定为 `null`；本切片不做代理。
- 预览摘要带 `【P5 开发验证·还款】`。

**四条通用检查点**

1. **未确认不写**：生成预览但不确认 → 业务库无 Transfer、无创建 RPC。
2. **重复确认只写一次**：连续确认 3 次 → 1 次 `create_expense_repayment_v2`，同一 `request_id`、同一 `execution_id`。
3. **版本冲突作废旧预览**：预览后 Activity 财务版本变化 → 0 次创建 RPC、Proposal `closed`、Turn `CANCELLED`；服务端 40001 在派发后返回也关闭为 `closed`。
4. **未知不冒充成功**：确认后断网/注入超时 → `RECOVERING/UNKNOWN`，不重发；按原 `request_id` 只读核对，找到且 payload 一致才落成功，找不到保持 UNKNOWN。

**还款专项**

| # | 操作 | 预期 |
|---|---|---|
| 17 | FIFO：`还款 Alex Rin 10.0 USD` | 预览成功；确认后生成 1 条 settlement Transfer；请求含 `request_id` 与 `expected_financial_version` |
| 18 | TARGETED：`还款 Alex Rin 10.0 USD TARGETED` | 请求 `target_expense_ids` 非空且为当前候选；确认后成功 |
| 19 | 金额超过该方向可偿还债务 | 预览或创建被服务端拒绝；Turn `rejected`；不产生 Transfer |
| 20 | 无效参与人 / Payer 无权 / Activity 归档 | 服务端拒绝；Turn `rejected`；不产生 Transfer |

证据模板：

```text
还款命令: 还款 <付款人> <收款人> <金额> <币种> <模式>
  activity_id:
  from_participant_id / to_participant_id:
  request_id:
  expected_financial_version:
  execution_id:
  transfer_id:
  allocation_mode: FIFO / TARGETED
  target_expense_ids:
  resolution: succeeded / rejected / closed / unknown
```

## 5.5b P5.5b 真实转账作废

命令：

```text
作废 <付款人> <收款人> <金额> <币种> [原因=<文本>]
```

示例：

```text
作废 Alex Rin 10.0 USD
作废 Alex Rin 10.0 USD 原因=录错了
```

规则：

- 付款人/收款人按当前 Activity 的显示名精确匹配，且必须不同。
- 按 付款人 + 收款人 + 金额 + 币种 在当前 Activity 的 Transfer 列表中匹配；必须唯一。
- Member 只能作废自己录入的；Activity Creator 可作废任意记录；其他成员拒绝。
- 结算转账走 `void_settlement_transfer`；预存/预存返还/最终结算走 `void_prepayment_transfer`。
- 预存来源仍有有效返还依赖时，服务端拒绝；Agent 如实显示 `rejected`，不自动先作废返还。
- 不提供恢复；不调用 `restore_transfer`。
- 预览摘要带 `【P5 开发验证·作废】`。

**四条通用检查点**

1. **未确认不写**：生成预览但不确认 → Transfer 仍未作废、无 void RPC。
2. **重复确认只写一次**：连续确认 3 次 → 1 次 void RPC，同一 `execution_id`。
3. **版本冲突作废旧预览**：预览后 Transfer 状态/录入者/类型或 Activity 状态/财务版本变化 → 0 次 RPC、Proposal `closed`、Turn `CANCELLED`。
4. **未知不冒充成功**：确认后断网/注入超时 → `RECOVERING/UNKNOWN`，不重发；核对到已作废（无法证明是自己）→ `closed`（`voided_elsewhere`）；未作废且版本未变 → `closed`（`void_not_applied`）；版本变化 → `closed`（`activity_changed`）。

**作废专项**

| # | 操作 | 预期 |
|---|---|---|
| 21 | 本人录入的 settlement Transfer 执行 `作废 ...` | 预览成功；确认后 `void_settlement_transfer` 一次；Transfer 变为已作废；`voided=true` |
| 22 | Activity Creator 作废他人录入的 Transfer | 预览/确认成功；RPC 一次 |
| 23 | 普通 Member 作废他人录入的 Transfer | 拒绝；不产生作废 |
| 24 | 对已作废 Transfer 再次作废 | 服务端 `voided=false` 或 55000 后重读 → 幂等成功，不重复重建投影 |
| 25 | 归档/已删除 Activity，或预存来源仍有有效返还依赖 | `rejected`；Transfer 不变 |

证据模板：

```text
作废命令: 作废 <付款人> <收款人> <金额> <币种> 原因=<文本>
  activity_id:
  transfer_id:
  transfer_type: settlement / prepayment / prepayment_return / final_settlement
  recorded_by:
  expected_financial_version:
  execution_id:
  voided: true / false
  resolution: succeeded / rejected / closed / unknown
```

## 5.6 P5.6 大型活动预存新增与返还

命令：

```text
预存 <所有者> <保管人> <金额> <币种>
返还 <所有者> <保管人> <金额> <币种>
```

示例：

```text
预存 Alex Rin 10.0 USD
返还 Alex Rin 3.0 USD
```

规则：

- 只在**大型活动**（`activities.type = 'large'`）中可用；普通活动直接拒绝，不发 RPC。
- 所有者 / 保管人按当前 Activity 的显示名匹配；必须存在且互不相同。
- 币种必须是活动可用币种；基础币种金额只能有一位小数（`10.0` 可以，`10.55` 拒绝）。
- 新增：任何 Member 都可提交，不要求 claim；`on_behalf_of_participant_id` 固定 `null`。
- 新增先偿还 `所有者 -> 保管人` 方向的旧债，剩余部分计入预存账户；预览显示服务端返回的
  **偿债金额**与**入账余额**两部分，不做净额换算。
- 返还：谁能返还是由服务端 `authorize_phase5_actor` 决定，Agent 不自行判断。
- 返还预览只显示账户**当前余额**，并写明「返还后余额以服务端执行结果为准」；不要手工
  计算或填写返还后余额。
- 返还金额超过余额时由服务端事务拒绝，App 显示 `rejected`。
- 预览摘要带 `【P5 开发验证·预存】` / `【P5 开发验证·返还】`。

**四条通用检查点**

1. **未确认不写**：生成预览但不确认 → 无 Transfer、无创建 RPC。
2. **重复确认只写一次**：连续确认 3 次 → 1 次 `create_prepayment_v2` 或
   `create_prepayment_return_v2`，同一 `request_id`、同一 `execution_id`。
3. **版本冲突作废旧预览**：预览后 Activity 财务版本变化、或活动被改成普通类型 →
   0 次 RPC、Proposal `closed`、Turn `CANCELLED`；派发后服务端返回 40001 也关闭为
   `closed`，不显示成功。
4. **未知不冒充成功**：确认后断网/注入超时 → `RECOVERING/UNKNOWN`，不重发；按原
   `request_id` 只读核对 transfers，找到且 payload 一致才落成功，找不到保持 UNKNOWN。

**预存专项**

| # | 操作 | 预期 |
|---|---|---|
| 26 | 在大型活动执行 `预存 <所有者> <保管人> 10.0 <基础币种>` | 预览显示偿债金额 / 入账余额；确认后生成 1 条 `prepayment` Transfer；请求含 `request_id`、`expected_financial_version`、`on_behalf_of=null` |
| 27 | 在普通活动执行 `预存 ...` 或 `返还 ...` | Turn 完成拒绝消息「普通活动不支持预存」；无 RPC；无提案卡 |
| 28 | 执行 `预存 <所有者> <保管人> 99.0 <币种>` 后 `返还 <所有者> <保管人> 3.0 <币种>` | 返还预览显示账户当前余额；确认后生成 1 条 `prepayment_return` Transfer；执行结果显示服务端 `remaining_balance` |
| 29 | 返还金额超过账户余额 | 服务端拒绝；Turn `rejected`；不产生 Transfer |
| 30 | 重复确认 3 次（新增或返还） | 只有 1 次创建 RPC；同一 `request_id`、同一 `execution_id` |
| 31 | 预览后修改活动财务版本，或把活动降级为普通类型，再确认 | 0 次 RPC；Proposal `closed`；Turn `CANCELLED`；`execution` 为空 |

证据模板：

```text
预存/返还命令: 预存|返还 <所有者> <保管人> <金额> <币种>
  activity_id:
  activity_type: large
  owner_participant_id / custodian_participant_id:
  request_id:
  expected_financial_version:
  execution_id:
  transfer_id:
  settlement_amount / prepayment_amount / new_balance（预存）:
  remaining_balance（返还，服务端返回）:
  resolution: succeeded / rejected / closed / unknown
```

## 5.7 P5.7 最终结算执行

命令：

```text
结算 <付款人> <收款人> <金额> <币种> [模式=base_unified|original_currency]
```

示例：

```text
结算 Alex Rin 10.0 USD
结算 Alex Rin 10.0 USD 模式=original_currency
```

规则：

- 预览来自服务端 `preview_final_settlement_v2`，它是**整个 Activity 的建议项列表**，
  不是某人欠谁的即时计算；预览摘要会列出完整建议，不只匹配的那一项。
- 执行只能引用当前建议中的某一项：方向、金额、币种必须与建议逐字段一致，Agent 不合并、
  不拆单、不重排、不做净额化。
- 命令匹配不到完全一致的一项（金额、方向或币种不同）时直接拒绝，不发执行 RPC，也不
  调用模型。
- 模式缺省 `base_unified`；大型活动建议可含预存返还路径，普通活动该路径为空。
- 确认语义是「登记一笔已经真实发生的付款」，不是下发转账指令。
- 预览摘要带 `【P5 开发验证·结算】`。

**四条通用检查点**

1. **未确认不写**：生成预览但不确认 → 无 Transfer、无执行 RPC。
2. **重复确认只写一次**：连续确认 3 次 → 1 次 `execute_final_settlement_v2`，同一
   `request_id`、同一 `execution_id`。
3. **版本冲突作废旧预览**：预览后 Activity 财务版本变化，或活动类型改变（大型降级为
   普通）→ 0 次 RPC、Proposal `closed`、Turn `CANCELLED`；派发后服务端返回 40001 也
   关闭为 `closed`，不显示成功。
4. **未知不冒充成功**：确认后断网/注入超时 → `RECOVERING/UNKNOWN`，不重发；按原
   `request_id` 只读核对 transfers，找到且 payload 一致才落成功，找不到保持 UNKNOWN。

**结算专项**

| # | 操作 | 预期 |
|---|---|---|
| 32 | 预览一次结算命令 | 卡片摘要列出**完整**建议（含未选中的方向），选中项与建议字段一致；确认前无执行 RPC |
| 33 | 确认建议中的一项 | `execute_final_settlement_v2` 一次；生成 1 条 `final_settlement` Transfer；请求含 `request_id`、`expected_financial_version`、`mode`、`on_behalf_of=null` |
| 34 | 金额、方向或币种与建议不一致 | Turn 完成拒绝消息；无执行 RPC；无提案卡 |
| 35 | 普通活动结算 | 建议中没有预存返还路径；正常执行普通债务项 |
| 36 | 大型活动且存在预存余额 | 建议可含预存返还项；选中该项后执行，普通/预存返还拆分与建议一致 |
| 37 | `模式=original_currency` | 预览与执行都用该模式；请求 `mode` 为客户指定值，币种来自建议 |

证据模板：

```text
结算命令: 结算 <付款人> <收款人> <金额> <币种> [模式=...]
  activity_id:
  activity_type: normal / large
  mode: base_unified / original_currency
  from_participant_id / to_participant_id:
  plan_items: <完整建议条数>
  selected: amount / ordinary_amount / prepayment_return_amount
  request_id:
  expected_financial_version:
  execution_id:
  transfer_id:
  resolution: succeeded / rejected / closed / unknown
```

## 7. 回滚

1. 将 `AGENT_P5_DEV_INTENT_ENABLED=false`，`AGENT_LIVE_WRITE_ENABLED=false`，重启 Agent。确认接口回到冻结的 501，`记账` 输入回到普通路径。
2. 如果已写入测试 Expense，在专用测试 Activity 中用 App 原生删除；不要直接改业务表。
3. 不改业务 schema，因此无需数据库回滚。

## 8. Pin 提醒

本次及后续 P5 切片修改了 `agent/app/store.py`、`api.py`、`components.py`、`settings.py`、
`p2_runtime.py`、`p5_write.py`、`contracts.py`，它们都在 P2 v3 execution manifest 的 49 个
component 内。因此：

- **文档里的“当前 pin”已失效**，live P2 v3 运行会被 fail-closed。
- 需要 live 运行时，用 `python -m agent.app.p2_v3_manifest_cli` 重新生成 manifest，并在状态文档中显式记录新 pin。
- 旧的真机证据仍绑定旧源码哈希；重新生成 pin **不会**重新验证旧证据。
