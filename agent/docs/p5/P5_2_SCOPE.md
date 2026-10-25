# P5.2 消费展示更新：范围、边界与验收

状态：**实现完成，自动化验收通过；真机由所有者统一验收**（2026-10-25）
分支：`agent`
业务基线：`D:/project/Android/shared-ledger`（本切片不改业务 schema 或 RPC）

## 1. 范围

| 项 | 纳入 P5.2 | 说明 |
|---|---|---|
| `expense.presentation.update` | 是 | 唯一新增的写操作 |
| 真实 RPC | 是 | `public.update_expense_presentation`，用户 JWT + anon key |
| 可修改字段 | `title` / `note` / `icon_key` | 请求体不得出现任何财务字段 |
| `financial_locked` Expense | **允许** | 这正是该 RPC 的用途 |
| 已删除 / Activity 归档 / 关联退款 | 交给 RPC 实际返回 | Gateway 不扩大拒绝范围 |
| 版本保护 | Expense 自身 `version` | 使用 RPC 的 `expected_version`；不使用 `activities.financial_version` |
| 幂等 | 是 | 同一 proposal 复用 `execution_id`，重复确认不再发 RPC |
| 回执 | 是 | 成功 / 拒绝 / 关闭（含 40001）/ 未知 |
| 财务字段 / 金额 / 付款 / 分摊 | 否 | 由 P5.1 处理 |
| 业务 migration / RPC | 否 | 本切片零业务 schema 变更 |
| 训练数据 / LAN / 新 pin | 否 | 按所有者要求 |
| 真机验收 | 否 | 所有者统一验收 |

## 2. 与 P5.1 的边界差异

| 情况 | P5.1 财务编辑 | P5.2 展示更新 |
|---|---|---|
| `financial_locked=true` | 拒绝 | **允许** |
| 请求字段 | 完整财务状态 | 只有 title/note/icon_key |
| 版本保护 | Expense + Activity 双版本重读 | 只用 Expense `version` |
| 已删除 / 归档 / 关联退款 | Gateway 预检拒绝 | 交给 RPC 返回实际错误 |
| 无变化 | 拒绝 | 拒绝（要求至少一个展示字段变化） |

## 3. 契约对齐

`ExpensePresentationUpdateIntent` / `FixedExpensePresentationCommand` 只含展示字段：

| 命令字段 | RPC 参数 |
|---|---|
| `expense_id` | `expense_id` |
| `patch.title` | `title`（必填） |
| `patch.note` | `note` |
| `patch.icon_key` | `icon_key` |
| `expected_expense_version` | `expected_version` |

Gateway 在预览时把 patch 与当前展示字段合并，命令里保存完整展示状态，避免“未提供”被误解释为“清空”：

- 未提供 `note` → 沿用当前 note
- 未提供 `icon_key` → 沿用当前 icon
- 未提供 `title` → 沿用当前 title

支持的 icon key（与服务端约束一致）：

```text
money dining shopping transport hotel ticket
fuel entertainment medical gift grocery flight
```

服务端会把未知 icon 归一化为 `money`；P5.2 在 Gateway **先拒绝**，避免静默改值。

## 4. 版本保护

1. 预览读取 `expenses.version`，写入 `FixedExpensePresentationCommand.expected_expense_version` 与 `PreconditionSnapshot.expense_version`。
2. 确认执行前重读 `expenses.version`；不一致 → 关闭提案、Turn `CANCELLED`、**0 次 RPC**。
3. 若竞态仍发生，RPC 返回 `40001` → 视为版本冲突：
   - 关闭已派发的 execution（`EXECUTING → RECOVERING → CANCELLED`，`execution_resolution=closed`）
   - Proposal `closed`
   - 不返回成功回执（202 的 resolution 是 `closed`，不是 `succeeded`）
4. **不使用 `activities.financial_version`** 作为展示更新的版本条件。预览里的 `activity_financial_version` 只用于契约字段与信息展示。

## 5. 幂等与四终态

- `execution_id = derive(actor, proposal_id, revision)`；重复确认复用同一 ID，不再发 RPC。
- 未知结果：Turn `RECOVERING/UNKNOWN`，不自动重发。
- 版本冲突（服务端 40001）：Turn `CANCELLED/closed`，不是成功。

| 终态 | 触发 | Turn | Proposal | RPC |
|---|---|---|---|---|
| 成功 | RPC 返回新 version | `COMPLETED/succeeded` | `confirmed` | 一次 |
| 拒绝 | RPC 返回删除/归档/成员等确定性错误 | `FAILED/rejected` | `rejected` | 一次 |
| 关闭 | 预检版本冲突（未派发） | `CANCELLED/closed` | `closed` | 0 次 |
| 关闭 | RPC 40001（已派发） | `CANCELLED/closed` | `closed` | 一次，不重发 |
| 未知 | 传输结果不明 | `RECOVERING/unknown` | `confirmed` | 一次，不重发 |

## 6. dev 桥命令

```text
改名 <标题> <新标题>
改图标 <标题> <icon_key>
改备注 <标题> <备注文本>
```

- `<标题>` 是目标选择器：按当前 Activity 内未删除 Expense 的标题匹配，必须唯一。
- 目标标题可以包含空格；解析采用“最长唯一前缀”，值可以是剩余文本。
- 标题重复、匹配不到、新值为空、无实际变化、非法 icon_key：Turn 直接完成一条拒绝消息，不调用模型。
- 预览摘要带 `【P5 开发验证·展示】`，`policy_version=p5-dev-expense-presentation-v1`。

示例：

```text
改名 Lunch Dinner
改图标 Lunch dining
改备注 Lunch 团队午餐
```

## 7. 验收与测试

| 验收 | 测试 | 结果 |
|---|---|---|
| 锁定 Expense 可改展示、财务字段不变 | `test_p5_presentation.py::test_locked_expense_can_change_presentation_and_financial_fields_are_unchanged` | PASS |
| 未锁定 Expense 可改展示 | `test_unlocked_expense_can_change_presentation` | PASS |
| 预检版本冲突 → 0 RPC、提案关闭、Turn CANCELLED | `test_presentation_expense_version_change_closes_without_rpc` | PASS |
| 服务端 40001 → 已派发 execution 关闭、不重发 | `test_server_40001_closes_the_dispatched_execution_and_never_retries` | PASS |
| Activity 财务版本不是展示更新的守卫 | `test_presentation_activity_version_is_not_the_guard` | PASS |
| 无变化拒绝 | `test_presentation_no_change_is_rejected` | PASS |
| 非法 icon_key 拒绝 | `test_presentation_invalid_icon_is_rejected` | PASS |
| 已删除/归档等交给 RPC 返回 | `test_presentation_deleted_row_is_not_pre_rejected` | PASS |
| 重复确认只写一次 | `test_presentation_duplicate_confirmation_sends_one_rpc` | PASS |
| 未知不冒充成功、不重发 | `test_presentation_unknown_is_not_retried` | PASS |
| dev 桥改名到达真实 RPC | `test_p5_dev_bridge.py::test_dev_presentation_bridge_renames_and_reaches_the_rpc` | PASS |
| dev 桥改图标/备注 | `test_dev_presentation_bridge_changes_icon_and_note` | PASS |
| dev 桥非法 icon/无变化/匹配不到 | `test_dev_presentation_bridge_refuses_bad_icon_no_change_and_unknown_target` | PASS |
| dev 桥重名拒绝 | `test_dev_presentation_bridge_refuses_duplicate_titles` | PASS |

全量调用方式（两个 store 根每轮新建）：

```powershell
$env:PYTHONPATH="$PWD;$PWD\agent;$PWD\agent\tests"
$env:P2_STORE_TEST_ROOT="D:\tmp\p52-<guid>-store"
$env:P2_V3_STORE_TEST_ROOT="D:\tmp\p52-<guid>-v3"
New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT, $env:P2_V3_STORE_TEST_ROOT
.\agent\.venv\Scripts\python.exe -m pytest agent\tests -q
```

结果（2026-10-25，本提交）：`818 passed, 1 xfailed`。

## 8. 已知限制

- `note` 清空无法通过当前 intent 表达（`None` 表示“未提供”）；P5.2 只支持设置文本。需要清空时留待后续契约扩展。
- 展示更新不改变金额、付款、分摊、发生时间；这些字段在预览里只用于展示，RPC 请求体不包含它们。
- 已删除/归档/关联退款不在 Gateway 预检拒绝，由 RPC 的实际错误码决定；因此这些情况会表现为 `rejected`，而不是预检 `closed`。dev 桥的标题列表只包含未删除消费，无法选中已删除行；这是读取层的列表范围，不是 Gateway 扩大的业务拒绝。
- `update_expense_presentation` 有 `expected_version`，但预检与 RPC 之间仍有极小窗口；服务端会用同一版本条件最终裁决。
- 未做真机验收；未改训练数据；未启用 LAN；未生成新 pin。`p2_runtime.py`、`store.py` 在 P2 v3 manifest 内，pin 继续失效。

## 9. 回滚

- `AGENT_P5_DEV_INTENT_ENABLED=false` 关闭 dev 桥。
- `AGENT_LIVE_WRITE_ENABLED=false` 关闭全部真实写，confirm 回到 501。
- 已写入的展示字段由所有者在专用测试 Activity 中处理。
