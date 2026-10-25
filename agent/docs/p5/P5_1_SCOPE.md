# P5.1 消费财务编辑：范围、边界与验收

状态：**实现完成，自动化验收通过；真机由所有者统一验收**（2026-10-25）
分支：`agent`
业务基线：`D:/project/Android/shared-ledger`（本切片不改业务 schema 或 RPC）

## 1. 范围

| 项 | 纳入 P5.1 | 说明 |
|---|---|---|
| `expense.update` | 是 | 唯一新增的写操作 |
| 真实 RPC | 是 | `public.update_expense_auto_rate`，用户 JWT + anon key，`security invoker` |
| 预览 | 是 | 服务端读取当前 Expense + Activity 后生成 before/after；不写库 |
| 双版本保护 | 是 | 执行前重读 `expenses.version` 与 `activities.financial_version` |
| 幂等 | 是 | 同一 proposal 复用 `execution_id`，重复确认不再发 RPC |
| 回执 | 是 | 成功 / 拒绝 / 关闭 / 未知 |
| 标题 / 备注 / 图标 | 否 | P5.2 展示更新 |
| 外币消费 | 否 | 只接受基础币种 |
| 手动分摊改金额 | 仅显式指定分摊时 | 未指定且当前是手动分摊时拒绝 |
| 关联退款（Expense 本身是 Refund） | 否 | `original_expense_id != null` 直接拒绝 |
| 退款来源 / 真实 Transfer 来源 | 否 | 通过 `financial_locked` 标记拒绝 |
| 业务 migration / RPC | 否 | 本切片零业务 schema 变更 |
| 训练数据 / LAN / 新 pin | 否 | 按所有者要求 |

## 2. 契约对齐

`FixedExpenseUpdateCommand` 是冻结契约，只有 `patch`，没有完整状态；`update_expense_auto_rate` 却要求完整字段。因此 Gateway 在预览时把 patch 与当前状态合并，命令里保存**完整合并结果**：

| 来源 | 合并字段 |
|---|---|
| patch 显式提供 | title / original_amount / original_currency / payment_allocations / split / note / occurred_at |
| 当前 Expense | 未提供的字段；`ledger_unit_id` 始终沿用当前值（intent 无此字段） |
| 服务端计算 | `base_amount`（基础币种为 `round(amount, 1)`） |

RPC 参数：

| 命令字段 | RPC 参数 |
|---|---|
| `expense_id` | `expense_id` |
| `patch.ledger_unit_id` | `ledger_unit_id` |
| `patch.title` | `title` |
| `patch.original_amount` / `original_currency` | `original_amount` / `original_currency` |
| `patch.split` | `split_method` + `aa_participant_ids` / `manual_splits` |
| `patch.payment_allocations` | `payments` |
| `patch.occurred_at` / `note` | `occurred_at` / `note` |
| — | `original_expense_id = null`（P5.1 拒绝关联退款） |

## 3. 版本保护

`update_expense_auto_rate` 没有 `expected_expense_version` 或 `expected_financial_version` 参数。P5.1 在**发 RPC 前**重读：

1. `activities.financial_version`（通过 P2 权威读 + 成员校验）
2. `expenses.version`
3. `expenses.is_deleted` / `financial_locked` / `original_expense_id`
4. Activity 未归档、Expense 的 ledger unit 与参与人仍在当前 scope

任一不一致：关闭提案、Turn `CANCELLED`、**不发 RPC**。

**已知竞态**：重读与 RPC 之间仍有窗口。P5.1 不宣称原子 CAS；服务端仍会重新校验权限、成员、归档、锁定与投影。要消除窗口需要后端新增版本参数，属于后续独立任务。

## 4. 拒绝边界

| 边界 | 判定 | 结果 |
|---|---|---|
| `financial_locked=true` | 预览与执行前都检查 | 关闭，`expense_financial_locked` |
| 已删除 | `is_deleted=true` | 关闭，`expense_deleted` |
| Activity 已归档 / 已删除 | `resolve_scope` | 关闭，`scope_denied` |
| Expense 本身是 Refund | `original_expense_id != null` | 关闭，`refund_update_not_in_p5` |
| 退款来源 / 真实 Transfer 来源 | 由 `financial_locked` 覆盖 | 关闭，`expense_financial_locked` |
| 外币 | 当前币种或新币种 != Activity 基础币种 | 关闭，`foreign_currency_not_in_p5` |
| 金额与付款/手动分摊不守恒 | Gateway 合并后校验 | 关闭，`amount_allocation_mismatch` |
| 没有任何字段变化 | 预览 changes 为空 | 关闭，`no_change` |
| Expense 版本变化 | 执行前重读 | 关闭，`expense_changed` |
| Activity 财务版本变化 | 执行前重读 | 关闭，`preview_stale` / `data_changed_during_read` |

说明：`transfer_source_expenses` 与 `private.expense_refund_sources` 不对 `authenticated` 开放，客户端无法直接读取；服务端在这两类来源出现时会把 `expenses.financial_locked` 置为 `true`，Gateway 以该公开标记为准，服务端仍是最终权威。

## 5. 幂等与四终态

1. `execution_id = derive(actor, proposal_id, revision)`。
2. `confirm_and_dispatch` 先原子写入 execution 并进入 `EXECUTING`，之后才发 RPC。
3. 同一 proposal 的重复确认（无论 `client_request_id`）复用同一 `execution_id`，不再发 RPC。
4. RPC 结果不明：Turn 进入 `RECOVERING/UNKNOWN`，绝不显示成功；不自动重发。
5. `update_expense_auto_rate` 没有服务端 `request_id`，所以结果不明时无法用唯一键精确找回；这是 P5.1 的已知限制，与 P5.0 相同。

| 终态 | Turn | Proposal | 是否发 RPC |
|---|---|---|---|
| 成功 | `COMPLETED/succeeded` | `confirmed` | 一次 |
| 拒绝 | `FAILED/rejected` | `rejected` | 一次 |
| 关闭 | `CANCELLED/closed` | `closed` | 否 |
| 未知 | `RECOVERING/unknown` | `confirmed` | 一次，不重发 |

## 6. dev 桥命令

```text
改账 <标题> <新金额> [付款人=<名字>] [分摊=<名字1>,<名字2>]
```

- `<标题>` 是**目标选择器**：在当前 Activity 内按未删除 Expense 的标题精确匹配；必须唯一。
- `<新金额>` 是修改后的原币金额；标题本身不改（改名属于 P5.2）。
- 未指定 `付款人=`：沿用当前唯一付款人，并把其金额改为新金额；多付款人时拒绝。
- 未指定 `分摊=`：当前是等额分摊则沿用参与人；当前是手动分摊则拒绝，要求显式指定。
- 外币标记、匹配不到、标题不唯一、锁定、已删除、关联退款：Turn 直接完成一条拒绝消息，不回落到模型。

命令被拦截时不调用模型；预览摘要带 `【P5 开发验证·改账】`，`policy_version=p5-dev-expense-update-v1`。

## 7. 验收与测试

| 验收 | 测试 | 结果 |
|---|---|---|
| 未确认不写 | `test_p5_update.py::test_update_preview_reads_both_versions_without_rpc` | PASS |
| 重复确认只写一次 | `test_p5_update.py::test_update_duplicate_confirmation_never_sends_a_second_rpc` | PASS |
| Expense 版本并发变化作废旧预览 | `test_update_concurrent_expense_version_closes_without_rpc` | PASS |
| Activity 版本并发变化作废旧预览 | `test_update_concurrent_activity_version_closes_without_rpc` | PASS |
| 锁定 / 已删除 / 关联退款拒绝 | `test_update_rejection_boundaries_close_without_rpc` | PASS |
| 归档 Activity 拒绝 | `test_update_archived_activity_closes_without_rpc` | PASS |
| 未知不冒充成功、不重发 | `test_update_unknown_is_not_retried` | PASS |
| dev 桥生成预览并到达真实 RPC | `test_p5_dev_bridge.py::test_dev_update_bridge_creates_preview_and_reaches_the_update_rpc` | PASS |
| dev 桥锁定拒绝且不调用模型 | `test_p5_dev_bridge.py::test_dev_update_bridge_refuses_a_locked_expense_without_a_model_call` | PASS |

全量调用方式与 P5.0 相同（两个 store 根每轮新建）：

```powershell
$env:PYTHONPATH="$PWD;$PWD\agent;$PWD\agent\tests"
$env:P2_STORE_TEST_ROOT="D:\tmp\p5-<guid>-store"
$env:P2_V3_STORE_TEST_ROOT="D:\tmp\p5-<guid>-v3"
New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT, $env:P2_V3_STORE_TEST_ROOT
.\agent\.venv\Scripts\python.exe -m pytest agent\tests -q
```

结果（2026-10-25，本提交）：`803 passed, 1 xfailed`。

## 8. Pin 与回滚

- 本切片修改了 `agent/app/p5_write.py`、`p5_dev_intent.py`、`p2_runtime.py`、`store.py`；其中 `p2_runtime.py` 与 `store.py` 在 P2 v3 execution manifest 内。**pin 仍然失效，本切片按要求不生成新 pin。**
- 回滚：`AGENT_P5_DEV_INTENT_ENABLED=false` 关闭 dev 桥；`AGENT_LIVE_WRITE_ENABLED=false` 关闭全部真实写，confirm 回到 501。
- 已写入的测试数据由所有者在专用测试 Activity 中处理。
