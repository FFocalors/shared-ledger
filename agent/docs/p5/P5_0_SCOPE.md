# P5.0 真实写通路：范围、幂等与验收

状态：**写通路、确定性开发桥与测试已完成；真机证据待用户执行**（2026-10-25）
分支：`agent`
业务基线：`D:/project/Android/shared-ledger`（只读参考；本切片不改业务 schema 或 RPC）

## 1. 范围

| 项 | 纳入 P5.0 | 说明 |
|---|---|---|
| `expense.create` | 是 | 唯一接通的写操作 |
| 真实 RPC | 是 | `public.create_expense_auto_rate`，用户 JWT + anon publishable key，`security invoker` |
| 预览 | 是 | 服务端读取当前 Activity 财务版本、参与人、账本单元后生成；不写库 |
| 版本保护 | 是 | 执行前重读 `activities.financial_version`，不一致作废旧预览 |
| 幂等 | 是 | `execution_id = derive(actor, proposal_id, proposal_revision)`，同一 execution 只派发一次 RPC |
| 回执 | 是 | 成功 / 拒绝 / 关闭 / 未知四种终态 |
| 外币消费 | 否 | P5.0 只接受 `original_currency == activity.base_currency`；外币留给后续切片，避免在预览里重算 FX |
| 编辑 / 删除 / 展示更新 | 否 | 后续切片 |
| 退款 / 转账 / 预存 / 结算 / 管理类 | 否 | 依赖 T4 数据 |
| 业务 migration / RPC 改动 | 否 | 本切片零业务 schema 变更 |
| 训练数据 | 否 | 不改 `docs/ai/dataset`、`dataset_contracts` 或任何训练资产 |
| LAN | 否 | 只用真机 USB 联调 |

### 1.1 预览来源：已选方案 A

P2 运行时的 v3 模型输出契约是只读识别（`P2ProposalRecognition` 只有 operation 与识别文本），不能生成预览字段。P5.0 因此采用**默认关闭的确定性开发桥**：

- `AGENT_P5_DEV_INTENT_ENABLED=true` 时，运行时不调用模型，而是解析以 `记账` 开头的输入，按当前服务端 scope 绑定参与人/账本单元，生成 live 预览。
- 只支持非 v3 P2 profile（`AGENT_P2_V3_CANDIDATE_ENABLED=false`）；v3 下该桥被配置检查拒绝。
- 只支持 Activity 基础币种、等额分摊；外币、手动分摊留给后续切片。
- 不是产品模型路径：预览摘要带 `【P5 开发验证】`，`policy_version=p5-dev-intent-v1`，默认关闭，日志明确记录。

语法与示例见 `P5_0_RUNBOOK.md` §2。该桥只验证写通路、幂等、版本保护与 App 202 流程，不构成模型质量评测。

## 2. 能力卡

| 字段 | 值 |
|---|---|
| CAP / Intent / Tool | CAP07 / `expense.create` / `create_expense_auto_rate` |
| 允许的操作 | 仅正金额、非关联退款、同币种（`original_currency == base_currency`） |
| 前置读 | Activity（`financial_version`、`base_currency`、`archived_at`、`is_deleted`）、成员校验、参与人、账本单元 |
| 拒绝分支 | 非成员、Activity 归档/删除、外币、负数、非 `equal/manual` 分摊、金额不守恒 |
| 幂等键 | `execution_id`（由 actor + proposal_id + revision 派生） |
| 版本条件 | `FixedExpenseCreateCommand.expected_financial_version` + 执行前重读 |
| 回滚开关 | `AGENT_LIVE_WRITE_ENABLED=false`，确认接口回到冻结的 501 |
| 数据覆盖 | T1 CAP07（已训练） |
| 模型评测 | 未接入；见 §1.1 |
| 业务写入 | 真实 `create_expense_auto_rate` |

## 3. 契约对齐

| Agent 字段 | RPC 参数 | 转换 |
|---|---|---|
| `ledger_unit_id` | `ledger_unit_id` | 直接 |
| `title` | `title` | 直接 |
| `original_amount` | `original_amount` | 十进制字符串 → numeric |
| `original_currency` | `original_currency` | 大写三字母 |
| `split` | `split_method` + `aa_participant_ids` / `manual_splits` | equal → `equal` + ID 数组；manual → `manual` + `[{participant_id, amount}]` |
| `payment_allocations` | `payments` | `[{participant_id, amount}]` |
| `occurred_at` | `occurred_at` | ISO-8601 带时区；预览时固定 |
| `note` | `note` | 直接 |
| — | `original_expense_id` | 固定 `null` |
| `expected_financial_version` | 无对应参数 | 只在 Gateway 执行前重读校验；RPC 本身不校验 |

**已知竞态**：`create_expense_auto_rate` 没有 `expected_financial_version` 参数，重读与 RPC 之间仍有窗口。P5.0 不宣称消除该窗口；RPC 服务端仍会重新校验权限、成员、归档与账本归属。

## 4. 幂等方案

1. 确认请求通过 `confirm_and_dispatch` 原子地写入 `execution` 并进入 `EXECUTING`，之后才允许发 RPC。
2. 同一 proposal 的重复确认（无论 `client_request_id` 是否相同）复用同一个 `execution_id`；若已派发，直接返回同一 202，不再发 RPC。
3. 进程在 RPC 前崩溃：Turn 停在 `EXECUTING`，不会自动重发；核对路径按原 `execution_id` 处理。
4. RPC 结果不明（超时/连接断开/5xx 且无法判定是否已提交）：Turn 进入 `RECOVERING` + `UNKNOWN`，绝不显示成功；核对只使用原 execution 与原命令。
5. `create_expense_auto_rate` 没有服务端 `request_id`，所以**传输层结果不明时无法用数据库唯一键精确找回**。核对方式是按原命令的自然键（activity、title、amount、currency、payer、split、occurred_at）做有界只读匹配；匹配不唯一时保持 `UNKNOWN`。这是 P5.0 的已知限制，后续切片再讨论是否新增 `request_id`。

## 5. 四种终态

| 终态 | 触发 | Turn | Proposal | 是否发 RPC |
|---|---|---|---|---|
| 成功 | RPC 返回 expense 行 | `COMPLETED` / `succeeded` | `confirmed` | 是，一次 |
| 拒绝 | RPC 返回确定性业务错误（权限、归档、参数、守恒） | `FAILED` / `rejected` | `rejected` | 是，一次 |
| 关闭 | 预览过期、版本不一致、scope 失效、Agent 被禁用、用户取消 | `CANCELLED` / `closed`（未派发时无 execution） | `closed` | 否 |
| 未知 | 传输结果不明 | `RECOVERING` / `unknown` | `confirmed` | 是，一次；不重发 |

## 6. 验收标准

1. **未确认不写**：预览存在、Turn 在 `WAIT_CONFIRM` 时，业务库没有新增 Expense，也没有 RPC 调用。
2. **重复确认只写一次**：同一 proposal 连续确认 3 次，只有 1 次 RPC、1 条 Expense；三次返回同一 `execution_id`。
3. **并发改账作废旧预览**：确认前 `activities.financial_version` 变化 → 不发 RPC，Proposal 关闭，App 显示需要重新预览。
4. **结果不明不冒充成功**：注入超时/连接断开 → Turn `RECOVERING` + `UNKNOWN`，重复确认不重发 RPC。

附加回归：非成员、归档 Activity、外币、负金额均在 Gateway 或服务端被拒绝，且不产生写入。

## 7. 测试与证据

- 单元/契约：`agent/tests/test_p5_live_write.py`（假 PostgREST 传输，断言请求体与四终态）。
- API：`agent/tests/test_p5_confirm_api.py`（未确认、重复确认、并发改账走 confirm 路由）。
- 开发桥：`agent/tests/test_p5_dev_bridge.py`（`记账` 解析 + 不调用模型生成 live 预览 + confirm 到真实 RPC 形状）。
- 全量（2026-10-25，本提交）：`788 passed, 1 xfailed`。
  调用方式：

  ```powershell
  $env:PYTHONPATH="$PWD;$PWD\agent;$PWD\agent\tests"
  $env:P2_STORE_TEST_ROOT="D:\tmp\p5-<guid>-store"
  $env:P2_V3_STORE_TEST_ROOT="D:\tmp\p5-<guid>-v3"
  New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT, $env:P2_V3_STORE_TEST_ROOT
  .\agent\.venv\Scripts\python.exe -m pytest agent\tests -q
  ```

  两个目录必须每轮新建；复用目录会产生与代码无关的假失败。
- 真机：`agent/docs/p5/P5_0_RUNBOOK.md`，由用户执行；本切片不启动模拟器。
- 证据记录真机设备、App 构建、Agent 提交哈希、写入的 Expense ID 与四条验收结果。

## 7.1 P2 v3 execution pin

本切片修改了 `agent/app/store.py`、`api.py`、`components.py`、`settings.py`、`p2_runtime.py`，它们都在 P2 v3 execution manifest 的 49 个 component 中。**文档中的“当前 pin”因此失效**；live P2 v3 运行会 fail-closed。需要时用 `python -m agent.app.p2_v3_manifest_cli` 重新生成，并显式记录新 pin；不要静默替换，也不要声称旧证据在新源码上有效。

## 8. 回滚

- `AGENT_LIVE_WRITE_ENABLED=false`（默认）：confirm 回到冻结的 501，App 显示“执行暂不可用”。
- Gateway 任何非 `expense.create` 操作一律 `closed`，不落到 RPC。
- 业务库不需要回滚：本切片不改 schema；已写入的测试 Expense 由用户在专用测试 Activity 中手动删除。
