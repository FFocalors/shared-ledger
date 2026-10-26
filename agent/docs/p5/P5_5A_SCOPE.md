# P5.5a 真实还款/转账：预览与创建（只做新增）

状态：**实现完成，自动化验收通过；真机由所有者统一验收**（2026-10-26）
分支：`agent`
业务基线：`D:/project/Android/shared-ledger`（本切片不改业务 schema 或 RPC）

## 1. 范围

| 项 | 纳入 P5.5a | 说明 |
|---|---|---|
| 服务端预览 | 是 | `preview_expense_repayment` |
| 服务端创建 | 是 | `create_expense_repayment_v2` |
| FIFO | 是 | 服务端按既有候选顺序分配 |
| TARGETED | 是 | 必须给出有效 `target_expense_ids` |
| `request_id` 幂等 | 是 | 从稳定执行键派生，同一 proposal 版本恒定 |
| 版本保护 | 是 | 预览返回 `source_financial_version`，创建原样携带；执行前重读 |
| `on_behalf_of` | 否 | 固定传 `null`，本切片不做代理 |
| 作废 / void | 否 | P5.5b |
| 预存 / 最终结算 / 管理类 | 否 | 后续切片 |
| 业务 migration / RPC | 否 | 零业务 schema 变更 |
| 契约重导出 | 否 | 按要求留到 P5 出口门 |
| 训练数据 / LAN / 新 pin / 真机 | 否 | 按所有者要求 |

## 2. 服务端接口

### 预览

```text
preview_expense_repayment(
  activity_id, from_participant_id, to_participant_id,
  amount, currency, mode, target_expense_ids, expected_financial_version
)
```

返回每个分配行的 `expense_id / ledger_unit_id / allocation_mode /
payment_currency / payment_amount / original_* / base_amount / fx_rate /
remaining_* / source_financial_version`。

Agent 的处理：

- 先通过权威读拿到当前 `activities.financial_version`，作为预览的 `expected_financial_version`。
- 预览返回的 `source_financial_version` 必须与输入一致；否则拒绝生成提案。
- 分配金额之和必须等于请求金额；由 `RepaymentPreview` 校验。
- 预览是只读 RPC，不写库、不保留额度。

### 创建

```text
create_expense_repayment_v2(
  activity_id, from_participant_id, to_participant_id, amount, currency,
  mode, target_expense_ids, occurred_at, on_behalf_of_participant_id,
  expected_financial_version, request_id
)
```

Agent 的请求体：

| 字段 | 来源 |
|---|---|
| `activity_id` / 双方 / 金额 / 币种 / 模式 | 固定命令 |
| `target_expense_ids` | TARGETED 的请求目标；FIFO 传空数组 |
| `occurred_at` | 预览生成时固定的服务端时间 |
| `on_behalf_of_participant_id` | 固定 `null` |
| `expected_financial_version` | 预览行的 `source_financial_version`，原样携带 |
| `request_id` | `derive_execution_id(actor, proposal_id, revision)` |

## 3. 幂等与版本保护

- `request_id = execution_id`，由稳定的执行键派生；同一 proposal 版本恒定，不在每次确认时重新生成。
- 同一 proposal 重复确认只发一次创建 RPC，返回同一 `execution_id`。
- 服务端用 `request_id` 做幂等：相同 payload 返回原结果；payload 不同冲突或版本过期由服务端拒绝。
- 执行前重读 `activities.financial_version`；不一致 → 关闭提案、Turn `CANCELLED`、0 次创建 RPC。
- 服务端创建返回 `40001`（债务/版本变化）→ 关闭已派发 execution（`CANCELLED/closed`），不报成功。

## 4. 业务边界

- 付款人/收款人必须是当前 Activity 的有效 Participant，且不能相同；预览前检查，服务端再次校验。
- 金额、债务方向与上限由服务端预览/创建校验；超额或目标无效 → `REJECTED`。
- FIFO：`target_expense_ids=[]`，服务端按候选顺序分配。
- TARGETED：必须给出有效目标；dev 桥用当前候选列表的全部 `expense_id`。
- 币种使用原币；服务端拒绝不支持的币种。
- 资金身份与代理规则以服务端 `authorize_phase5_actor` 为准；Agent 不自行判断。
- 不调用任何银行/支付接口；只登记“已经真实发生”的还款。

## 5. 契约扩展

- 新增 `RepaymentIntent`（使用服务端已绑定的 ID）与 `FixedRepaymentCommand`。
- 新增 `RepaymentPreview` / `RepaymentAllocation`，并加入 `ProposalPreview` 联合。
- 新增 `ProposalOperation` / `ProposalIntent`：`expense.delete` 与 `settlement.repayment` 只存在于提案/卡片层，**不进入模型输出 schema**，避免 P2 模型请求超预算。
- 模型路径明确拒绝 `settlement.repayment`；本切片只有 dev 桥创建提案。
- 按要求不重导出契约；App 契约快照与卡片渲染留给 P5 出口门。

## 6. dev 桥命令

```text
还款 <付款人> <收款人> <金额> <币种> [FIFO|TARGETED]
```

示例：

```text
还款 Alex Rin 10.0 USD
还款 Alex Rin 10.0 USD TARGETED
```

- 付款人/收款人按当前 scope 的显示名精确匹配；重名或不匹配拒绝。
- 金额必须为正数；币种必须为三字母；模式只能是 FIFO/TARGETED。
- TARGETED 使用 `list_transfer_expense_candidates` 返回的全部候选 `expense_id`；没有候选则拒绝。
- 匹配不到/重名/金额非法/币种不支持/服务端预览拒绝：Turn 完成一条拒绝消息，不调用模型。
- 预览摘要带 `【P5 开发验证·还款】`，`policy_version=p5-dev-repayment-v1`。

## 7. 验收与测试

| 验收 | 测试 | 结果 |
|---|---|---|
| 预览→确认→真实创建 RPC，字段含 request_id/expected_financial_version | `test_p5_repayment.py::test_repayment_confirmation_reaches_the_create_rpc` | PASS |
| 重复确认 → 1 次 RPC、同一 request_id/execution_id | `test_repayment_duplicate_confirmation_uses_one_request_id_and_rpc` | PASS |
| 预览后版本变化 → 关闭、0 次创建 RPC | `test_repayment_version_change_closes_without_create_rpc` | PASS |
| 超时/丢失 → UNKNOWN，不重发；按 request_id 核对 | `test_repayment_unknown_reconciles_by_request_id`、`test_repayment_unknown_without_a_transfer_stays_unknown` | PASS |
| 服务端拒绝（超额/无效参与人/权限）→ REJECTED | `test_repayment_server_rejection_is_terminal` | PASS |
| FIFO 与 TARGETED 各一例 | `test_repayment_confirmation_reaches_the_create_rpc`、`test_targeted_repayment_sends_target_expense_ids` | PASS |
| 预览拒绝不生成提案 | `test_repayment_preview_rejection_prevents_a_proposal` | PASS |
| dev 桥 FIFO/TARGETED/拒绝 | `test_p5_dev_bridge.py::test_dev_repayment_bridge_*` | PASS |

全量调用方式（两个 store 根每轮新建）：

```powershell
$env:PYTHONPATH="$PWD;$PWD\agent;$PWD\agent\tests"
$env:P2_STORE_TEST_ROOT="D:\tmp\p55a-<guid>-store"
$env:P2_V3_STORE_TEST_ROOT="D:\tmp\p55a-<guid>-v3"
New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT, $env:P2_V3_STORE_TEST_ROOT
.\agent\.venv\Scripts\python.exe -m pytest agent\tests -q
```

结果（2026-10-26，本提交）：`849 passed, 1 xfailed`。

## 8. 已知限制

- 未知结果按 `request_id` 只读核对：找到且 payload 一致才落成功；找不到保持 `RECOVERING/UNKNOWN`，不猜测。
- TARGETED 的 dev 桥使用“全部候选”作为目标；产品模型路径后续需要由模型/UI 选择具体目标。
- `RepaymentIntent` 使用服务端 ID（不是模型 ref）；模型输出 schema 不包含该操作。
- 契约未重导出，App 端暂不认识 `settlement.repayment` 预览/卡片。
- 不做作废（P5.5b）、不做代理、不做外币策略扩展。
- Activity 已归档由服务端创建 RPC 返回 55000 并落 `REJECTED`；Activity 已删除时财务版本不可读，预检会关闭提案而不是调用 RPC。
- 未做真机验收；未改训练数据；未启用 LAN；未生成新 pin。`p2_runtime.py`、`store.py` 在 P2 v3 manifest 内，pin 继续失效。

## 9. 回滚

- `AGENT_P5_DEV_INTENT_ENABLED=false` 关闭 dev 桥。
- `AGENT_LIVE_WRITE_ENABLED=false` 关闭全部真实写，confirm 回到 501。
- 已登记的测试还款由所有者在专用测试 Activity 中处理；本切片不作废。
