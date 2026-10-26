# P5.6 大型活动预存新增与返还：范围、边界与验收

状态：**实现完成，自动化验收通过；真机由所有者统一验收**（2026-10-26）
分支：`agent`
业务基线：`D:/project/Android/shared-ledger`（本切片不改业务 schema 或 RPC）

## 1. 范围

| 项 | 纳入 P5.6 | 说明 |
|---|---|---|
| `preview_prepayment` | 是 | 服务端预览：偿债金额 / 入账金额 / 新余额 |
| `create_prepayment_v2` | 是 | 新增预存，带 `request_id` 与 `expected_financial_version` |
| `create_prepayment_return_v2` | 是 | 返还预存，带 `request_id` 与 `expected_financial_version` |
| 仅大型活动 | 是 | Agent 预检 + 服务端 `assert_large_prepayment_activity` 双重把关 |
| 返还预览 | 是 | 服务端无专用预览；只读账户余额并原样展示 |
| 返还后余额 | 否 | 不计算；执行后以服务端 `remaining_balance` 为准 |
| 业务 migration / RPC | 否 | 零业务 schema 变更 |
| 契约重导出 | 否 | 按要求留到 P5 出口门 |
| 训练数据 / LAN / 新 pin / 真机 | 否 | 按所有者要求 |

## 2. 接口

```text
preview_prepayment(activity_id, owner_participant_id, custodian_participant_id,
                   amount, currency)
  -> settlement_amount, prepayment_amount, new_balance, financial_version

create_prepayment_v2(activity_id, owner_participant_id, custodian_participant_id,
                     amount, currency, occurred_at, on_behalf_of_participant_id,
                     expected_financial_version, request_id)
  -> transfer_id, settlement_amount, prepayment_amount, new_balance, currency,
     financial_version

create_prepayment_return_v2(activity_id, owner_participant_id, custodian_participant_id,
                            amount, currency, occurred_at, on_behalf_of_participant_id,
                            expected_financial_version, request_id)
  -> transfer_id, amount, currency, remaining_balance, financial_version
```

- 新增：服务端先偿还 `owner -> custodian` 方向的旧债（`settlement_amount`），余额部分
  计入预存账户（`prepayment_amount`）。相反方向的债务与余额不互相抵消；Agent 只展示
  服务端返回的两部分，不做任何净额计算。
- 返还：服务端把 `custodian` 记为付款人、`owner` 记为收款人；可用余额与代理权限都由
  服务端事务判定。
- 账户维度：Activity + Owner + Custodian + 币种；有效子活动共用同一账户。

## 3. 业务边界

- 仅大型活动（`activities.type = 'large'`）支持预存与返还。普通活动在 Agent 预检即
  拒绝，不调用任何 RPC，也不改写成其他业务。
- 新增：任何 Member 都可以提交，任意选择两个不同的有效参与人作为 Owner / Custodian；
  不要求 claim，也不经过 `authorize_phase5_actor`。`on_behalf_of_participant_id` 固定
  `null`。
- 返还：资金身份与代理规则完全以服务端 `authorize_phase5_actor` 为准，Agent 不自行
  判断谁能返还。
- 返还金额不得超过服务端记录的可用余额：Agent 不预判，由服务端事务返回 23514 →
  `REJECTED`（`prepayment_return_exceeds_balance`）。
- 归档 / 已删除 Activity：Agent 不在预览阶段扩大拒绝，服务端返回 55000 / P0002 →
  `REJECTED`。
- 币种：Agent 预检基础币种与多币种开关；基础币种金额必须是一位小数（与服务端
  `round(amount,1)` 规则一致）。

## 4. 版本保护

- 新增：预览 RPC 返回的 `financial_version` 原样写入固定命令与预览，创建时原样发送。
- 返还：服务端没有返还预览，预览使用当次 scope 读取的 `activities.financial_version`。
- 执行前重新读取 Activity 财务版本、Activity 类型与两个参与人的有效性：
  任一不一致 → 关闭提案、Turn `CANCELLED`、**0 次 RPC**。
- 派发后服务端返回 `40001` → `CLOSED`（`prepayment_version_conflict`），不显示成功。

**已知竞态**：重读与 RPC 之间仍有窗口；服务端仍是最终权威。

## 5. 幂等与未知

- `request_id = derive_execution_id(actor, proposal_id, revision)`，同一 proposal 版本恒定；
  重复确认不会二次派发。
- 超时 / 响应丢失：Turn `RECOVERING` + `UNKNOWN`，绝不重发。
- 按原 `request_id` 只读核对 `transfers`：
  - 找到且 `request_payload`、`type` 与本命令一致，且 `request_result` 完整 →
    `SUCCEEDED`（`prepayment_created` / `prepayment_return_created`）。
  - 找到但 payload 或类型不一致 → `CLOSED`（`request_id_conflict`）。
  - 找不到 → 保持 `RECOVERING/UNKNOWN`（读取滞后、RLS 或不可达都不算未写入）。
- 同步成功响应必须是服务端返回的完整行；缺字段按 `UNKNOWN` 处理，不冒充成功。

## 6. dev 桥命令

```text
预存 <所有者> <保管人> <金额> <币种>
返还 <所有者> <保管人> <金额> <币种>
```

示例：

```text
预存 Alex Rin 10.0 USD
返还 Alex Rin 3.0 USD
```

- 所有者 / 保管人按当前 Activity 的显示名精确或唯一匹配；必须不同。
- 匹配不到、重名、同名、金额非正数、币种非三字母、参数个数不对：Turn 完成一条拒绝
  消息，不调用模型。
- 普通活动、币种不受支持、基础币种金额超过一位小数、余额不可读：同样直接拒绝。
- 预览摘要带 `【P5 开发验证·预存】` / `【P5 开发验证·返还】`；
  `policy_version` 分别为 `p5-dev-prepayment-v1` / `p5-dev-prepayment-return-v1`。
- 返还预览只显示服务端读取的当前余额，并写明「返还后余额以服务端执行结果为准」。

## 7. 契约扩展

- 新增 `PrepaymentIntent`、`PrepaymentReturnIntent`；
  `FixedPrepaymentCommand`、`FixedPrepaymentReturnCommand`；
  `PrepaymentPreview`、`PrepaymentReturnPreview`。
- 加入 `ProposalOperation` / `ProposalIntent` / `ProposalPreview` / `FixedCommand`。
- 不进入模型输出 schema：`WriteOperation` / `WriteIntent` 保持三个模型可见操作。
- 按要求不重导出契约；App 契约快照与卡片渲染留给 P5 出口门。

## 8. 验收与测试

| 验收 | 测试 | 结果 |
|---|---|---|
| 大型活动：预览 → 确认 → 真实 RPC，请求体字段正确 | `test_p5_prepayment.py::test_prepayment_preview_shows_settlement_and_balance_parts`、`test_prepayment_create_uses_request_id_and_server_version` | PASS |
| 普通活动新增/返还 → 拒绝、0 次 RPC | `test_normal_activity_is_refused_before_any_rpc`（两参数） | PASS |
| 新增显示「偿债金额 / 入账余额」两部分且与预览一致 | `test_prepayment_preview_shows_settlement_and_balance_parts` | PASS |
| 返还超余额 → 服务端拒绝 → REJECTED | `test_return_above_balance_is_rejected_by_the_server` | PASS |
| 返还预览不计算后余额；执行后显示服务端 `remaining_balance` | `test_return_preview_reads_balance_and_never_computes_the_post_balance`、`test_return_execution_reports_the_server_remaining_balance`、`test_p5_dev_bridge.py::test_dev_prepayment_return_bridge_reports_the_server_remaining_balance` | PASS |
| 重复确认 → 1 次 RPC、同一 request_id、同一 execution_id | `test_duplicate_confirmation_sends_one_rpc` | PASS |
| 预览后版本变化 → 关闭、0 次 RPC | `test_version_change_closes_without_rpc`（两参数） | PASS |
| 派发后 40001 → CLOSED | `test_server_version_conflict_after_dispatch_closes` | PASS |
| 大型活动降级 → 关闭、0 次 RPC | `test_large_activity_requirement_is_rechecked_before_dispatch` | PASS |
| 未知 → RECOVERING/UNKNOWN，不重发；按 request_id 核对 | `test_unknown_prepayment_stays_unknown_until_the_request_id_is_found`、`test_unknown_prepayment_with_a_different_payload_closes` | PASS |
| 币种 / 精度本地预检 | `test_prepayment_currency_and_precision_are_guarded_locally` | PASS |
| 新增不要求 claim；非会员由服务端拒绝 | `test_create_needs_no_claim_from_the_owner_or_custodian`、`test_non_member_creation_is_rejected_by_the_server` | PASS |
| 幂等结果不可回放 → UNKNOWN，不冒充拒绝或成功 | `test_unreplayable_idempotent_result_is_unknown_not_rejected` | PASS |
| 账户不可读 → 预览拒绝 | `test_return_preview_reports_an_unreadable_account` | PASS |
| dev 桥预存/返还/拒绝/普通活动 | `test_p5_dev_bridge.py::test_dev_prepayment_bridge_*` | PASS |

全量调用方式（两个 store 根每轮新建）：

```powershell
$env:PYTHONPATH="$PWD;$PWD\agent;$PWD\agent\tests"
$env:P2_STORE_TEST_ROOT="D:\tmp\p56-<guid>-store"
$env:P2_V3_STORE_TEST_ROOT="D:\tmp\p56-<guid>-v3"
New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT, $env:P2_V3_STORE_TEST_ROOT
.\agent\.venv\Scripts\python.exe -m pytest agent\tests -q
```

结果（2026-10-26，本提交）：`895 passed, 1 xfailed`。

## 9. 已知限制

- 服务端没有返还预览 RPC，返还预览只展示当前余额；返还后余额只能来自执行结果。
- 返还预览的 `expected_financial_version` 来自 Agent 当次 scope 读取，不是服务端预览。
- Agent 不在预览阶段判断“余额不足”，以免与服务端事务规则分叉；这类拒绝由服务端返回。
- 基础币种金额必须一位小数，源自服务端规则；两位小数由 Agent 预检拒绝。
- 契约未重导出，App 暂不认识 `prepayment.create` / `prepayment.return` 预览与卡片。
- 未做真机验收；未改训练数据；未启用 LAN；未生成新 pin。`p2_runtime.py`、`store.py`
  在 P2 v3 manifest 内，pin 继续失效。

## 10. 回滚

- `AGENT_P5_DEV_INTENT_ENABLED=false` 关闭 dev 桥。
- `AGENT_LIVE_WRITE_ENABLED=false` 关闭全部真实写，confirm 回到 501。
- 已写入的测试预存/返还由所有者在专用测试 Activity 中按业务界面处理；本切片不提供
  自动冲正。
