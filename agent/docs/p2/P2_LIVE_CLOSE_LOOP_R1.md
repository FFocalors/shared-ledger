# P2 当前 pin 真实闭环与身份恢复 R1（2026-10-18）

本文记录在 **当前 source/config pin** 上针对 `D:\AI\runs\shared-ledger\p2\` 隔离环境做的三组实测。它不是整体 P2 验收，也不改变任何冻结契约；业务写入全程关闭，`Gateway` 仍为 `Unimplemented`。

- pin：manifest `D:/AI/runs/shared-ledger/p2/native-runtime-resume-budget-20261018-02/p2-v3-execution-manifest.json`，SHA-256 `5df93c7fe360e8cedda27b2ca38379c031cd227768f31f7505c127bcd3dd92c6`
- 代码：`agent` 分支 `aaf9fc3`（全量套件 738 passed 的同一次提交），`agent/app/` 相对该提交无改动
- 环境：D 盘隔离 Supabase 栈（API `http://127.0.0.1:55421`，独立 project id，未触碰业务本机栈与任何云端）；LM Studio 本地 `t0-cp36-20261007`（Q4_K_M，context 8192，native `/api/v1/chat`，`reasoning=off`）
- harness：`D:/AI/runs/shared-ledger/p2/current-postfix-live-20261018-01/`（`bridge.py` 为 loopback HTTPS 转发器，`close_loop.py` 为驱动器）。驱动器只替换「模型输出从哪来」，其余全部走真代码
- 证据：同目录下各 `run-*/close-loop-result.json` 与 `run-*/model-response-*.json`

## 一、零模型 POST 闭环：通过

`P2Runtime._generate_v3_model` 被替换为脚本生成器，因此**零模型 POST**；决策文本取自更早一次真实模型输出（`stageD-native-activities-ae7fa73fa7/server-log-recovered-native-response.json`）。其余全部真实：

| 项 | 实测 |
|---|---|
| 回合状态 | `COMPLETED` |
| 读取操作 | `read.activities` |
| 真实 Auth 校验 | `/auth/v1/user` 200 × 11（经 TLS 桥打到真实 GoTrue） |
| 真实 RLS 读取 | `/rest/v1/activities` 200 × 2、`/rest/v1/activity_members` 200 × 3 |
| source GET 收据 | 2 |
| query attempt / 结果收据 | 1 / 1（page 0） |
| fact proof | 1 |
| 受保护答案 | 1，`kind=answer`，`citations=[qev_DEjqNKfrMDYL6mTP99_nQfKHrUU]` |
| output→query 链接 | 1（与上面的 QEV 同值） |
| 桥拒绝 | 0 |
| 业务写入 | 0 |

结论：当前 pin 的「真实身份/RLS/类型化读取 → Store 接受 → QEV/fact → 受保护答案」这条链在本机隔离库里是通的。这是 R3 里「最新代码的真实闭环未测」在**无模型**条件下的补齐，**不能**当作模型侧通过。

## 二、真实模型闭环：3 次 Turn，1 次通过

同一驱动，改用真实 native transport，硬上限 2 次 POST（读决策 + 答案）。

| 次数 | 结果 | 模型 POST | 说明 |
|---|---|---|---|
| 1 | FAILED | 2 | 读成功、答案被拒 |
| 2 | FAILED | 2 | 同上，已留存原始响应 |
| 3 | **COMPLETED** | 2 | 全链路闭环 |

第 3 次实测（`run-4fd9813a7d-live/`）：POST 1 模型自主选择
`{"kind":"read","message_type":"query_request","operation":"read.activities","scope":null,"criteria":{"kind":"activities","status":"any","name_contains":null},...}`，通过严格 sent guard 与 parser；随后真实读取（`activities` ×2、`activity_members` ×3）→ 2 条 source GET 收据、1 个 page-0 结果收据、1 个 fact proof；POST 2 输出

```json
{"kind":"answer","basis":"fresh_read_receipts","citations":["qev_ZF8nKKkmnK2itWADnby9HRVgbrg"],"text":"当前活动：P2 postfix close loop 4fd9813a7d。"}
```

引用的正是本次新铸的 QEV；文本里的活动名 `P2 postfix close loop 4fd9813a7d` 是本次运行刚通过真实 RPC 创建的活动，模型不可能先验知道，**接地是端到端的**。三次运行的两次 POST 均 HTTP 200，`reasoning_output_tokens` 均为 0（native `reasoning=off` 生效），输入 1724/2419 tokens，均远低于 6144 上限。

### 两次失败的精确原因（模型侧协议不遵循）

两次失败的答案输出（`run-a83b909b56-live/model-response-02.json`）：

```json
{"kind":"answer","basis":"fresh_read_receipts","citations":["qev_bLavUnk1JLdv-hstdJ6XCgf0Fno"],
 "text":"当前活动列表包含 1 条记录。",
 "source_query_complete":true,"model_projection_complete":true,"has_more":false}
```

`kind`、`basis`、citation（也是正确的新 QEV）、文本均正确，但 `P2AnswerDecision` 只声明 `kind`/`basis`/`text`/`citations` 四个字段，多出的 `source_query_complete`、`model_projection_complete`、`has_more` 属契约未声明字段，严格 sent guard 按契约拒绝，回合以 `FAILED` 收场。

性质判定：**这是模型侧未遵循既有契约，不是契约或实现缺陷。** 与 R2 记录的「answer 多出根字段 `type`」同类；`direct-decision-hint-r3` 抑制了旧协议字段名，但模型会从上下文 page-summary 的词汇里新造字段。契约不应为此放宽。

样本：3 次 Turn、其中 2 次失败于同一原因、1 次通过。**这是 1/3，不是通过率结论**；按 T1 口径仍为 `INSUFFICIENT_SAMPLE`。

## 三、真实身份恢复（`/resume/auth`）：机制可用，但暴露两个问题

做法：由 `bridge.py` 把 `/auth/v1/user` 在受控条件下返回 **503**（真实的上游不可用，而非凭证被拒），触发运行时 `_P2DependencyPause` → 回合按 `WAIT_INPUT/AUTH_REQUIRED` 挂起并撤销内存授权；随后解除故障，用公开路由 `POST /v1/turns/{id}/resume/auth` 带同一用户的新鲜凭据恢复。

两次臂发都是**恰好一次** 503（`auth_503_count: 1`），且挂起判定正确（`DEPENDENCY_UNAVAILABLE` / `auth_verifier_unavailable`，`resume_state=QUEUED`）。

### 3a 故障发生在查询描述符绑定之前

- 挂起时 `receipts=0`、`queries=0`、无 attempt → 没有可复用的描述符
- `resume_status: 202`，恢复后回合重新规划，随即以 `RATE_LIMITED` / 「P2 planning generation budget reached.」**终态失败**

即：R3 描述的「复用不可变逻辑查询描述符、不重做规划」这条恢复路径**预设描述符已存在**；描述符尚未绑定时，恢复只能重新规划，而 v3 读取路径预定的模型调用额度仍被计入，于是撞额度终态。**这是有界限制，需在文档与产品上与「已绑定」情形区分开。**（证据：`run-0032e9cff5-offline-resume/`）

### 3b 故障发生在查询描述符绑定之后 —— 机制对，但回合被遗弃（未定位的缺陷）

把臂发点改为「首次成功服务 `/rest/v1/activities` 之后」，挂起时 `receipts=2`、`queries=1`、`attempt_seq=[1]`。恢复后实测（`run-ec19ff3b13-offline-resume/`、`run-6c67894abe-offline-resume/`，离线模式，3/3 同现象）：

| 期望（R3） | 实测 |
|---|---|
| 复用原逻辑查询，不重新规划 | ✅ `query_ids_after_resume` 只有 1 个；脚本生成器只被调用 1 次且 phase 为 `read_decision`，恢复后未再调用 |
| 新 attempt 从 page 0 重读 | ✅ `attempt_seq_after_resume=[1,2]`，`attempt_pages=[0,0]`；`/rest/v1/activities` ×2、`activity_members` ×2 |
| 不额外消耗逻辑读取与模型调用 | ✅ `logical_read=1`、`model_calls=3` 与暂停前一致 |
| **沿原查询完成后续答案** | ❌ **未发生**：答案派发从未发出 |

失败形态：回合最终停在 `RUNNING` / `step=model_decision` / `state_revision=5`，**仍持有 claim token**，`_p2_states` 为空（运行时的 per-turn 任务已结束），模型信号量空闲（`_model_gate` 值为 1，不是资源死锁），且**没有任何终态或暂停事件**写入。规划逃逸记录为 `_P2DependencyPause`（即挂起本身）之后的一笔 `asyncio.CancelledError`——即第 2 次规划任务被取消，任务结束时回合被**遗弃在 RUNNING**。

带时间戳的运行（`run-8c84210f97-offline-resume/`）证明取消发生在**运行过程中**而不是 harness 退出时：第 1 次规划 2.67s 进入、8.22s 以挂起逃逸；第 2 次规划 18.42s 进入、**23.25s 被取消**（存活 4.8 秒），而本次 harness 的轮询截止是 70 秒。

未定位的部分：取消第 2 次规划的来源没有查到。已知 `_await_turn_grant` 超时只会抛 `_AuthRequired`，`_renew_loop` 续租失败只 return（不取消），`_LEASE_SECONDS=30` 与 4.8 秒不符；而 `asyncio.Task.cancel` 是不可变的 C 方法，无法从 harness 侧挂钩记录调用栈。据此把这一项记为**待 owner 处置的缺陷**，而不是本次能定性归因的结论。**在此项修复前，不应把「真实身份恢复」记为 P2 通过。**

## 四、本文不建立什么

- 不建立 v3 candidate 的基线地位。已核实存在两条 root 记录，但都限于候选范围：`D:/AI/runs/shared-ledger/p2/root-runtime-integration-20261014/ROOT_V3_CONTRACT_IMPLEMENTATION_R1.md` 批准的是一个**未装配**的 v3 candidate，并明确「不是正式 T1 freeze/training/CAP/release，不是生产路由或模型运行批准」；`D:/AI/runs/shared-ledger/p2/v3-source-codec-backend-final-r4-20261015T0331Z-luna/ROOT_R4_NULLABLE_AND_SOURCE_LIMITED_REVIEW.json` 的裁决为 `ACCEPTED_FOR_DISABLED_CPU_CANDIDATE_FOUNDATION_ONLY`。后续把该 candidate 实际装配进 Runtime/Store/API，已超出当时「unassembled」的批准表述；是否存在把它作为基线的裁决，见 `P2_V3_PROFILE_STATUS.md`。
- 不建立云端 Supabase 的 Auth/RLS 结论（全程本机隔离栈）
- 不建立模型质量结论（同名任务 3 次样本；两次失败为协议不遵循，一次通过；`INSUFFICIENT_SAMPLE`）
- 不建立 LM Studio 的 `parallelism` 设置（本轮未能读到该字段；R2 记录过旧失败样本为 parallel 4、完成样本为 parallel 1，故延迟不可比）
- 不建立业务写入路径（`Gateway` 仍 `Unimplemented`，两次 POST 之外无任何写调用；桥只转发 GET 且路径白名单，拒绝计数为 0）
- 不建立 CAP01–CAP17（仍为 0/17）

## 五、建议的下一步

1. **处置 3b**：定位取消已恢复规划任务的来源，并确保任何规划逃逸都落到终态或暂停事件，不允许出现「RUNNING + 持有 claim + 无事件」的遗弃态。
2. **针对模型的多余根字段**：按任务边界，改提示词前先在 `agent/docs/p2/` 出差异说明并交 root 评审；不得放宽严格 guard，也不得静默修改 v3 契约。可优先考虑在 r3 hint 里显式列出「answer 根对象恰为 kind/basis/text/citations，禁止复制上下文 page-summary 字段」。
3. 在 3b 修复后再重跑一次 live-resume，作为身份恢复的真实模型证据。
