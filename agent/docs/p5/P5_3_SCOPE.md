# P5.3 消费逻辑删除：范围、边界与验收

状态：**实现完成，自动化验收通过；真机由所有者统一验收**（2026-10-26）
分支：`agent`
业务基线：`D:/project/Android/shared-ledger`（本切片不改业务 schema 或 RPC）

## 1. 范围

| 项 | 纳入 P5.3 | 说明 |
|---|---|---|
| `delete_expense` | 是 | 逻辑删除，服务端 `is_deleted=true` |
| 真实 RPC | 是 | `public.delete_expense`，用户 JWT + anon key |
| 版本保护 | 是 | 重读 `expenses.version`、`expenses.is_deleted`、`activities.financial_version` |
| 权限 | 是 | Expense 创建者或 Activity Creator |
| 已删除再删 | 是 | 服务端返回 `changed=false`，视为幂等成功 |
| 恢复 | 否 | 当前没有可调用的 restore RPC；不伪造 |
| 财务编辑 / 展示更新 | 否 | P5.1 / P5.2 |
| 业务 migration / RPC | 否 | 本切片零业务 schema 变更 |
| 训练数据 / LAN / 新 pin | 否 | 按所有者要求 |
| 真机验收 | 否 | 所有者统一验收 |

## 2. 业务边界

| 情况 | 行为 |
|---|---|
| `financial_locked=true`（真实 Transfer 来源或关联退款历史） | Gateway 预检拒绝，0 次 RPC |
| Expense 创建者或 Activity Creator | 允许 |
| 其他成员 | Gateway 预检拒绝，0 次 RPC |
| 已删除再删 | 服务端 `changed=false`；Gateway 落 `SUCCEEDED`，结果码 `expense_already_deleted`，不重复投影 |
| Activity 已归档 / 已删除 | 不在 Gateway 预检拒绝；dispatched 后按 RPC 实际错误落 `REJECTED` |
| 未知结果后核对发现已删除 | 落 `CLOSED`（`deleted_elsewhere`），不谎称成功 |
| 恢复 | 不支持 |

## 3. 契约扩展

冻结的 v1 写契约原本没有 delete 的 intent/command/preview 表达。P5.3 做了**加法扩展**：

- `WriteOperation` 增加 `"expense.delete"`。
- 新增 `ExpenseDeleteIntent`、`FixedExpenseDeleteCommand`。
- `ExpenseSnapshot` 增加 `is_deleted: bool = false`。
- 新增 `ExpenseDeletedChange`（`field="is_deleted"`）并加入 `ExpenseFieldChange`。

影响与限制：

- App 端的合同快照（`app/src/test/resources/agent-contract-v1.0.0/`）**未同步**；App 目前可能把 `expense.delete` 当作未知 operation 展示。P5.3 不做真机验收，App 侧接入留给后续切片。
- 模型路径未启用 delete：`validate_decision_against_context` 明确拒绝 `expense.delete` 的 `ProposeDecision`。删除只由默认关闭的 dev 桥创建提案。

## 4. 版本保护

服务端 `delete_expense(expense_id)` 没有 `expected_version` 或 `request_id`。P5.3 在发 RPC 前重读：

1. `expenses.version`
2. `expenses.is_deleted`
3. `activities.financial_version`（删除会重建债务投影并推进财务版本）
4. `financial_locked` 与权限

任一与预览不一致：关闭提案、Turn `CANCELLED`、**0 次 RPC**。

**已知竞态**：重读与 RPC 之间仍有窗口；服务端仍是最终权威。

## 5. 幂等、未知与核对

- `execution_id = derive(actor, proposal_id, revision)`；重复确认复用同一 ID，不再发 RPC。
- 传输超时/响应丢失：Turn `RECOVERING/UNKNOWN`，不重发。
- 核对只读 `expenses.is_deleted` 与 `version`，不调用任何写 RPC：
  - 已删除 → `CLOSED`（`deleted_elsewhere`）：没有服务端 `request_id`，无法证明是本 execution 删的，不报成功。
  - 未删除且 version 未变 → `CLOSED`（`delete_not_applied`）。
  - 未删除但 version 变化 → `CLOSED`（`expense_changed`）。
  - 读取失败 → 保持 `RECOVERING/UNKNOWN`。
- 服务端同步返回 `deleted=false`（例如版本竞态中已被删除）→ `SUCCEEDED` + `expense_already_deleted`，不重复投影。

## 6. dev 桥命令

```text
删除 <标题>
```

- `<标题>` 必须精确等于当前 Activity 内一笔消费的标题；标题可以包含空格。
- 匹配不到、重名、已锁定、已删除、非创建者/非 Creator：Turn 直接完成一条拒绝消息，不调用模型。
- 预览摘要带 `【P5 开发验证·删除】`，`policy_version=p5-dev-expense-delete-v1`。
- 预览展示 `is_deleted: false → true`，其他字段不变。

## 7. 验收与测试

| 验收 | 测试 | 结果 |
|---|---|---|
| 未锁定可删 | `test_p5_delete.py::test_unlocked_expense_can_be_deleted` | PASS |
| 锁定拒绝且 0 次 RPC | `test_locked_expense_is_rejected_without_rpc` | PASS |
| 非创建者/非 Creator 拒绝 | `test_non_creator_and_non_activity_creator_are_rejected` | PASS |
| 已删除再删 → `changed=false` 不报错 | `test_already_deleted_response_is_idempotent_success` | PASS |
| 预览后版本变化 → 关闭、0 次 RPC | `test_preflight_change_closes_without_rpc`（expense/version/is_deleted/activity 三种） | PASS |
| 归档 Activity 交给服务端 | `test_archived_activity_is_left_to_the_rpc` | PASS |
| 重复确认只写一次 | `test_duplicate_confirmation_sends_one_rpc` | PASS |
| 未知 → RECOVERING/UNKNOWN，不重发 | `test_unknown_delete_is_not_retried_and_reconciles_to_closed` | PASS |
| 核对发现被他人删除 → closed | `test_reconcile_marks_already_deleted_elsewhere_as_closed` | PASS |
| 核对未删除且版本不变 → closed | `test_reconcile_with_unchanged_undeleted_expense_closes_not_applied` | PASS |
| dev 桥删除到达真实 RPC | `test_p5_dev_bridge.py::test_dev_delete_bridge_creates_preview_and_reaches_the_rpc` | PASS |
| dev 桥锁定/非创建者拒绝 | `test_dev_delete_bridge_refuses_locked_and_non_creator` | PASS |
| dev 桥已删除/重名拒绝 | `test_dev_delete_bridge_refuses_already_deleted_and_duplicate_titles` | PASS |

全量调用方式（两个 store 根每轮新建）：

```powershell
$env:PYTHONPATH="$PWD;$PWD\agent;$PWD\agent\tests"
$env:P2_STORE_TEST_ROOT="D:\tmp\p53-<guid>-store"
$env:P2_V3_STORE_TEST_ROOT="D:\tmp\p53-<guid>-v3"
New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT, $env:P2_V3_STORE_TEST_ROOT
.\agent\.venv\Scripts\python.exe -m pytest agent\tests -q
```

结果（2026-10-26，本提交）：`834 passed, 1 xfailed`。

## 8. 已知限制

- 无恢复能力；`restore_expense` 不在本切片范围，没有伪造调用。
- 未知结果无法证明删除作者，核对时一律落 `closed`，不报成功。
- delete 的预览/操作是 Agent 合同扩展；App 合同快照未同步，设备端可能显示为未知 operation。
- 模型不能直接提出 delete；只有 dev 桥可用。
- 未做真机验收；未改训练数据；未启用 LAN；未生成新 pin。`p2_runtime.py`、`store.py` 在 P2 v3 manifest 内，pin 继续失效。

## 9. 回滚

- `AGENT_P5_DEV_INTENT_ENABLED=false` 关闭 dev 桥。
- `AGENT_LIVE_WRITE_ENABLED=false` 关闭全部真实写，confirm 回到 501。
- 已删除的测试数据由所有者在专用测试 Activity 中处理；本切片不提供 restore。
