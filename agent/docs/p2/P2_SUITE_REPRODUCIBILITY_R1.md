# P2 套件可复现性：一条时间相关的不稳定用例（R1）

**状态：发现并记录，未修。** 本文只描述实测与机理，不改任何生产代码。相关生产行为（存储校验失败即拒绝启动）是**正确的 fail-closed**，问题在测试侧。

## 现象

全量 `agent/tests` 在三种调用方式下结果不同：

| 调用方式 | 结果 |
|---|---|
| 全量套件（`agent/tests` 整个目录，pytest 默认文件序） | **绿**：基线 `aaf9fc3` 为 738 passed；分页补口后为 **743 passed, 1 xfailed** |
| 只跑 `agent/tests/test_p2_v3_store_recovery_edges.py` | **红**：3/3 次均为 `1 failed, 40 passed` |
| 只跑该单条用例 | **绿**：`1 passed in 5.33s` |

失败用例：`test_two_store_connections_only_one_consumer_can_claim_continuation_nonce`

失败形态：

```text
agent\app\store.py:508: StorageStartupError:
  configured SQLite storage failed migration or integrity verification
```

即**第二个 Store 连接在重开校验时拒绝启动**（不是放行坏数据）。

## 机理

该用例在 `tests/test_p2_v3_store_recovery_edges.py:2201` 用
`wall_start = datetime.now(timezone.utc).replace(microsecond=0)` 作基准，随后用 `wall_start + 1s / +2s / +4s / +8s` 合成 `reserved`、`dispatch_started`、`consume(now=...)` 等事件时间戳；而 fixture 内另有**真实时钟**写入的事件（结算类）。Store 重开时按 `reservation_id` 校验同一预留的事件必须按 `occurred_at` 有序，于是当真实时钟**尚未越过 `wall_start + 2s`** 时，真实时钟写入的事件排在合成事件之前，校验 fail closed。

这解释了"快则失败、慢则通过"的反向相关：

- **单跑**：fixture 冷启动耗时长（5.33s），真实时钟已越过合成的 `+2s`，通过
- **随文件跑**：前序用例已把缓存热起来，本用例更快（<2s），真实时钟未越过 `+2s`，失败
- **全量跑**：本用例之前还有约 40 个文件的测试，机器更热更忙，本用例更慢，通过

因此"全量 738/743 passed"是**在该调用方式下成立**的结果，不应被读成这条用例本身稳定。

## 已尝试但未采用的修法

把基准整体推早（`- timedelta(seconds=30)`），使全部合成时间戳落在过去、真实时钟写入必定排在其后。结果：该用例改为以**另一种**失败告终——`agent\app\p2_read_backend.py:1231` 抛出 `P2ReadBackendError: upstream_failure`（单跑 1.81s 即失败），说明改基准会破坏 fixture 其它以真实时钟为参照的时序假设。**已回退，未保留。**

结论：这不是"改一行基准"就能安全解决的问题，需要该类 fixture 统一走**单一注入时钟**（合成与真实写入不得混用），或让 Store 的重开校验接受显式的逻辑时钟。属测试基建改造，留 P2 owner 处置。

## 影响与建议

- 引用 P2 测试结论时必须同时给出**调用方式**（全量 / 单文件 / 单用例）；本文与其它文档中的"738/743 passed"均指全量目录调用。
- 建议把 `test_p2_v3_store_recovery_edges.py` 内所有 `datetime.now(timezone.utc)` 合成点（另见 `:781`、`:823`、`:1102`、`:1432`、`:2101`、`:2296`、`:2372`、`:2413`、`:2461`、`:2572`）一次性改为注入时钟，避免同类倒数式 flake 继续出现；本用例是当前唯一被观测到的失败点。
- 该用例**单独跑必过**，因此不应据单次失败判定生产缺陷；其失败路径恰好证明 Store 在账本不一致时拒绝启动。

## 证据

- 隔离跑 3/3 失败：`D:/AI/runs/shared-ledger/p2/flakecheck-*`
- 单跑通过：`D:/AI/runs/shared-ledger/p2/base-single-*`（`1 passed in 5.33s`）
- 按文件跑的真实异常：`D:/AI/runs/shared-ledger/p2/base-order-*`
- 失败修法（已回退）：`D:/AI/runs/shared-ledger/p2/fixdbg-*`、`D:/AI/runs/shared-ledger/p2/fixcheck-*`
- 全量绿：`D:/AI/runs/shared-ledger/p2/commit-baseline-20261018-03/`（738 passed）、`D:/AI/runs/shared-ledger/p2/recheck-full-20261018-04/`（743 passed, 1 xfailed）
