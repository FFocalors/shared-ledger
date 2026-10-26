# P5.5b 真实转账作废：范围、边界与验收

状态：**实现完成，自动化验收通过；真机由所有者统一验收**（2026-10-26）
分支：`agent`
业务基线：`D:/project/Android/shared-ledger`（本切片不改业务 schema 或 RPC）

## 1. 范围

| 项 | 纳入 P5.5b | 说明 |
|---|---|---|
| `void_settlement_transfer` | 是 | `settlement` 类型 |
| `void_prepayment_transfer` | 是 | `prepayment` / `prepayment_return` / `final_settlement` |
| 类型分派 | 是 | 按服务端读取的 `transfers.type`；未知类型 fail closed |
| 权限 | 是 | 录入者本人或 Activity Creator |
| 已作废再作废 | 是 | 服务端 `voided=false` 或 55000 后重读 `is_voided` → 幂等成功 |
| 版本保护 | 是 | 重读 Transfer 状态、录入者、Activity 状态与财务版本 |
| 恢复 | 否 | `restore_transfer` 对 API role 已撤权，不调用、不伪造 |
| 预存返还依赖 | 否 | 服务端 23514 → `REJECTED`，不自动先作废返还 |
| 业务 migration / RPC | 否 | 零业务 schema 变更 |
| 契约重导出 | 否 | 按要求留到 P5 出口门 |
| 训练数据 / LAN / 新 pin / 真机 | 否 | 按所有者要求 |

## 2. 接口与类型分派

```text
void_settlement_transfer(transfer_id, void_reason)
void_prepayment_transfer(transfer_id, void_reason)
```

| `transfers.type` | RPC |
|---|---|
| `settlement` | `void_settlement_transfer` |
| `prepayment` | `void_prepayment_transfer` |
| `prepayment_return` | `void_prepayment_transfer` |
| `final_settlement` | `void_prepayment_transfer` |
| 其他 | fail closed（`unsupported_transfer_type`） |

类型来自服务端读取，不接受客户端自报；执行前再次读取并比对预览时的类型。

## 3. 业务边界

- Member 只能作废自己录入的 Transfer（`recorded_by = auth.uid()`）。
- Activity Creator 可作废任意记录。
- 要求 Activity 未删除；未归档；记录未作废。
- Transfer 不可编辑、不可恢复；作废保留历史与来源，不删除 Transfer/组件。
- 预存来源仍有有效 Return 依赖时，服务端返回 23514；Agent 如实落 `REJECTED`，不自动作废 Return。
- 已作废再作废：服务端返回 `voided=false`（或 55000）时，Agent 重读 `is_voided`；为 true 则落幂等成功 `transfer_already_voided`。
- 归档/已删除 Activity：预览不扩大拒绝；执行时服务端返回 55000/P0002 → `REJECTED`。

## 4. 版本保护

服务端没有 `expected_version` / `request_id`。执行前重读：

1. `transfers.is_voided`
2. `transfers.recorded_by`
3. `transfers.type`
4. `activities.archived_at` / `is_deleted`
5. `activities.financial_version`

任一与预览不一致 → 关闭提案、Turn `CANCELLED`、**0 次 RPC**。

**已知竞态**：重读与 RPC 之间仍有窗口；服务端仍是最终权威。

## 5. 幂等与未知

- `execution_id = derive(actor, proposal_id, revision)`；重复确认复用同一 ID，不重发。
- 超时/响应丢失：Turn `RECOVERING/UNKNOWN`，不重发。
- 按 `transfer_id` 只读核对：
  - 已作废 → `CLOSED`（`voided_elsewhere`）；没有服务端请求键，无法证明是本 execution 作废的，不报成功。
  - 未作废且 Activity 财务版本未变 → `CLOSED`（`void_not_applied`）。
  - 未作废但 Activity 财务版本变化 → `CLOSED`（`activity_changed`）。
  - 读取失败 → 保持 `RECOVERING/UNKNOWN`。
- 同步返回 `voided=false` → `SUCCEEDED` + `transfer_already_voided`，不重复重建投影。
- 同步返回 55000 后重读 `is_voided=true` → 同样视为幂等成功；若重读为未作废（如归档拒绝）→ `REJECTED`。

## 6. dev 桥命令

```text
作废 <付款人> <收款人> <金额> <币种> [原因=<文本>]
```

示例：

```text
作废 Alex Rin 10.0 USD
作废 Alex Rin 10.0 USD 原因=录错了
```

- 付款人/收款人按当前 Activity 的显示名精确匹配，且必须不同。
- 按 付款人 + 收款人 + 金额 + 币种 在当前 Activity 的 Transfer 列表中匹配；必须唯一。
- 匹配不到、重名、多笔、已作废、非录入者且非 Creator：Turn 完成拒绝消息，不调用模型。
- 金额必须为正数；币种三字母；原因为空时使用 `dev bridge void`。
- 预览摘要带 `【P5 开发验证·作废】`，`policy_version=p5-dev-transfer-void-v1`。

## 7. 契约扩展

- 新增 `VoidTransferIntent`、`FixedVoidTransferCommand`、`TransferVoidPreview`。
- 加入 `ProposalOperation` / `ProposalIntent` / `ProposalPreview`。
- 不进入模型输出 schema；模型路径不能提出 `transfer.void`。
- 按要求不重导出契约；App 契约快照与卡片渲染留给 P5 出口门。

## 8. 验收与测试

| 验收 | 测试 | 结果 |
|---|---|---|
| 本人录入可作废 | `test_p5_void.py::test_own_settlement_transfer_can_be_voided` | PASS |
| Creator 可作废他人记录 | `test_activity_creator_can_void_another_users_transfer` | PASS |
| 普通 Member 作废他人记录 → REJECTED | `test_member_voiding_another_users_transfer_is_rejected` | PASS |
| 已作废再作废 → `changed=false` 幂等成功 | `test_already_voided_changed_false_is_idempotent_success`、`test_55000_already_voided_race_is_idempotent_success` | PASS |
| 归档 / 已删除 Activity → REJECTED | `test_archived_or_deleted_activity_is_rejected` | PASS |
| 预存返还依赖 → REJECTED | `test_prepayment_return_dependency_is_rejected` | PASS |
| 预览后版本/状态变化 → 关闭、0 次 RPC | `test_preflight_change_closes_without_rpc` | PASS |
| 未知 → UNKNOWN；核对到他人作废 → closed | `test_unknown_void_reconciles_to_closed`、`test_unknown_void_not_applied_closes`、`test_unknown_void_with_activity_change_closes` | PASS |
| 重复确认只写一次 | `test_duplicate_confirmation_sends_one_rpc` | PASS |
| 结算转账与预存资金各一例，选对 RPC | `test_own_settlement_transfer_can_be_voided`、`test_prepayment_transfer_uses_the_prepayment_rpc` | PASS |
| dev 桥结算/预存/拒绝 | `test_p5_dev_bridge.py::test_dev_void_bridge_*` | PASS |

全量调用方式（两个 store 根每轮新建）：

```powershell
$env:PYTHONPATH="$PWD;$PWD\agent;$PWD\agent\tests"
$env:P2_STORE_TEST_ROOT="D:\tmp\p55b-<guid>-store"
$env:P2_V3_STORE_TEST_ROOT="D:\tmp\p55b-<guid>-v3"
New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT, $env:P2_V3_STORE_TEST_ROOT
.\agent\.venv\Scripts\python.exe -m pytest agent\tests -q
```

结果（2026-10-26，本提交）：`870 passed, 1 xfailed`。

## 9. 已知限制

- 服务端当前对已作废记录实际返回 55000，而不是 `changed=false`；Agent 通过重读 `is_voided` 兼容两者。
- 未知结果一律不报成功；即使 Transfer 已作废，也无法证明是本 execution 所为。
- 归档/已删除 Activity 由服务端拒绝；若在预览后状态发生变化，则按版本保护关闭提案。
- 不调用 `restore_transfer`；不自动作废依赖的 Return。
- 契约未重导出，App 暂不认识 `transfer.void` 预览/卡片。
- 未做真机验收；未改训练数据；未启用 LAN；未生成新 pin。`p2_runtime.py`、`store.py` 在 P2 v3 manifest 内，pin 继续失效。

## 10. 回滚

- `AGENT_P5_DEV_INTENT_ENABLED=false` 关闭 dev 桥。
- `AGENT_LIVE_WRITE_ENABLED=false` 关闭全部真实写，confirm 回到 501。
- 已作废的测试转账由所有者在专用测试 Activity 中处理；本切片不恢复。
