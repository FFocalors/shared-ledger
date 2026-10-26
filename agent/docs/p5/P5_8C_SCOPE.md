# P5.8c Creator 管理：成员、创建者、归档与删除

状态：**实现完成，自动化验收通过；真机由所有者统一验收**（2026-10-26）
分支：`agent`
业务基线：`D:/project/Android/shared-ledger`（本切片不改业务 schema 或 RPC）

## 1. 范围

| 项 | 纳入 P5.8c | 说明 |
|---|---|---|
| `remove_activity_member` | 是 | 仅撤销账号访问 |
| `transfer_activity_creator` | 是 | 转移给另一名现有成员 |
| `archive_activity` | 是 | 返回债务 / 预存 / 未结清摘要 |
| `unarchive_activity` | 是 | 仍是 Creator-only |
| `delete_activity` | 是 | 逻辑删除，仅未归档 |
| 恢复已删除活动 | 否 | 无入口 |
| 物理删除 | 否 | 无入口 |
| 子活动归档 | 否 | 子活动没有独立归档入口 |
| 强制完成 | 否 | 无入口 |
| 业务 migration / RPC | 否 | 零业务 schema 变更 |
| 契约重导出 / 新 pin / 真机 | 否 | 留到 P5 出口门 / 所有者 |

## 2. 接口

```text
remove_activity_member(activity_id, user_id)          -> boolean
transfer_activity_creator(activity_id, new_creator_user_id) -> uuid
archive_activity(p_activity_id)                       -> activity_id, archived, changed,
                                                         archived_at, total_debt,
                                                         total_prepayment, completed,
                                                         has_unsettled, warning
unarchive_activity(p_activity_id)                     -> (同上)
delete_activity(activity_id)                          -> boolean
```

注意 `archive_activity` / `unarchive_activity` 的参数名带 `p_` 前缀，payload 必须与之一致。

## 3. 业务边界

- 五个操作**全部 Creator-only**：服务端以 `created_by = auth.uid()` 判定；其他成员与非成员
  一律 `42501`。Agent 在预览阶段就拒绝非 Creator（`creator_permission_required`）。
- **移除成员**：不能移除自己；目标必须是现有成员；只删除 `activity_members` 一行，
  Participant 行与全部历史账务保持不变。已归档活动上的成员移除由服务端拒绝。
- **转移 Creator**：目标是另一名现有成员；不能转给自己；Activity 必须有效、未归档、未删除。
- **归档**：未结清也可归档；服务端返回债务合计、预存余额合计、`has_unsettled` 与提示原文，
  Agent 原样写进执行结果摘要。归档后该 Activity 的财务写入由服务端变为只读。
- **取消归档**：必须仍是 Creator；不改变债务与预存。
- **逻辑删除**：只允许未归档活动。Agent 在预览阶段对已归档活动直接拒绝并提示先取消归档；
  若服务端仍返回 `42501`，Agent 如实落 `REJECTED`（不伪装成成功或关闭）。
- 子活动没有独立归档入口，本切片不实现；不提供恢复已删除活动、物理删除或强制完成。

## 4. 身份映射（dev 桥）

- 成员是 **User**，不是 Participant。
- `移除成员` / `转移创建者` 接受 Participant 名字时，必须先在该 Activity 的
  `participant_claims` 中找到这个人对应的认领；未认领、重名、找不到一律拒绝并说明原因，
  绝不猜测。
- 预览同时显示 Participant 名字与脱敏用户标识（`前 8 位…后 4 位`），方便验收者确认目标。
  目标没有认领时（直接 API 路径）只显示用户标识并注明“未认领参与人”。

## 5. 版本与幂等

五个 RPC 都没有 `expected_version` / `request_id`。执行前重读：

- Activity 的 `archived_at`、`is_deleted`、`created_by`；
- 成员列表（`remove` / `transfer`：对排序后的 user id 列表取 SHA-256 摘要作为快照，
  任何成员变化都会关闭提案）；
- 当前调用者仍是 Creator。

任一与预览快照不一致 → 关闭提案、Turn `CANCELLED`、**0 次 RPC**。

- 重复确认：`confirm_and_dispatch` 保证只派发一次，同一 `execution_id`。
- 未知结果：Turn `RECOVERING` + `UNKNOWN`，不重发。
- 只读核对，一律 `closed`：
  - 成员移除 → 目标已不在成员列表 → `member_removed_elsewhere`；仍在 → `member_remove_not_applied`。
  - Creator 转移 → `created_by` 已不是原 Creator → `creator_transferred_elsewhere`；未变 →
    `creator_transfer_not_applied`。
  - 归档 → 已归档 → `archived_elsewhere`；未归档 → `archive_not_applied`。
  - 取消归档 → 未归档 → `unarchived_elsewhere`；仍归档 → `unarchive_not_applied`。
  - 删除 → `is_deleted` → `activity_deleted_elsewhere`；未删除 → `delete_activity_not_applied`。
  无法证明归属，因此从不落成功。

## 6. dev 桥命令

```text
移除成员 <参与人名字>
转移创建者 <参与人名字>
归档活动
取消归档
删除活动
```

示例：

```text
移除成员 Alex
转移创建者 Alex
归档活动
取消归档
删除活动
```

- 全部作用于当前面板 Activity。
- `移除成员` 目标是自己 → 拒绝；目标未认领/重名 → 拒绝。
- `转移创建者` 目标不是成员/是自己/未认领 → 拒绝。
- `删除活动` 在已归档活动上 → 拒绝并提示「活动已归档，请先取消归档」。
- 预览摘要带 `【P5 开发验证·管理】`，`policy_version = p5-dev-activity-admin-v1`。
- 归档预览必须列出未结清摘要（债务 / 预存）与警告原文；未结清时明确写出提示。

## 7. 契约扩展

- 新增 `ActivityMemberRemoveIntent`、`ActivityCreatorTransferIntent`、
  `ActivityArchiveIntent`、`ActivityUnarchiveIntent`、`ActivityDeleteIntent`。
- 新增 `FixedActivityMemberRemoveCommand`、`FixedActivityCreatorTransferCommand`、
  `FixedActivityArchiveCommand`、`FixedActivityUnarchiveCommand`、
  `FixedActivityDeleteCommand`（后两者要求 Activity 版本前置；全部要求 Creator 与归档状态前置）。
- `ManagementPreview` 增加
  `activity.member.remove` / `activity.creator.transfer` / `activity.archive` /
  `activity.unarchive` / `activity.delete`，以及 `target_user_ref`、`unsettled`、
  `financial_summary` 三个字段。
- 五个操作加入 `ProposalOperation` / `ProposalIntent` / `FixedCommand`，
  不进入模型输出 schema。
- 按要求不重导出契约。

## 8. 验收与测试

| 验收 | 测试 | 结果 |
|---|---|---|
| 移除成员：Creator 成功；移除自己拒绝；目标非成员拒绝；非 Creator 拒绝、0 次 RPC | `test_p5_activity_admin.py::test_member_remove_previews_and_executes`、`test_member_remove_preview_rejections`、`test_member_remove_cannot_target_the_creator` | PASS |
| 移除后 Participant 与历史账务仍在（只发成员 RPC） | `test_member_remove_previews_and_executes`（payload 仅 `activity_id`/`user_id`） | PASS |
| 转移 Creator：成功；目标非成员/自己/非 Creator 拒绝 | `test_creator_transfer_previews_and_executes`、`test_creator_transfer_rejections`、`test_creator_transfer_command_cannot_target_the_creator` | PASS |
| 归档：成功并返回未结清摘要；非 Creator 拒绝 | `test_archive_previews_with_the_unsettled_summary_and_executes`、`test_archive_rejects_a_non_creator`、`test_archive_is_idempotent` | PASS |
| 归档后写入由服务端拒绝、Agent 落 rejected | `test_archived_activity_management_write_is_rejected_by_the_server` | PASS |
| 取消归档：成功；非 Creator 拒绝 | `test_unarchive_previews_and_executes`、`test_unarchive_reports_a_live_activity`、`test_unarchive_rejects_a_non_creator` | PASS |
| 删除活动：未归档成功；已归档拒绝；非 Creator 拒绝；服务端 42501 → REJECTED | `test_delete_previews_and_executes`、`test_delete_refuses_an_archived_activity_before_any_rpc`、`test_delete_refuses_a_non_creator`、`test_delete_server_rejection_is_reported` | PASS |
| 预览后成员/creator/归档变化 → 关闭、0 次 RPC | `test_preview_changes_close_without_an_rpc`（五参数） | PASS |
| 重复确认只写一次 | `test_duplicate_confirmation_sends_one_rpc` | PASS |
| 未知 → RECOVERING/UNKNOWN，核对到他人操作 → closed | `test_unknown_administration_outcomes_always_close`（十参数） | PASS |
| dev 桥：五条命令、身份映射与拒绝 | `test_p5_dev_bridge.py::test_dev_member_remove_bridge_*`、`test_dev_creator_transfer_bridge_*`、`test_dev_activity_lifecycle_bridge_*`、`test_dev_member_and_admin_refusals` | PASS |

全量调用方式（两个 store 根每轮新建）：

```powershell
$env:PYTHONPATH="$PWD;$PWD\agent;$PWD\agent\tests"
$env:P2_STORE_TEST_ROOT="D:\tmp\p58c-<guid>-store"
$env:P2_V3_STORE_TEST_ROOT="D:\tmp\p58c-<guid>-v3"
New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT, $env:P2_V3_STORE_TEST_ROOT
.\agent\.venv\Scripts\python.exe -m pytest agent\tests -q
```

结果（2026-10-26，本提交）：`1058 passed, 1 xfailed`。

## 9. 已知限制

- 五个 RPC 都没有请求去重键，未知结果只能关闭。
- 归档后普通财务写入（记账/改账/删除等）在 Agent 侧更早就被 `_require_writable_activity`
  以 `scope_denied` 关闭（0 次 RPC），比服务端的只读拒绝更严格；服务端的 `55000`
  「archived activity is read-only」也映射为 `REJECTED`（`activity_read_only`）。
- 成员列表快照用 SHA-256 摘要，只用于“是否变化”，不用于任何授权判断。
- 归档摘要里的债务/预存来自服务端 `activity_financial_status` 视图；归档执行结果以 RPC
  返回为准，两者不一致时以执行为准。
- dev 桥的身份映射依赖认领；未认领的成员无法用 Participant 名字操作（需要后续 App 入口）。
- 契约未重导出，App 暂不认识五种新的管理预览与卡片。
- P5 出口门仍未做：契约重导出、真机验收、P2 v3 pin 重新生成。`p2_runtime.py`、`store.py`
  在 manifest 内，pin 继续失效。

## 10. 回滚

- `AGENT_P5_DEV_INTENT_ENABLED=false` 关闭 dev 桥。
- `AGENT_LIVE_WRITE_ENABLED=false` 关闭全部真实写，confirm 回到 501。
- 本切片只操作测试活动的成员、创建者与生命周期；自动化不做补偿，由所有者在测试项目内处理。
