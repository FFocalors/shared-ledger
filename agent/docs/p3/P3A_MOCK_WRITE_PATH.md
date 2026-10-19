# P3a — Mock 写路径（工程实现记录）

**状态：引擎已实现并通过四条验收条件（Mock），HTTP 成功响应仍未开启（见差异提案）。** 本文记录 P3a 的实现、验收证据与边界。

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

补充：`test_confirmation_dispatches_deterministic_identity_and_applies_once`（正常闭环，逐段断言"派发本身不落账"）、`test_dispatch_refuses_a_simulation_proposal`（模拟提案不可执行）。

## 4. 实现落点

| 文件 | 内容 |
|---|---|
| `agent/app/p3_mock_execution_migration.sql` | 迁移 007：`mock_ledger_state`（每活动财务版本）、`mock_execution_ledger`（效果，`execution_id` 主键 + `(proposal_id, proposal_revision)` 唯一） |
| `agent/app/p3_execution.py` | 纯语义：固定命令 → 确定性效果、期望财务版本校验、错误类型 |
| `agent/app/store.py` | 迁移 007 接线；`confirm_and_dispatch` / `apply_mock_execution` / `settle_mock_execution` / `mark_execution_unknown` / `reconcile_mock_execution` / 账本读取与版本推进；`transition_turn` 新增 `execution_dispatch`（替代借用测试夹具门）与 `proposal_result_update`（结算时把已确认提案置为终态的窄门） |
| `agent/app/runtime.py` | `_inspect_recovery_checkpoint` 由"无适配器，park"改为按原键核对并结算 |
| `agent/tests/test_p3a_mock_write.py` | 上述 8 个用例 |

## 5. 边界（明确不做）

- **HTTP 成功响应未开启**：冻结的确认路由没有 2xx，仍返回 `501 ConfirmationUnavailableResponse`。要在 HTTP 上把确认当成功返回，需先批准 [确认响应差异提案](P3A_CONFIRM_RESPONSE_DIFF.md)。引擎与四条验收条件不依赖该提案。
- **不碰真实业务写入**：效果只写入 Mock 账本；没有任何 Supabase 调用、没有业务迁移。
- **P2 v3 防火墙不动**：`transition_turn` 里"v3 candidate 不得持久化/确认业务提案"的守卫原样保留；P3a 只对非 candidate 的 P1/Mock Turn 生效。
- **P3b 不做**：真实模型驱动的预览与真实后端执行留给 T3 之后。
- **T1 文件不动**：未改 `agent/docs/t1/`、`agent/dataset_contracts/`、`agent/evaluation/`。

## 6. 验证

```bash
# 定向
pytest agent/tests/test_p3a_mock_write.py -q   # 8 passed
```

全量套件的调用方式前提与结果见本文件末尾「验证记录」一节（整目录一次调用 + 两个 store 根目录每轮新建）。

## 7. 已知限制与后续

1. **Mock 账本不是业务库**：它证明的是 agent 侧的键、顺序、幂等与恢复，不证明任何真实业务规则（例如后端对金额/分摊/币种的最终裁决）。
2. **`mark_execution_unknown` 的触发**：P3a 由测试显式调用以模拟响应丢失；真实后端接入时（P3b）应在"请求已发出但结果不可判定"时调用它。当前 runtime 的恢复钩子只处理重启恢复路径。
3. **单进程 Mock**：并发测试覆盖的是"账本被第三方改动使预览失效"，不是两个 agent 实例同时确认同一提案的竞争；后者依赖 Store 的 CAS（`proposal … status='pending'` 的 `rowcount`）已经具备，但没有专门的多进程用例。
4. 待批准后才能做的：HTTP 202 + receipt kind（见差异提案）。

## 8. 验证记录

```bash
# 定向（8 个用例）
pytest agent/tests/test_p3a_mock_write.py -q                     # 8 passed
# 全量：agent/tests 整个目录一次调用；两个 store 根目录每轮新建为空
pytest agent/tests -q -p no:cacheprovider                        # 753 passed, 1 xfailed
export_contracts --check                                         # exit 0
```

证据目录：`D:/AI/runs/shared-ledger/p2/p3a-full-20261019-02/`（`baseline-result.json`、原始 stdout 与 SHA-256）。**调用方式前提与 P2 一致**：整目录一次调用 + 两个 store 根目录每轮新建；仅跑单文件或不新建目录时结果不保证一致。

## 9. 对执行 pin 的连带影响（重要）

P3a 改动了 `agent/app/store.py` 与 `agent/app/runtime.py`，两者都是执行 manifest `362e66ad…e8a848` 的固定组件；逐组件复核现在是 **2 处 mismatch**。因此：

- 该 pin **不再匹配当前工作树**，任何 v3 live 运行会 fail closed；需要先重新生成 manifest。
- 更值得注意的一点：manifest 的组件是 `agent/app/p2_v3_manifest_cli.py` 里 `_ROLE_PATHS` 的**显式枚举**，新增的 `agent/app/p3_execution.py` **完全不在其覆盖范围内**。是否把 P3a 模块纳入 pin，属 cohort 所有者的决定；P3a 是 Mock/P1 路径，本文不擅自改动 v3 的必需角色集（改它会作废现有 pin 与已记录证据）。
- [P2 baseline calibration R1](../p2/P2_BASELINE_CALIBRATION_R1.md) 的证据绑定的是 `3fcb2fd` 那一刻的源码，不随本次改动失效；但它引用的 pin 已不能用于当前树，引用时须同时说明这一点。
