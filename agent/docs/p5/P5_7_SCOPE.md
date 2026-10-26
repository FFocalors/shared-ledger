# P5.7 最终结算执行：范围、边界与验收

状态：**实现完成，自动化验收通过；真机由所有者统一验收**（2026-10-26）
分支：`agent`
业务基线：`D:/project/Android/shared-ledger`（本切片不改业务 schema 或 RPC）

## 1. 范围

| 项 | 纳入 P5.7 | 说明 |
|---|---|---|
| `preview_final_settlement_v2` | 是 | 读取服务端完整建议：方向、金额、拆分为普通/预存返还、币种、版本 |
| `execute_final_settlement_v2` | 是 | 只执行建议中的某一项，带去重键与版本前置 |
| 两种模式 | 是 | `base_unified` / `original_currency` 原样透传 |
| 普通活动 | 是 | 建议中不含预存返还路径 |
| 大型活动 | 是 | 建议可含预存返还路径（由服务端计划决定） |
| Agent 侧计算 / 重排 / 净额 | 否 | 不实现，也不允许 |
| 业务 migration / RPC | 否 | 零业务 schema 变更 |
| 契约重导出 | 否 | 按要求留到 P5 出口门 |
| 训练数据 / LAN / 新 pin / 真机 | 否 | 按所有者要求 |

## 2. 接口

```text
preview_final_settlement_v2(activity_id, mode = 'base_unified')
  -> activity_id, from_participant_id, to_participant_id,
     amount, ordinary_amount, prepayment_return_amount,
     currency, mode, path_currency, source_financial_version,
     is_prepayment_return
     （每个方向/币种一行，构成完整建议）

execute_final_settlement_v2(activity_id, from_participant_id, to_participant_id,
                            amount, currency, mode,
                            expected_financial_version, request_id,
                            occurred_at?, on_behalf_of_participant_id?)
  -> transfer_id, amount, currency, mode, financial_version
```

服务端在执行时会用当前计划重新匹配
`(from, to, amount, currency)`；匹配不到即 23514。

## 3. 业务边界

- **预览返回的是整个 Activity 的建议项**，不是“某人欠谁”的即时计算。Agent 保留全部
  建议项，并在预览与摘要中完整列出。
- **执行只能引用当前建议中的某一项**：方向、金额、币种逐字段与服务端建议一致，且
  拆分的普通金额 / 预存返还金额原样拷贝。Agent 不估算、不合并、不拆单。
- 普通与大型活动都走同一 optimizer 与同一组模式，差别只在建议内容：只有大型活动的
  建议可能出现预存返还路径，普通活动该路径为空（由服务端 `activities.type` 决定）。
- 不保证最少笔数，不自动抵消环路，不做净额化；Agent 不重排建议，也不为“更好看”的
  笔数做任何合并。
- 执行语义是**登记一笔用户确认已经真实发生的付款**，不是下发转账指令。
- `on_behalf_of_participant_id` 本切片固定 `null`；代理登记不在 P5.7 内。
- 归档 / 已删除 Activity、非会员、计划不匹配等由服务端事务给出结论。

## 4. 版本与幂等

- 预览中所有建议项必须共享同一个 `source_financial_version`；它被原样写入固定命令与
  预览的 `expected_financial_version`，执行时原样发送。
- `request_id = derive_execution_id(actor, proposal_id, revision)`，同一 proposal 版本恒定；
  重复确认不会二次派发。
- 执行前重读 Activity 财务版本与 `activities.type`，并复查两个参与人仍然有效：
  - 版本不一致 → 关闭提案、Turn `CANCELLED`、**0 次 RPC**。
  - 类型改变（例如大型降级为普通）→ 关闭提案、`activity_type_changed`、**0 次 RPC**。
- 派发后服务端返回 `40001` → `CLOSED`（`final_settlement_version_conflict`），
  execution 保留但**不报成功**。
- 派发后服务端返回 `23514`（计划已变）→ `REJECTED`（`final_settlement_stale_plan`）。
- 未知结果：Turn `RECOVERING` + `UNKNOWN`，绝不重发；按原 `request_id` 只读核对
  `transfers`（类型必须是 `final_settlement`，payload 必须逐字段一致）：
  - 找到且一致 → `SUCCEEDED`；
  - 找到但 payload 不同 → `CLOSED`（`request_id_conflict`）；
  - 找不到 → 保持 `UNKNOWN`。
- 服务端 55000「idempotent result is unavailable」→ `UNKNOWN`，不冒充拒绝或成功。

## 5. dev 桥命令

```text
结算 <付款人> <收款人> <金额> <币种> [模式=base_unified|original_currency]
```

示例：

```text
结算 Alex Rin 10.0 USD
结算 Alex Rin 10.0 USD 模式=original_currency
```

- 付款人 / 收款人按当前 Activity 的显示名精确或唯一匹配；必须不同。
- 只有当前建议中存在**方向、金额、币种逐字段完全一致**的一项时才生成预览；否则 Turn
  完成一条拒绝消息，不调用模型、不发执行 RPC。
- 预览摘要带 `【P5 开发验证·结算】`，列出当前**完整**建议项（不只匹配的那一项），
  并说明确认后按已实际发生的付款登记。
- 模式缺省为 `base_unified`；非法模式、金额非正数、币种非三字母、参数个数不对一律拒绝。

## 6. 契约扩展

- 新增 `FinalSettlementIntent`、`FixedFinalSettlementCommand`、
  `FinalSettlementPreview`、`FinalSettlementPlanItem`。
- `settlement.final` 加入 `ProposalOperation` / `ProposalIntent` / `ProposalPreview` /
  `FixedCommand`，不进入模型输出 schema。
- 预览模型自带两条不变量：选中的项必须**恰好一项**落在 `plan` 中；拆分的普通 / 预存返还
  金额必须与计划项完全一致。
- 按要求不重导出契约；App 契约快照与卡片渲染留给 P5 出口门。

## 7. 验收与测试

| 验收 | 测试 | 结果 |
|---|---|---|
| 预览列出完整建议；执行匹配项 → 真实 RPC，请求体字段正确 | `test_p5_final_settlement.py::test_preview_lists_the_complete_plan_and_selects_one_item`、`test_execute_matches_the_plan_item_and_sends_request_fields` | PASS |
| 金额 / 方向 / 币种任一不匹配 → 拒绝，0 次 RPC | `test_any_field_mismatch_is_refused_without_an_rpc`（三参数） | PASS |
| 普通活动建议无预存返还路径，大型活动可含 | `test_normal_activity_plan_has_no_prepayment_return_item`、`test_large_activity_plan_can_select_a_prepayment_return_item` | PASS |
| 重复确认 → 1 次 RPC、同一 request_id、同一 execution_id | `test_duplicate_confirmation_sends_one_rpc` | PASS |
| 预览后版本变化 → 关闭、0 次 RPC | `test_preview_version_change_closes_without_rpc` | PASS |
| 预览后活动类型变化 → 关闭、0 次 RPC | `test_activity_type_change_closes_without_rpc` | PASS |
| 服务端 40001 → 已派发 execution 关闭，不报成功 | `test_server_40001_closes_the_dispatched_execution` | PASS |
| 计划已变（23514）→ REJECTED | `test_stale_plan_rejection_is_reported_as_rejected` | PASS |
| 空建议 → 拒绝 | `test_empty_plan_is_refused` | PASS |
| 未知 → RECOVERING/UNKNOWN；按 request_id 核对 | `test_unknown_final_settlement_reconciles_by_request_id`、`test_unknown_final_settlement_with_a_different_payload_closes` | PASS |
| `base_unified` 与 `original_currency` 各一例 | `test_both_settlement_modes_reach_the_rpc`（两参数）、dev 桥 `..._supports_original_currency_mode` | PASS |
| dev 桥：完整建议、执行、拒绝 | `test_p5_dev_bridge.py::test_dev_final_settlement_bridge_*` | PASS |

全量调用方式（两个 store 根每轮新建）：

```powershell
$env:PYTHONPATH="$PWD;$PWD\agent;$PWD\agent\tests"
$env:P2_STORE_TEST_ROOT="D:\tmp\p57-<guid>-store"
$env:P2_V3_STORE_TEST_ROOT="D:\tmp\p57-<guid>-v3"
New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT, $env:P2_V3_STORE_TEST_ROOT
.\agent\.venv\Scripts\python.exe -m pytest agent\tests -q
```

结果（2026-10-26，本提交）：`916 passed, 1 xfailed`。

## 8. 已知限制

- Agent 不做本地计划校验以外的任何金额推断；计划由服务端在事务内重新匹配，Agent 的
  “匹配”只用于选中项与渲染。
- 预览后、派发前的计划变化若未改变 Activity 财务版本，Agent 无法提前发现，由服务端
  23514 拒绝（`REJECTED`，不会写成成功）。
- 预览摘要长度上限提高到 2000 字符以容纳完整建议；建议项超过 64 条会被契约拒绝
  （当前 optimizer 规模远低于此）。
- `on_behalf_of_participant_id` 固定 `null`；代理登记不在 P5.7 内。
- 契约未重导出，App 暂不认识 `settlement.final` 预览与卡片。
- 未做真机验收；未改训练数据；未启用 LAN；未生成新 pin。`p2_runtime.py`、`store.py`
  在 P2 v3 manifest 内，pin 继续失效。

## 9. 附带修复

`agent/tests/test_p2_read_contracts.py` 之前用模块级 `NOW` 构造授权与回执，有效期只有
一分钟；一次较慢的全量跑批会让这些合同在解析时已过期，导致 4 项与产品无关的失败。
本次把**有效期**改为调用时取值（`current_time()`，5 分钟窗口），静态事实时间戳仍用
`NOW`，断言语义不变。

## 10. 回滚

- `AGENT_P5_DEV_INTENT_ENABLED=false` 关闭 dev 桥。
- `AGENT_LIVE_WRITE_ENABLED=false` 关闭全部真实写，confirm 回到 501。
- 已登记的测试结算由所有者在专用测试 Activity 中按业务界面处理；本切片不提供自动冲正。
