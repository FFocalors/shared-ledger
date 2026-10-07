# P0 工程基线审计

审计日期：2026-10-06 至 2026-10-07。本文区分本轮文档执行员直接复核、主线已验证记录与仍待验证事项。范围仅为工程/业务事实映射、环境与资产盘点；不实现 Agent，不修改 App/后端源码、迁移或冻结训练资产。

## 仓库基线

本节记录 P0 原始核查时的 feature 工作区快照；分支和 HEAD 事实保留为历史证据，不代表拆分后的当前 Agent checkout。

| 项目 | 核验结果 | 证据边界 |
|---|---|---|
| 工作目录 | `D:\project\Android\shared-ledger` | 本轮工作目录 |
| 分支 / HEAD | `feature/ai-training-pipeline` / `dcdb033b9cc245f355f61b5a303007b7d7571e18` | 本轮只读 Git 检查；工作树原有未提交修改很多，不按本轮结果归属，也不覆盖或提交 |
| Agent 现状 | 有 `agent/README.md`、统一业务指南和历史模型契约/范围材料；没有 Agent 服务/执行 Harness | 本轮限定目录搜索；未来 Harness 并非 P0 静态映射的前提 |
| 仓库说明 | 根目录没有 `README.md` | 本轮检查 |
| 指令文件 | 仓库根及祖先目录没有 `AGENTS.md` | 仅覆盖已检查路径，不代表全机无此文件 |
| 统一指南 | 已逐段阅读 `agent/docs/shared-ledger-agent-development-guide-v0.4.html`，包括业务/CAP、P0–P6、T0–T4；CAP badge 按其所在表格行末尾匹配 | 指南是未来范围，不替代当前函数定义与 App payload；本次已知 CAP06 业务纠正优先于指南旧段落中的“总名单”表述，统一指南的同期修订由另一执行任务负责 |

本轮直接核对 `git branch --show-current`、`git rev-parse HEAD`、`git status --short`、`rg --files` 与目标源码。CAP01–CAP17 逐项映射见 [能力表](capability-map.md)。


## 拆分后的当前工作区（2026-10-07）

- Agent 文档工作区：D:/project/Android/shared-ledger-agent，分支 agent，HEAD dcdb033b9cc245f355f61b5a303007b7d7571e18；10 个 Agent 文档未提交，index 为空。
- 业务源码工作区：D:/project/Android/shared-ledger，分支 main，HEAD d305011b02e6105e2fe3e5b40460de4218d466ba；35 个业务文件未提交，index 为空。当前源码/迁移/测试证据链接指向此工作区。
- Agent worktree 的 app、supabase 与 docs/backend 是 feature HEAD 的已提交旧版本。核对当前业务实现和部署依据时使用 main 工作区，不能按 Agent worktree 的相对路径解析当前源码。

## 证据层级与部署边界

- 业务实际行为以迁移链中最后生效的 `CREATE OR REPLACE FUNCTION`、触发器/RLS/授权以及 Android 当前 repository/payload 为准。`docs/backend/api-contracts.md` 自身注明名字可能与实现不同；其中 owner/admin、`update_expense_with_allocations`、所有 update 共用 `expected_version` CAS、dispute 改 Transfer 状态等是旧草稿漂移，不能当作当前功能。
- 仓库中普通活动预存限制由 `supabase/migrations/20261006025641_normal_activity_prepayment_restrictions.sql` 明确：普通 Activity 的 prepayment preview/create/return 整笔拒绝，不把偿债部分转换成普通 Transfer。该 migration 的早期云端应用及 31 SQL / 235 pgTAP、265 unit、assemble、verifier 150 属于前序获授权执行记录；本次主线另以 fresh isolated DB 跑完 32 个 SQL 文件/237 个 pgTAP assertions、Android 268 项测试（0 failures/errors/skips）和 `assembleDebug`。不把隔离测试扩大为云端部署证据。既存 Haptics lint 的 `NewApi` 是构建检查失败，本轮不扩修或归入文档工作。
- 本地 `supabase_db_shared-ledger` 的 PostgreSQL 17.6 catalog 快照最近 migration 为 `20260925133211`；这是本地容器状态，不覆盖 linked remote 的独立状态。主线只对 remote ref `zecjkgvwpcvwheyflbyi` 应用 `20261006142507_sub_activity_participant_scopes.sql`（push exit 0、`--skip-vault`，无 seed/role 改动或生产业务测试行）。随后只读核查通过：migration history 有该 revision；`participant_scope_configured` 为 NOT NULL/default false；scope 表 RLS 仅允许 authenticated Member SELECT；两个 public create overload 仅 authenticated 可执行、anon/service_role 不可执行；旧 private helper 无 API role EXECUTE；三个 scope triggers enabled，projection wrapper 的 caller/linked-refund/rebuild guards 符合预期。本审计执行员没有迁移/reset 本地共享栈或写业务行。
- `20261006142507_sub_activity_participant_scopes.sql` 在执行员工作树内完成，通过上述隔离回归并按主线完成 remote catalog/ACL 只读核查；Android payload/按 ledger unit 过滤的本地改动也通过测试和 `assembleDebug`。这只核实此次 migration 和相关权限定义，不代表 CAP01–CAP17 已做真实客户端/全角色端到端验收。历史子活动无法反推出从未保存过的 Participant 选择；见 CAP06。

## Expense 版本、财务锁与回执

- 当前 App `ExpensePayload.kt` 中 `create_expense_auto_rate` / `update_expense_auto_rate` 财务 payload 没有 `expected_version`、`request_id`；`update_expense_presentation` 有可选 `expected_version`。财务 update 在事务中由数据库行锁/版本递增串行化，但没有调用方旧版本 CAS；presentation 若携带旧 version 则后端比较并拒绝。不能把 App 的版本提示描述为财务更新 CAS，也不能把“无客户端 CAS”说成无事务锁。
- `financial_locked` 的事实来源要精确区分：真实 Transfer 对 Expense 形成的 `transfer_source_expenses` / 有效分配历史会锁住该 Expense，作废 Transfer 不删除来源历史，锁不解开；`20260923032928_refund_limits_and_legacy_rpc_permissions.sql` 还引入 `private.expense_refund_sources`：存在过关联退款就会持久化该原始 Expense 的 refund-source 历史并永久锁住 original，即使退款后来 soft-delete、且没有真实 Transfer。退款来源表由 capture trigger 记录，历史 backfill 覆盖已有 link。被引用的 original 被锁，不等于每个 linked-refund 自身都已经有真实 Transfer 或 `financial_locked=true`。锁后 financial fields 与 Payment/Split 不可改，presentation 走独立 RPC；Expense 没有可调用 restore RPC。Transfer 不可编辑/恢复，只能适用时 void。证据：`20260921043414_expense_financial_lock_presentation_update.sql`、`20260923032928_refund_limits_and_legacy_rpc_permissions.sql`。
- 资金 v2 有后端幂等回执，不应泛化成“所有写入均无幂等”：`transfers.request_id/request_payload/request_result` 在事务中持久化；相同用户和 payload 会在 stale financial version 拒绝前 replay 原结果，冲突 key/payload 拒绝。见 `20260923022250_business_logic_finalization.sql` 的普通还款、Final、预存提交实现。Agent 跨操作 durable key、Expense 通用幂等回执及可靠未知结果恢复仍是后续工程工作。
- App 的 last-write-wins 行为保留。旧 D4 全局禁写是历史模型策略；未来 Agent 可在后端允许时做 preview，经用户确认修改未锁 Expense；不能越过后端 lock。

## 当前业务锚点

- CAP06 的业务目标和实现：大型子活动保存显式 Participant ID 集；付款人/分摊人只可来自该 scope，普通/root 可使用 Activity 全名单；任何 Activity Member 仍可记账，不能添加 actor 必须在 scope 的限制。新子活动允许仅选 1 人；历史旧子活动标为 legacy-unscoped。scope migration 已通过 fresh isolated DB 全回归且 linked remote catalog/ACL 只读核验通过。详见 [CAP01–CAP17 映射](capability-map.md) 中 CAP06 行。
- `20261006142507_sub_activity_participant_scopes.sql` 还带有跨 ledger-unit Expense 更新的投影修复：未锁合法移动先清除该 Expense 可重建 debt projection，更新事实与子项后重建费用/双边债务投影；真实 Transfer source、有效 allocation 或 linked-refund-source 历史移动拒绝。包含它的本次隔离数据库全回归已通过，linked remote projection wrapper guard/rebuild 定义也已只读核验；见能力表 CAP07/08。
- AA base 尾差按现后端 `participant_order,id` 稳定分配最小单位：100/3 → 33.4、33.3、33.3；10/6 → 1.7 × 4、1.6 × 2。原币精度、币种和 FX snapshot 跟随后端。
- 日常还款为 FIFO/TARGETED。普通和大型 Final 均支持 `base_unified` / `original_currency` 与当前优化；仅大型 Final 有预存返还路径。
- ordinary activity 的预存限制和本轮未复测证据如上。新 Agent 四语义为 answer/clarify/read/propose；执行 Harness 负责 UUID 绑定、白名单 RPC、可信确认、固定命令、跨操作 durable key 与回执恢复。这些未来能力不能冒充当前 RPC 的 preview/ACL，也不是完成本次 P0 盘点的代码先决条件。

## 本轮状态

已形成 CAP01–CAP17 的源码映射与 T0 指定资产盘点；文档主审已通过。主线本次 32 SQL 文件/237 pgTAP、Android 268 项测试及 `assembleDebug` 通过；新子活动 scope 与 Expense move migration 本地全回归通过，linked remote migration/ACL 只读核验也已通过。主线另按授权完成已下载 9B Q4_K_M 的原生 LM Studio host 与 Docker 合成 chat；两侧都收到非空内容，随后卸载并确认 `lms ps=[]`。OpenAI 兼容 `chat/completions` 三次 HTTP 200 响应的 `choices[0].message.content` 均为空，即使 64/128 token 预算也以 length 结束；这条路径另列 P2 待查。P0 **仍进行中、未通过**：T0 的 Qwen3.5-4B adapter merge → HF → GGUF → LM Studio 链尚未执行/验证。远端核验只覆盖此次 migration 与相关 catalog/ACL 定义，不等于 CAP 全面端到端验收或 Agent Harness 已实现。

后续优先级和每个未决点的完成证据见 [差异与验收任务](follow-up-tasks.md)。本审计不表示 P0 已通过。
