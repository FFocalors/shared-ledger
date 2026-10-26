# P5.4 退款（负消费）：范围、边界与验收

状态：**实现完成，自动化验收通过；真机由所有者统一验收**（2026-10-26）
分支：`agent`
业务基线：`D:/project/Android/shared-ledger`（本切片不改业务 schema 或 RPC）

## 1. 范围

| 项 | 纳入 P5.4 | 说明 |
|---|---|---|
| 关联退款 | 是 | `create_expense_auto_rate` + 负金额 + `original_expense_id` |
| 未关联负调整 | 是 | 必须显式 `负调整`；普通 `记账` 不接受负金额 |
| 原单校验 | 是 | 同活动、有效、正金额、非退款单、币种一致 |
| 累计退款上限 | 是 | 以服务端读取的活跃退款累计值为准 |
| FX 快照 | 是 | 由服务端继承原单，Agent 不发送汇率 |
| 永久锁定 | 是 | Agent 观察 `financial_locked`，不解锁、不恢复 |
| 预存额度恢复 | 是 | 服务端投影重建；Agent 不改真实 Transfer |
| 业务 migration / RPC | 否 | 零业务 schema 变更 |
| 契约重导出 | 否 | 按要求留到 P5 出口门 |
| 训练数据 / LAN / 新 pin / 真机 | 否 | 按所有者要求 |

## 2. 接口

沿用 `public.create_expense_auto_rate(ledger_unit_id, title, original_amount,
original_currency, split_method, payments, manual_splits, aa_participant_ids,
occurred_at, note, original_expense_id)`：

| 参数 | 关联退款 | 负调整 |
|---|---|---|
| `original_amount` | 负数（本次退款额） | 负数（调整额） |
| `original_expense_id` | 原单 ID | `null` |
| `original_currency` | 原单币种（服务端校验一致） | 活动基础币种 |
| `payments[].amount` | 负数，合计等于退款额 | 负数，合计等于调整额 |
| `manual_splits[].amount` | 负数，合计等于退款额 | 负数，合计等于调整额 |
| `aa_participant_ids` | 等额分摊受益人 | 等额分摊参与人 |

服务端规则（`private.assert_linked_refund_integrity`）：

- 原单必须：同活动、未删除、账本单元有效、`original_expense_id is null`、`original_amount > 0`。
- 退款币种必须等于原单币种；币种不符 → `22023`。
- 退款 FX 必须等于原单 FX（服务端在 `resolve_expense_fx_snapshot` 中直接继承）。
- 活跃退款累计 + 本次绝对值 ≤ 原单金额；否则 `23514`。
- 子项金额符号必须与消费符号一致（负消费 → 负 payment / 负 split），合计必须等于负金额。

## 3. 业务边界

- **必须明确原单**：Agent 只接受用户/桥明确选定的原单引用；不会从标题联想到"大概哪一笔"。
- **未关联负调整必须显式**：`负调整` 是独立命令、独立操作 `expense.negative_adjustment`，
  不复用 `记账`，也不作为退款上限的绕过路径。普通 `记账` 的固定意图与命令都只能表达正金额。
- 来源不明时（例如只说了"退 20 元"却没有可绑定的原单）dev 桥直接拒绝，不生成提案，
  也不降级为负调整。
- **永久锁定**：一旦存在过关联退款，原单 `financial_locked` 由服务端追加表永久保持为真，
  即使退款后来被软删除；Agent 不调用任何解锁或恢复接口。
- **只恢复实际使用过的预存额度**：由服务端重建投影完成；Agent 不改真实 Transfer，
  也不计算预存余额变化。
- **收款人 / 受益人不沿用原单**：`payments` 是实际收款方，`split` 是退款受益额；二者都由
  调用方显式给出。Agent 不因为原单是谁付的、谁分摊的而推断。
- 已归档 Activity、已删除原单、外币不支持等情况以服务端返回为准；Agent 不扩大拒绝。
- 退款不会被计入"新增债务反向"，Agent 不推断债务方向。

## 4. 版本与幂等

服务端没有 `expected_version` 与 `request_id`。执行前重读：

1. 原单 `version`
2. 原单 `is_deleted`
3. 原单 `financial_locked`
4. 活跃退款累计额（以服务端读取为准，不做本地累加）
5. Activity `financial_version`

任一与预览不一致 → 关闭提案、Turn `CANCELLED`、**0 次 RPC**；重读后再按服务端累计值
重新校验退款上限。

- 重复确认：`confirm_and_dispatch` 保证只派发一次，同一 `execution_id`。
- 未知结果：Turn `RECOVERING` + `UNKNOWN`，不重发。
- 核对（只读）：
  - 活跃退款累计增加 → `CLOSED`（`refunded_elsewhere`）：无法证明属于本次 execution。
  - 累计不变但原单版本变化 → `CLOSED`（`refund_source_changed`）。
  - 累计与原单都未变 → `CLOSED`（`refund_not_applied`）。
  - 读取失败 → 保持 `UNKNOWN`。
  - 负调整：Activity 财务版本变化 → `CLOSED`（`activity_changed`）；未变 →
    `CLOSED`（`adjustment_not_applied`）。
- 退款与负调整的未知结果**从不**落成功。

## 5. dev 桥命令

```text
退款 <原单标题> <金额> [收款人=<名字>] [受益=<名字1>,<名字2>]
负调整 <标题> <金额> [付款人=<名字>] [分摊=<名字1>,<名字2>]
```

示例：

```text
退款 Lunch 10.0
退款 Lunch 10.0 收款人=Rin 受益=Alex
负调整 折扣 8.0 付款人=Rin 分摊=Alex
```

- `退款`：`<原单标题>` 必须在当前 Activity 内唯一匹配一笔未删除消费；匹配不到或重名 →
  拒绝。金额按正数输入，内部转换为负金额。
- `退款` 默认值（**dev 桥专用，不代表产品推断**）：收款人 = 第一个有效参与人；
  受益 = 全部有效参与人。都可在命令里显式覆盖。
- 退款的新消费标题为 `退款-<原单标题>`，避免与原单标题冲突。
- `负调整`：默认付款人 = 第一个有效参与人，分摊 = 全部有效参与人，币种 = 活动基础币种。
- 普通 `记账` 出现负金额（如 `记账 午餐 -5`）→ 直接拒绝并提示改用 `负调整` / `退款`，
  不调用模型。
- 预览摘要带 `【P5 开发验证·退款】` / `【P5 开发验证·负调整】`；退款摘要显示原单、
  累计已退、本次上限。

## 6. 契约扩展

- 新增 `ExpenseRefundIntent`、`NegativeAdjustmentIntent`；
  `FixedExpenseRefundCommand`、`FixedNegativeAdjustmentCommand`；
  `RefundPreview`、`NegativeAdjustmentPreview`。
- 命令与意图里的金额是**正的绝对值**；只有 `_rpc_payload_*` 在派发时统一取负，
  与服务端 `payment sign must match expense sign` 规则一致。
- 退款命令自带上限不变量：`expected_refunded_amount + amount <= expected_original_amount`。
- 加入 `ProposalOperation` / `ProposalIntent` / `ProposalPreview` / `FixedCommand`，
  不进入模型输出 schema。
- 按要求不重导出契约；App 契约快照与卡片渲染留给 P5 出口门。

## 7. 验收与测试

| 验收 | 测试 | 结果 |
|---|---|---|
| 关联退款：预览 → 确认 → 真实 RPC；负金额 + `original_expense_id`，payer/受益正确 | `test_p5_refund.py::test_refund_preview_binds_the_original_and_the_cap`、`test_refund_execute_sends_a_negative_linked_expense` | PASS |
| 超上限 → 拒绝、0 次 RPC | `test_refund_over_the_cap_is_refused_without_an_rpc`（两参数） | PASS |
| 原单已删除 / 本身是退款 / 非正金额 → 拒绝 | `test_invalid_original_is_refused`（三参数） | PASS |
| 服务端拒绝（跨活动等 22023）→ REJECTED | `test_server_rejections_surface_as_rejected` | PASS |
| 退款后原单永久锁定（观察 `financial_locked`） | `test_a_recorded_refund_locks_the_original_permanently` | PASS |
| 未关联负调整必须走显式命令；`记账` 无法表达负金额 | `test_negative_adjustment_executes_as_an_unlinked_negative_expense`、`test_plain_create_cannot_express_a_negative_amount`、dev 桥 `test_dev_plain_create_refuses_a_negative_amount` | PASS |
| 负调整外币 → 拒绝、0 次 RPC | `test_negative_adjustment_rejects_foreign_currency` | PASS |
| 重复确认 → 1 次 RPC、同一 execution_id | `test_duplicate_confirmation_sends_one_rpc` | PASS |
| 预览后原单版本 / 累计退款 / 锁定 / 删除 / Activity 版本变化 → 关闭、0 次 RPC | `test_preview_changes_close_without_an_rpc`（五参数） | PASS |
| 未知 → RECOVERING/UNKNOWN；核对无法证明 → closed | `test_unknown_refund_never_claims_success`（两参数）、`test_unknown_negative_adjustment_closes_without_claiming_success`（两参数） | PASS |
| dev 桥：退款、负调整、拒绝、上限 | `test_p5_dev_bridge.py::test_dev_refund_bridge_*`、`test_dev_negative_adjustment_bridge_*` | PASS |

全量调用方式（两个 store 根每轮新建）：

```powershell
$env:PYTHONPATH="$PWD;$PWD\agent;$PWD\agent\tests"
$env:P2_STORE_TEST_ROOT="D:\tmp\p54-<guid>-store"
$env:P2_V3_STORE_TEST_ROOT="D:\tmp\p54-<guid>-v3"
New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT, $env:P2_V3_STORE_TEST_ROOT
.\agent\.venv\Scripts\python.exe -m pytest agent\tests -q
```

结果（2026-10-26，本提交）：`942 passed, 1 xfailed`。

## 8. 已知限制

- 服务端没有请求去重键，未知结果只能关闭，不能证明归属。
- 退款上限依赖一次额外的 `expenses` 读取；活跃退款超过 1000 条时按不可读取关闭预览。
- 退款只继承原单的币种与 FX，不继承原单的付款人 / 分摊，这是有意为之。
- dev 桥的默认收款人 / 受益人只是验收便利，不代表产品会这样推断。
- 负调整只支持基础币种（与 P5.0 记账一致）。
- 契约未重导出，App 暂不认识 `expense.refund` / `expense.negative_adjustment` 预览与卡片。
- 未做真机验收；未改训练数据；未启用 LAN；未生成新 pin。`p2_runtime.py`、`store.py`
  在 P2 v3 manifest 内，pin 继续失效。

## 9. 回滚

- `AGENT_P5_DEV_INTENT_ENABLED=false` 关闭 dev 桥。
- `AGENT_LIVE_WRITE_ENABLED=false` 关闭全部真实写，confirm 回到 501。
- 已写入的测试退款由所有者在专用测试 Activity 中按业务界面处理；本切片不提供自动冲正，
  也不解锁原单（服务端设计如此）。
