# P5.8a 活动与参与人管理（只读 + 安全写）：范围、边界与验收

状态：**实现完成，自动化验收通过；真机由所有者统一验收**（2026-10-26）
分支：`agent`
业务基线：`D:/project/Android/shared-ledger`（本切片不改业务 schema 或 RPC）

## 1. 范围

| 项 | 纳入 P5.8a | 说明 |
|---|---|---|
| `create_activity` | 是 | 名称、类型、基础币种、多币种开关 |
| `join_activity_by_code` | 是 | 8 位数字加入码 |
| `create_participant` | 是 | 活动内新增参与人，顺序可省略 |
| `delete_participant` | 是 | 仅未认领、未被引用的参与人 |
| claim / unclaim | 否 | 留给 P5.8b |
| 成员移除 / Creator 转移 | 否 | 留给 P5.8b / P5.8c |
| 归档 / 删除活动 | 否 | 留给 P5.8c |
| 业务 migration / RPC | 否 | 零业务 schema 变更 |
| 契约重导出 | 否 | 按要求留到 P5 出口门 |
| 训练数据 / LAN / 新 pin / 真机 | 否 | 按所有者要求 |

## 2. 接口

```text
create_activity(name, type, base_currency = 'CNY', multi_currency_enabled = false)
  -> activity_id, join_code, activity_name, activity_type,
     activity_base_currency, activity_multi_currency_enabled

join_activity_by_code(join_code)
  -> activity_id, is_new

create_participant(activity_id, name, participant_order = null)
  -> participant_id, participant_name, participant_order

delete_participant(participant_id)
  -> participant_id, deleted
```

- `create_activity` 的 Creator 由服务端取 `auth.uid()`；请求体**不含**任何用户 ID。
- `join_activity_by_code`：加入成功 `is_new=true`；已是成员时 `is_new=false`（幂等成功）。
- `create_participant`：不传 `participant_order` 时由服务端取 `max(order)+1`。
- `delete_participant`：已删除时返回 `deleted=false`（幂等成功）。

## 3. 业务边界

- **创建活动**：任何已登录用户；服务端固定 Creator 并同时建立 membership 与默认账本单元。
- **加入活动**：8 位数字加入码；未知码 `P0002`、归档活动 `55000`、格式错误 `22023`。
  **加入不等于认领 Participant**，Agent 不把两者混为一谈，也不顺手 claim。
- **新增参与人**：要求调用者是有效 Activity Member；`participants_locked_at` 非空 →
  `55000 participant list is locked`；空名 `22023`。
- **删除参与人**：要求调用者是有效 Activity Member；已认领（`participant_claims`）或被
  Payment / Split / Transfer（含 `on_behalf_of_participant_id`）引用 → `23514`；
  名单锁定 → `55000`；已删除 → `deleted=false`。
- 归档 / 已删除 Activity 一律按服务端返回处理：Agent 预览不因归档而提前拒绝，而是在
  执行前比对归档/删除状态，变化则关闭提案。
- Agent 侧额外规则（服务端允许、Agent 为确定性而拒绝）：
  - 建活动：调用者已有同名未删除活动 → `activity_name_conflict`。
  - 加参与人：活动内已有同名未删除参与人 → `participant_name_conflict`。
  两条都是为了让名称仍可作为稳定的自然键；写进本切片文档，不冒充服务端约束。

## 4. 版本与幂等

这些 RPC 没有 `expected_version` / `request_id`。

- 执行前重读：
  - `join_activity_by_code`：按加入码读活动（仅当调用者已是成员才可见）；已归档/已删除 →
    `join_code_inactive`，0 次 RPC。
  - `create_participant`：Activity 是否删除、归档、`participants_locked_at`、参与人重名。
  - `delete_participant`：Activity 状态、参与人是否存在/同活动/名称/是否已删除、是否被
    认领或引用。
  - 任一与预览快照不一致 → 关闭提案、Turn `CANCELLED`、**0 次 RPC**。
- `create_activity` 没有可读的前置状态（活动尚不存在），只做名称冲突检查。
- 重复确认：`confirm_and_dispatch` 保证只派发一次，同一 `execution_id`。
- 未知结果：Turn `RECOVERING` + `UNKNOWN`，不重发；按自然键只读核对，**一律 `closed`**：
  - 活动名 + 类型/币种/多币种一致 → `activity_created_elsewhere`；否则 `activity_not_created`。
  - 加入码可见成员关系 → `joined_elsewhere`；不可见 → `join_not_applied`。
  - 活动内同名参与人 → `participant_created_elsewhere`；否则 `participant_not_created`。
  - 参与人已删除 → `deleted_elsewhere`；未删除或不存在 → `delete_not_applied`。
  无法证明归属，因此从不落成功。

## 5. 没有活动 scope 的提案

`建活动` / `加入活动` 在活动尚不存在时发生，提案没有可授权的活动。

- `PreconditionSnapshot.activity_id` 改为可选；这两个操作写入 `null`，且不允许携带
  财务版本前置。
- API 侧新增两条精确豁免：
  - 卡片可见性与确认：当 `scope_ids` 为空且提案是这四个管理操作之一时，跳过活动授权
    （服务端 RPC 自身以 `auth.uid()` 鉴权，不泄露任何活动数据）。
  - 事件轮询：仅当一个 Turn 无绑定引用、无读取结果、无策略证据，且其中所有提案都是管理
    操作时，才允许无 scope 读取；它的 `execution_result` 只描述调用者自己的管理写入。
- dev 桥拒绝消息：仅当 Turn 没有模型决策、没有引用/读取时，才允许无 scope 读取该条
  非模拟 `message`；其他事件（例如注入的 `error`）仍然 503 失败关闭。

## 6. dev 桥命令

```text
建活动 <名称> <普通|大型> <币种>
加入活动 <8位加入码>
加参与人 <名字>
删参与人 <名字>
```

示例：

```text
建活动 秋游 大型 JPY
加入活动 12345678
加参与人 Ben
删参与人 Alex
```

- `建活动` / `加入活动` 不需要当前活动 scope；`加参与人` / `删参与人` 用当前面板 Activity。
- `建活动` 固定 `multi_currency_enabled = false`（命令里没有该开关）。
- `删参与人` 按名字在当前活动未删除参与人中唯一匹配；找不到或重名 → 拒绝。
- 名称重名、名单锁定、参与人已被认领/引用、加入码格式错误 → 拒绝，不调用模型、不发 RPC。
- 预览摘要带 `【P5 开发验证·管理】`，`policy_version = p5-dev-management-v1`。

## 7. 契约扩展

- 新增 `ActivityCreateIntent`、`ActivityJoinIntent`、`ParticipantCreateIntent`、
  `ParticipantDeleteIntent`。
- 新增 `FixedActivityCreateCommand`、`FixedActivityJoinCommand`、
  `FixedParticipantCreateCommand`、`FixedParticipantDeleteCommand`。
- 新增 `ManagementPreview`（单一 `kind="management"`，按 `operation` 校验字段组合）。
- `PreconditionSnapshot.activity_id` 变为可选。
- 四个操作加入 `ProposalOperation` / `ProposalIntent` / `ProposalPreview` / `FixedCommand`，
  不进入模型输出 schema。
- 按要求不重导出契约；App 契约快照与卡片渲染留给 P5 出口门。

## 8. 验收与测试

| 验收 | 测试 | 结果 |
|---|---|---|
| 建活动 → 真实 RPC，回执含活动 ID；请求不含 Creator | `test_p5_manage.py::test_activity_create_previews_and_executes_without_a_creator_id`、dev 桥 `test_dev_activity_create_bridge_works_without_a_scope` | PASS |
| 加入活动：合法码成功；非法码/已归档拒绝 | `test_activity_join_previews_and_executes`、`test_activity_join_server_rejections`、`test_activity_join_closes_on_an_archived_code`、`test_activity_join_requires_eight_digits` | PASS |
| 加参与人：合法成功；名单锁定后拒绝 | `test_participant_create_previews_and_executes`、`test_participant_create_refuses_duplicate_names_and_lock` | PASS |
| 删参与人：未引用成功；已认领/被引用拒绝、0 次 RPC | `test_participant_delete_previews_and_executes`、`test_participant_delete_refuses_a_claimed_or_used_row`（四参数）、`test_participant_delete_refuses_a_locked_list` | PASS |
| 已删除参与人再次删除 → 幂等成功 | `test_participant_delete_of_an_already_deleted_row_is_idempotent` | PASS |
| 重复确认只写一次 | `test_duplicate_confirmation_sends_one_rpc` | PASS |
| 预览后状态变化 → 关闭、0 次 RPC | `test_preview_state_changes_close_without_an_rpc`（四参数） | PASS |
| 未知 → RECOVERING/UNKNOWN，无法证明归属 → closed | `test_unknown_management_outcomes_always_close`（八参数） | PASS |
| 无 scope 的建活动/加入活动：卡片可见、可确认、回执可读 | dev 桥 `test_dev_activity_create_bridge_works_without_a_scope`、`test_dev_activity_join_bridge_works_without_a_scope` | PASS |
| 无 scope 的失败关闭仍然生效 | `test_identity_api.py::test_unscoped_non_status_event_fails_closed_but_owner_status_poll_survives` | PASS |

全量调用方式（两个 store 根每轮新建）：

```powershell
$env:PYTHONPATH="$PWD;$PWD\agent;$PWD\agent\tests"
$env:P2_STORE_TEST_ROOT="D:\tmp\p58a-<guid>-store"
$env:P2_V3_STORE_TEST_ROOT="D:\tmp\p58a-<guid>-v3"
New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT, $env:P2_V3_STORE_TEST_ROOT
.\agent\.venv\Scripts\python.exe -m pytest agent\tests -q
```

结果（2026-10-26，本提交）：`976 passed, 1 xfailed`。

## 9. 已知限制

- 四个 RPC 都没有请求去重键，未知结果只能关闭。
- `join_activity_by_code` 在加入前无法读取活动（非成员看不到该活动行），因此“加入码是否仍有效”
  只能由服务端在事务内判定；Agent 仅在已是成员时能提前发现归档。
- 参与人使用检查需要 6 次只读查询（claims / payments / splits / transfers × 3）。
- 建活动/加参与人的同名拒绝是 Agent 规则，不是数据库约束。
- 无 scope 的管理提案在事件轮询上有一条精确豁免；非管理 Turn 仍然失败关闭。
- 契约未重导出，App 暂不认识 `activity.create` / `activity.join` /
  `participant.create` / `participant.delete` 预览与卡片。
- 未做真机验收；未改训练数据；未启用 LAN；未生成新 pin。`p2_runtime.py`、`store.py`、
  `api.py` 在 P2 v3 manifest 内，pin 继续失效。

## 10. 回滚

- `AGENT_P5_DEV_INTENT_ENABLED=false` 关闭 dev 桥。
- `AGENT_LIVE_WRITE_ENABLED=false` 关闭全部真实写，confirm 回到 501。
- 本切片只创建/软删除测试用活动与参与人；不在自动化中回滚，由所有者在测试项目内处理。
