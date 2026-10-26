# P5.8b 认领/解除认领与子活动生命周期：范围、边界与验收

状态：**实现完成，自动化验收通过；真机由所有者统一验收**（2026-10-26）
分支：`agent`
业务基线：`D:/project/Android/shared-ledger`（本切片不改业务 schema 或 RPC）

## 1. 范围

| 项 | 纳入 P5.8b | 说明 |
|---|---|---|
| `claim_participant` | 是 | 认领一个已存在的 Participant |
| `unclaim_participant` | 是 | 只能解除自己的认领 |
| `create_sub_activity(activity_id, name, participant_ids)` | 是 | 三参入口；两参兼容入口不在本切片 |
| `delete_sub_activity` | 是 | 软删除账本单元 |
| `restore_sub_activity` | 是 | 恢复并推进 `financial_version` |
| 成员移除 / Creator 转移 | 否 | 留给 P5.8c |
| 活动归档 / 删除 | 否 | 留给 P5.8c |
| legacy-unscoped 回填 | 否 | **不做**，旧子活动保持原样 |
| 业务 migration / RPC | 否 | 零业务 schema 变更 |
| 契约重导出 | 否 | 按要求留到 P5 出口门 |
| 训练数据 / LAN / 新 pin / 真机 | 否 | 按所有者要求 |

## 2. 接口

```text
claim_participant(activity_id, participant_id)
  -> claim_id, claimed_participant_id, is_new

unclaim_participant(activity_id)
  -> boolean            -- 是否真的删除了一行 claim

create_sub_activity(activity_id, name, participant_ids uuid[])
  -> parent_activity_id, ledger_unit_id, created_name, created_type

delete_sub_activity(sub_activity_id)
  -> sub_activity_id, activity_id, changed, is_deleted, financial_version

restore_sub_activity(sub_activity_id)
  -> sub_activity_id, activity_id, changed, is_deleted, financial_version
```

- Claim 的 Participant 身份始终来自 Activity 总名单；子活动不新建 Participant 实体。
- `create_sub_activity` 的三参版本没有 `participant_ids` 默认值，因此不会歧义命中两参兼容入口。
- 删除/恢复的入参只有 `sub_activity_id`；提案里另外记录 `activity_id` 用于授权与版本前置。

## 3. 业务边界

- **Claim**：同一用户在同一 Activity 只有一个 claim；重复认领同一 Participant 由服务端返回
  既有结果（`is_new=false`），不报错。目标已被他人认领 → 拒绝；调用者已认领了另一个
  Participant → 拒绝（服务端 23505，Agent 预览即拒绝）。
- **Unclaim**：只能解除自己的 claim；他人的 claim 不受影响。没有 claim 时预览直接拒绝。
- **子活动创建**：
  - Activity 必须为 large、未归档、未删除且存在 root ledger 单元（否则服务端 42501 /
    22023 / P0001）。
  - `participant_ids` 必须非空、无 null、无重复、全部属于该 Activity 且未删除；任一不合法
    服务端整体回滚（23514），不留下 child。
  - 创建成功时服务端写入 `sub_activity_participants` 并置 `participant_scope_configured=true`；
    本切片只负责发出这一次三参请求，不重复实现后续 payer/split 归属校验。
- **删除/恢复**：任何 Activity Member 都能操作（不是 Creator-only）；重复删除返回
  `changed=false`；恢复时服务端重建债务投影并推进 `financial_version`。
- **legacy-unscoped**：迁移前的旧子活动保持未配置状态；Agent 从不写
  `participant_scope_configured`，也不写 `sub_activity_participants`，因此不会回填。
- 已归档 / 已删除 Activity、非 large、非 `sub_activity` 单元一律按服务端返回处理：Agent
  预览不提前拒绝归档，而是在执行前比对归档/删除状态，变化则关闭。
- Agent 侧额外规则（服务端允许、Agent 为确定性而拒绝）：
  - 子活动名称与活动内现有未删除账本单元同名 → `sub_activity_name_conflict`。
  - delete/restore 的账本单元类型必须是 `sub_activity`。

## 4. 版本与幂等

五个 RPC 都没有 `expected_version` / `request_id`。执行前重读：

- Activity 归档 / 删除状态、`activities.type`；
- Participant 是否有效、是否已被认领（含"是否是本人认领"）；
- 子活动是否存在、是否已删除、是否仍属于该 Activity；
- `activities.financial_version`（五个操作都绑定；claim/unclaim 本身不修改它，绑定属于
  保守选择：预览后任何财务写入都会关闭该提案）。

任一与预览快照不一致 → 关闭提案、Turn `CANCELLED`、**0 次 RPC**。

- 重复确认：`confirm_and_dispatch` 保证只派发一次，同一 `execution_id`。
- 未知结果：Turn `RECOVERING` + `UNKNOWN`，不重发。
- 只读核对，一律 `closed`：
  - claim → 当前用户已有 claim → `claimed_elsewhere`；无 claim → `claim_not_applied`。
  - unclaim → claim 已不存在 → `released_elsewhere`；仍存在 → `unclaim_not_applied`。
  - 子活动创建 → 按名称 + 父活动找到未删除子活动 → `sub_activity_created_elsewhere`；
    否则 `sub_activity_not_created`。
  - 删除 → 已删除 → `sub_activity_deleted_elsewhere`；未删除 → `sub_activity_delete_not_applied`。
  - 恢复 → 已恢复 → `sub_activity_restored_elsewhere`；仍删除 → `sub_activity_restore_not_applied`。
  无法证明归属，因此从不落成功。

## 5. dev 桥命令

```text
认领 <参与人名字>
解除认领
建子活动 <名称> 参与人=<名字1>,<名字2>
删子活动 <名称>
恢复子活动 <名称>
```

示例：

```text
认领 Alex
建子活动 小组A 参与人=Alex,Rin
删子活动 小组A
恢复子活动 小组A
```

- 全部使用当前面板 Activity。
- 名字按当前活动未删除参与人唯一匹配；子活动按未删除/已删除的 `sub_activity` 账本单元
  唯一匹配。
- 名字匹配不到、重名、普通活动、参与人不在名单、子活动重名 → 拒绝，不调用模型、不发 RPC。
- 预览摘要带 `【P5 开发验证·认领】`（claim 与 unclaim 共用）/ `【P5 开发验证·子活动】`；
  `policy_version` 分别为 `p5-dev-claim-v1` / `p5-dev-sub-activity-v1`。

## 6. 契约扩展

- 新增 `ParticipantClaimIntent`、`ParticipantUnclaimIntent`、`SubActivityCreateIntent`、
  `SubActivityDeleteIntent`、`SubActivityRestoreIntent`。
- 新增 `FixedParticipantClaimCommand`、`FixedParticipantUnclaimCommand`、
  `FixedSubActivityCreateCommand`、`FixedSubActivityDeleteCommand`、
  `FixedSubActivityRestoreCommand`。
- `ManagementPreview` 增加 `participant.claim` / `participant.unclaim` /
  `subactivity.create` / `subactivity.delete` / `subactivity.restore` 五个 operation，以及
  `sub_activity_id` / `sub_activity_name` / `participant_names` 字段。
- 五个操作加入 `ProposalOperation` / `ProposalIntent` / `FixedCommand`，不进入模型输出 schema。
- 按要求不重导出契约；App 契约快照与卡片渲染留给 P5 出口门。

## 7. 验收与测试

| 验收 | 测试 | 结果 |
|---|---|---|
| Claim：合法成功；重复 claim 幂等；目标已被他人认领 → 拒绝 | `test_p5_claim_subactivity.py::test_claim_previews_and_executes`、`test_repeat_claim_is_idempotent`、`test_claim_refuses_a_participant_claimed_by_someone_else`、`test_claim_refuses_when_the_caller_already_claimed_another` | PASS |
| Unclaim：本人成功；无 claim 提示；他人 claim 不受影响 | `test_unclaim_previews_and_executes`、`test_unclaim_without_a_claim_is_refused`、`test_unclaim_reports_an_already_released_claim` | PASS |
| 建子活动：合法成功并返回子活动 ID；空/重复/名单外/普通活动 → 拒绝、0 次 RPC | `test_sub_activity_create_previews_and_executes`、`test_sub_activity_intent_rejects_an_empty_selection`、`test_sub_activity_intent_rejects_duplicate_ids`、`test_sub_activity_create_preview_rejections`、`test_sub_activity_create_rejects_participants_outside_the_roster` | PASS |
| 删子活动：成功；重复删除 `changed=false` 幂等；非成员拒绝 | `test_sub_activity_delete_and_repeat`、`test_sub_activity_lifecycle_rejects_non_members` | PASS |
| 恢复：成功且 `financial_version` 推进；未删除时 `changed=false` | `test_sub_activity_restore_advances_the_financial_version`、`test_sub_activity_restore_of_a_live_unit_is_idempotent` | PASS |
| 非 sub_activity 单元 → 拒绝 | `test_sub_activity_lifecycle_rejects_a_sibling_unit_kind` | PASS |
| 预览后 Activity 归档/版本变化 → 关闭、0 次 RPC | `test_preview_changes_close_without_an_rpc`（七参数） | PASS |
| 重复确认只写一次 | `test_duplicate_confirmation_sends_one_rpc` | PASS |
| 未知 → RECOVERING/UNKNOWN，核对到他人操作 → closed | `test_unknown_outcomes_always_close`（十参数） | PASS |
| legacy-unscoped 不被回填 | `test_legacy_sub_activities_are_never_backfilled_by_a_dispatch` | PASS |
| dev 桥：认领/解除/建/删/恢复与拒绝 | `test_p5_dev_bridge.py::test_dev_claim_bridge_*`、`test_dev_unclaim_bridge_*`、`test_dev_sub_activity_bridge_*` | PASS |

全量调用方式（两个 store 根每轮新建）：

```powershell
$env:PYTHONPATH="$PWD;$PWD\agent;$PWD\agent\tests"
$env:P2_STORE_TEST_ROOT="D:\tmp\p58b-<guid>-store"
$env:P2_V3_STORE_TEST_ROOT="D:\tmp\p58b-<guid>-v3"
New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT, $env:P2_V3_STORE_TEST_ROOT
.\agent\.venv\Scripts\python.exe -m pytest agent\tests -q
```

结果（2026-10-26，本提交）：`1021 passed, 1 xfailed`。

## 8. 已知限制

- 五个 RPC 都没有请求去重键，未知结果只能关闭。
- claim/unclaim 绑定 Activity `financial_version`：预览后任何财务写入都会关闭该提案，
  这是保守选择，不是服务端要求。
- 子活动同名拒绝是 Agent 规则，不是数据库约束。
- 子活动创建的三参请求只写 scope 一次；后续 payer/split 是否都在子集内由服务端触发器负责，
  本切片不重复实现。
- 不提供成员移除、Creator 转移、活动归档/删除、claim 之外的身份管理。
- 契约未重导出，App 暂不认识五种新预览与卡片。
- 未做真机验收；未改训练数据；未启用 LAN；未生成新 pin。`p2_runtime.py`、`store.py`
  在 P2 v3 manifest 内，pin 继续失效。

## 9. 回滚

- `AGENT_P5_DEV_INTENT_ENABLED=false` 关闭 dev 桥。
- `AGENT_LIVE_WRITE_ENABLED=false` 关闭全部真实写，confirm 回到 501。
- 本切片只认领/解除认领测试账号自己的 Participant，以及创建/软删除测试子活动；
  自动化不负责清理，由所有者在测试项目内处理。
