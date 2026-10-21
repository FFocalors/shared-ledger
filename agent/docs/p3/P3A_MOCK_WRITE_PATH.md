# P3a — Mock 写路径（工程实现记录）

**状态：引擎已实现并通过五条验收条件（Mock；其中"无权限/已归档在执行前拒绝"于 2026-10-21 补齐），HTTP 成功响应仍未开启（见差异提案）。** 本文记录 P3a 的实现、验收证据与边界。

## 1. 范围与形状

链条：**预览 → 用户确认 → 固定命令 → 原子执行 → 持久回执**。

- 预览与"等待确认"沿用既有 P1 Mock Runtime（`WAIT_CONFIRM` + `pending` proposal + nonce/digest/前置条件），本次不改。
- **确认**是唯一可以分配 `execution_id` 的边界（冻结契约已如此规定），本次把这条边界真正接通。
- **执行**在 Mock 中发生在一个独立的、可按键查账的账本里（`mock_execution_ledger`），而不是真实的业务数据库。
- **回执**是持久的：提案上的 `execution`（完整 `ExecutionIdentity`）、Turn 上的 `execution_resolution`、以及 `execution_result` 事件三者一致。

## 2. 两个重点

### 2.1 确定性 `execution_id`

不由随机数生成。冻结契约里已有 `derive_execution_id(actor_id, proposal_id, proposal_revision, operations_version)`：对稳定字符串做 `uuid5`，跨进程重启与旧备份都得到同一个值。P3a 的做法是：**在确认时调用它**，并把结果同时写进提案（`execution`）与 Turn（`execution`）。`ExecutionIdentity` 自身的校验器会拒绝任何非派生 id。测试 `test_execution_id_is_deterministic_and_bound` 钉住"同输入同值、换 revision/actor 即变值、非派生 id 被契约拒绝"。

### 2.2 结果未知的恢复：凭原键核对，不换键重做

写路径被刻意拆成**两次提交**，因为业务效果发生在 agent 之外，agent 无法与自己的回执做成一个事务：

1. `confirm_and_dispatch`：校验并**钉死** `execution_id`，提案 → `CONFIRMED`，Turn → `EXECUTING/DISPATCH`。提交。
2. `apply_mock_execution`：把固定命令的效果写入 Mock 账本（主键就是 `execution_id`），并**恰好一次**推进该活动的财务版本。提交。
3. `settle_mock_execution`：写 `execution_result` 事件 + 终态。提交。

如果进程死在第 2 与第 3 步之间，`recover_interrupted_turns` 会把 `EXECUTING` 的 Turn 移到 `RECOVERING/RECONCILE`；运行时恢复钩子（`_inspect_recovery_checkpoint`）随后调用 `reconcile_mock_execution`：**先按键查账**，若效果已在则直接结算为 `SUCCEEDED`，若不在则用同一个键补做一次再结算。任何异常都只把 Turn 留在可恢复态，**绝不会**把未知结果写成终态，也**不会**生成新键重做。

## 3. 四条验收条件与对应用例

| 通过条件 | 用例 |
|---|---|
| 未确认不落账 | `test_unconfirmed_proposal_applies_no_effect`（无账本行、提案仍 `PENDING`、Turn 仍 `WAIT_CONFIRM`、`execution` 为空） |
| 同请求无重复效果 | `test_repeated_confirmation_cannot_apply_a_second_effect`（第二次确认被拒；重复 `apply` 返回 `applied=False`；账本 1 行；财务版本只推进 1） |
| 并发改账使旧预览失效 | `test_concurrent_ledger_change_invalidates_the_preview`（账本版本被第三方推进 → 确认抛 `MockPreconditionConflict`，且未派发、未落账） |
| 响应丢失能找回 | `test_lost_response_is_reconciled_with_the_same_key` 与 `test_restart_recovery_reuses_the_original_key`（效果已落 → 标记 `UNKNOWN` 或重启恢复 → 按原键结算成功，账本仍 1 行、`execution_id` 不变） |
| 无权限 / 已归档在执行前拒绝 | 见 §3.1 的 6 条用例 |

补充：`test_confirmation_dispatches_deterministic_identity_and_applies_once`（正常闭环，逐段断言"派发本身不落账"）、`test_dispatch_refuses_a_simulation_proposal`（模拟提案不可执行）、`test_runtime_recovery_hook_settles_under_the_original_key`（直接驱动运行时 `_inspect_recovery_checkpoint`，而不是只测 store 方法）。

### 3.1 无权限与已归档：执行前拒绝（2026-10-21 补齐）

**先说清前提：这两条在补齐前不存在，不是"已实现、仅补证据"。** 补齐前的实际状态是：

- `PreconditionSnapshot.permission_checked` 的类型是 `Literal[True]`——契约**要求**它是 `True`，但这是预览方的**声明**，Store 从不验证谁检查过；
- `MockScopeAuthorizer` 只接受唯一夹具活动，且只在 HTTP/Runtime 的 scope 检查里使用，**不在 P3a 的派发/落账路径上**；
- Mock 账本与固定命令里**完全没有** `archived` 概念（`mock_ledger_state` 只有财务版本）。

所以一个"无权限"或"已归档"的提案在当时会照常派发并落账。现在补上的形状：

| 概念 | 落点 |
|---|---|
| 权限与生命周期的显式模型 | `app/p3_execution.py` 的 `MockActivityRoster` / `MockActivityAccess`（成员集合 + `archived`）；Mock 没有成员表，只能显式建模，否则检查永远不可能拒绝 |
| 拒绝类型 | `MockWriteRefused` → `MockPermissionDenied`（`code=actor_not_permitted`）/ `MockActivityArchived`（`code=activity_archived`） |
| 派发前 | `confirm_and_dispatch(..., activity_guard=...)` 在推导出效果后、推进任何状态前调用 guard |
| 落账前 | `apply_mock_execution(..., activity_guard=...)` 在插入账本行前调用；**已落账的重放（`existing is not None`）先返回，不被后来的归档改写** |
| 恢复路径 | `reconcile_mock_execution(..., activity_guard=...)`：效果未落且此刻被拒 → 以原键结算为 `REJECTED`（Turn `FAILED`），而不是把写入偷偷落下去或把 Turn 挂在 `RECOVERING` |
| 运行时接线 | `MockRuntime(..., activity_roster=...)`；恢复钩子把 `writable_guard(owner_id)` 传下去。未提供 roster 时行为与之前完全一致 |

六条用例：

| 用例 | 钉住什么 |
|---|---|
| `test_actor_without_permission_cannot_dispatch_a_write` | 非成员（或活动不存在）→ 派发抛 `MockPermissionDenied`；Turn 仍 `WAIT_CONFIRM`、提案仍 `PENDING`、账本 0 行、财务版本 0 |
| `test_archived_activity_cannot_dispatch_a_write` | 已归档 → 派发抛 `MockActivityArchived`，同上全部不变量 |
| `test_permission_revoked_after_preview_is_refused_at_dispatch` | **预览时是成员、确认前被移除** → 仍在派发前被拒（证明检查不是只在预览时做一次） |
| `test_archived_after_dispatch_is_refused_before_the_effect_lands` | 派发成功后归档 → `apply` 被拒、账本 0 行；由调用方以同一键结算 `REJECTED`，Turn `FAILED`、提案 `REJECTED`、`execution_id` 不变 |
| `test_recovery_hook_refuses_an_archived_activity_under_the_original_key` | 未知结果 + 归档 → 运行时恢复钩子**拒绝落账**并按原键结算 `REJECTED`，账本 0 行、财务版本 0 |
| `test_an_already_applied_effect_is_reported_after_archive_not_refused` | 效果已落之后才归档 → 重放返回 `applied=False`，不抛错、不重复、不改写历史 |

**边界（必须一并引用）**：guard 由调用方注入，Store 并不知道权限从哪来；在 P3b 接入真实后端前，"谁提供 roster、与真实 RLS 如何对齐"仍未建立。它证明的是**检查点位置正确且拒绝发生在效果之前**，不是真实权限模型正确。

结算方法在**被 claim 的恢复路径**上必须携带 `claim_token`（`transition_turn` 的 CAS 要求）；运行时钩子已经把 `claimed.claim_token` 传下去，store 的三个结算方法也接受该可选参数。这是实现时踩到的一个真实约束，已在测试中覆盖。

## 4. 实现落点

| 文件 | 内容 |
|---|---|
| `agent/app/p3_mock_execution_migration.sql` | 迁移 007：`mock_ledger_state`（每活动财务版本）、`mock_execution_ledger`（效果，`execution_id` 主键 + `(proposal_id, proposal_revision)` 唯一） |
| `agent/app/p3_execution.py` | 纯语义：固定命令 → 确定性效果、期望财务版本校验、错误类型；`MockActivityRoster`（权限 + 归档的显式 Mock 模型） |
| `agent/app/store.py` | 迁移 007 接线；`confirm_and_dispatch` / `apply_mock_execution` / `settle_mock_execution` / `mark_execution_unknown` / `reconcile_mock_execution` / 账本读取与版本推进；`transition_turn` 新增 `execution_dispatch`（替代借用测试夹具门）与 `proposal_result_update`（结算时把已确认提案置为终态的窄门）；三条写路径接受可选 `activity_guard` |
| `agent/app/runtime.py` | `_inspect_recovery_checkpoint` 由"无适配器，park"改为按原键核对并结算；新增可选 `activity_roster` 并传给恢复路径 |
| `agent/tests/test_p3a_mock_write.py` | 上述 15 个用例（含直接驱动运行时恢复钩子的一条，以及 §3.1 的 6 条权限/归档用例） |

## 5. 边界（明确不做）

- **HTTP 成功响应未开启**：冻结的确认路由没有 2xx，仍返回 `501 ConfirmationUnavailableResponse`。要在 HTTP 上把确认当成功返回，需先批准 [确认响应差异提案](P3A_CONFIRM_RESPONSE_DIFF.md)。引擎与四条验收条件不依赖该提案。
- **不碰真实业务写入**：效果只写入 Mock 账本；没有任何 Supabase 调用、没有业务迁移。
- **P2 v3 防火墙不动**：`transition_turn` 里"v3 candidate 不得持久化/确认业务提案"的守卫原样保留；P3a 只对非 candidate 的 P1/Mock Turn 生效。
- **P3b 不做**：真实模型驱动的预览与真实后端执行留给 T3 之后。
- **T1 文件不动**：未改 `agent/docs/t1/`、`agent/dataset_contracts/`、`agent/evaluation/`。

## 6. 验证

```bash
# 定向
pytest agent/tests/test_p3a_mock_write.py -q   # 15 passed
```

全量套件的调用方式前提与结果见本文件末尾「验证记录」一节（整目录一次调用 + 两个 store 根目录每轮新建）。

## 7. 已知限制与后续

1. **Mock 账本不是业务库**：它证明的是 agent 侧的键、顺序、幂等与恢复，不证明任何真实业务规则（例如后端对金额/分摊/币种的最终裁决）。
2. **`mark_execution_unknown` 的触发**：P3a 由测试显式调用以模拟响应丢失；真实后端接入时（P3b）应在"请求已发出但结果不可判定"时调用它。运行时钩子已覆盖重启恢复与未知结算路径（有专门用例），但"发出请求后立刻判未知"的时机仍由调用方决定。
3. **单进程 Mock**：并发测试覆盖的是"账本被第三方改动使预览失效"，不是两个 agent 实例同时确认同一提案的竞争；后者依赖 Store 的 CAS（`proposal … status='pending'` 的 `rowcount`）已经具备，但没有专门的多进程用例。
4. 待批准后才能做的：HTTP 202 + receipt kind（见差异提案）。
5. **权限模型是注入的**：Store 只会在调用方给了 `activity_guard` 时才检查，roster 由调用方提供；"真实 RLS/角色如何映射成 roster"属 P3b，不能用本节的 Mock 用例推断真实权限已验收。

## 8. 验证记录

```bash
# 定向（15 个用例）
pytest agent/tests/test_p3a_mock_write.py -q                     # 15 passed
# 全量：agent/tests 整个目录一次调用；两个 store 根目录每轮新建为空
pytest agent/tests -q -p no:cacheprovider                        # 760 passed, 1 xfailed
export_contracts --check                                         # exit 0
```

证据目录：`D:/AI/runs/shared-ledger/p2/p3a-full-20261019-02/`（`baseline-result.json`、原始 stdout 与 SHA-256）。**调用方式前提与 P2 一致**：整目录一次调用 + 两个 store 根目录每轮新建；仅跑单文件或不新建目录时结果不保证一致。2026-10-21 的权限/归档补齐按同一调用方式重跑为 `760 passed, 1 xfailed`（store 根目录：`D:/AI/runs/shared-ledger/p2/p3a-guard-20261021-01/{store-root,v3-store-root}`，每轮新建）。

## 9. 对执行 pin 的连带影响（重要）

P3a 改动了 `agent/app/store.py` 与 `agent/app/runtime.py`，两者都是执行 manifest `362e66ad…e8a848` 的固定组件；逐组件复核现在是 **2 处 mismatch**。因此：

- 该 pin **不再匹配当前工作树**，任何 v3 live 运行会 fail closed；需要先重新生成 manifest。
- 更值得注意的一点：manifest 的组件是 `agent/app/p2_v3_manifest_cli.py` 里 `_ROLE_PATHS` 的**显式枚举**，新增的 `agent/app/p3_execution.py` **完全不在其覆盖范围内**。是否把 P3a 模块纳入 pin，属 cohort 所有者的决定；P3a 是 Mock/P1 路径，本文不擅自改动 v3 的必需角色集（改它会作废现有 pin 与已记录证据）。
- [P2 baseline calibration R1](../p2/P2_BASELINE_CALIBRATION_R1.md) 的证据绑定的是 `3fcb2fd` 那一刻的源码，不随本次改动失效；但它引用的 pin 已不能用于当前树，引用时须同时说明这一点。
