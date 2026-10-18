# T1 业务验收准备与当前能力结论

**本轮状态：后端回归 NOT_RUN_RESOURCE；Agent CAP01–CAP17 的真实业务验收不可通过，因为实时 Backend/Gateway 尚未接入。** 本文是依据源码和测试断言做的验收预登记，不是本轮业务 PASS。模型质量评估按主会话安排稍后继续。

本轮正式数据库验收未运行；静态核对当前 main 的迁移、现存 SQL 测试、Agent 能力注册表与实现。没有改 main、P1 实现或旧报告，也没有进行云端操作。此前一次独立本地项目已在迁移/seed 阶段中断，0 个 SQL tests；未触及共享 Supabase 数据或云端数据，具体记录如下。Agent 侧仅增加本报告和 preregistration metadata。

## 冻结的输入和未运行记录

业务源为 D:\project\Android\shared-ledger，main HEAD 为 3f938ee6114b763e6cd3dbd10792a78c691eb526，工作树 clean。Agent 源为 D:\project\Android\shared-ledger-agent，agent HEAD 为 1a80a0f29e1ea432a60b95e7437af23d51182938；P1 源文件仍是未跟踪/未暂存文件，P1 终审只批准受限工程范围。

按当前 main 工作树枚举，迁移为 45 个 SQL 文件，runner 会选择 32 个 active SQL 测试；这些测试里的 plan(n) 声明总和为 237。排除项是 supabase/tests/database/legacy_rpc_fixture_adapters.sql（被 \ir 引入的 fixture helper）和 phase8_transfer_restore.sql（已退役）。supabase/tests/database/TEST_STATUS.md 仍写 30 文件/223 assertions，属于过期状态说明。Agent agent/docs/dev-status.md 记载的一次 32/237 fresh isolated PASS，以及此前其他 PASS，都是历史证据；本轮没有重跑，不据此宣称当前验收通过。

精确的 current-main HEAD、45 个 migrations、32 个 SQL 文件、config、seed、runner、业务规则文档、各自 SHA-256、Agent 代码快照摘要、命令和资源状态，已记录在 [preregistration JSON](evidence/business-prereg-20261010.json)。复跑前必须先匹配 HEAD、clean status 和每个输入 hash；任一不符就重新预登记。Preregistration 显示 Supabase CLI 2.116.0、Docker 29.8.2、PowerShell 7.6.6。

主会话上次轻量资源预检报告可用 RAM 1.82 GiB、GPU VRAM 189 MiB，因此暂停重型数据库回归。本轮当前结果为 NOT_RUN_RESOURCE。此前一次隔离尝试的准确状态也保留：项目 sl-dbtest-869fb4ec5d 在 D:\computer\Hermes\temp\shared-ledger-dbtests-869fb4ec5d 创建后，于 migrations/seed 阶段中止，SQL 测试数为 0；随后仅对这个独立 workdir 执行 supabase stop --workdir <该 workdir> --no-backup，检查未发现匹配的 container/volume。隔离源文件夹因安全限制仍留在磁盘，不以其他 shell 重试删除，也不把该尝试当 PASS 或 SQL 失败。

资源许可后，预登记命令会从当前 main 调用 supabase/tests/database/Invoke-IsolatedDatabaseTests.ps1 -KeepStack，并把进程 TEMP/TMP 指向 D:\AI\runs\shared-ledger\t1\business-20261010\temp。Runner 生成随机 sl-dbtest-<id> project id 与 shared-ledger-dbtests-<id> workdir，使用独立端口块、local reset 和本地 pgTAP；Windows bind-mount 异常时 runner 会在同一隔离网络使用 pg_prove fallback。命令先校验 prereg hashes，并保存运行前 Docker container/volume 清单。实际输出写入 D:\AI\runs\shared-ledger\t1\business-20261010。-KeepStack 输出的准确 workdir/project id 必须入最终证据；清理时只对该 workdir 调用 supabase stop --workdir <准确workdir> --no-backup，禁止 --all，之后对照运行前的 Docker 快照。完整可复跑命令已冻结在 JSON，不在低资源窗口启动。

Supabase 官方资料已按 Supabase skill 核验：CLI local workflows 说明 db reset 会销毁并重建目标本地数据库，命令须显式选择 local/linked；数据库测试使用 pgTAP，supabase test db --local 是本轮 runner 的实际模式。[CLI workflows](https://supabase.com/docs/guides/local-development/cli-workflows)、[Database testing](https://supabase.com/docs/guides/database/testing)、[test db CLI reference](https://supabase.com/docs/reference/cli/supabase-test-db)。

## 必须保留的业务角色与财务边界

- 普通 Activity 对 FUND、新增预存使用、RETURN 均整笔拒绝；拒绝必须无 Transfer、component、account/usage 或 financial_version 变化，不能降级成 ordinary settlement。
- Large Activity 的 prepayment account 是 Activity + owner + custodian + currency 范围，可跨有效 child ledger 共用。owner 和 custodian 不要求在同一个 child scope，也不要求 Participant claim；有效 Activity Member 可记录。Child Expense 的 payer 集合和 split 集合分别受该 child 显式 Participant ID scope 限制；记账 actor 必须是 Activity Member，不要求 actor 自己属于 child Participant scope。
- FUND 先抵同方向已有债，余额只接收剩余部分；反向债与预存余额不抵消。关联退款只恢复原 Expense 实际消耗的 Usage，不修改已发生的 Transfer。
- 普通 Activity 的 Final 不含 prepayment return；Large Activity Final 才可按真实可返余额生成 return path。
- AA 尾差应由后端按 participant_order/id 稳定分配，原币最多 4 位、base 最多 1 位；模型只表达用户意图，不承担钱款计算。
- 已关联真实 Transfer 或 linked-refund source history 的 Expense 不可财务修改、删除/移动或恢复；展示字段按独立 presentation RPC 规则处理。Expense restore RPC 对 API roles 不可调用；Transfer 保持 immutable，只能按现行权限 void。

## Agent 当前 CAP01–CAP17 覆盖

“Backend”列是业务 main 的后端 RPC/SQL 事实与可定位测试，不等于 Agent 已接入；“Agent 当前状态”来自 P1 registry 和代码。**当前可真实验收的 Agent CAP 数为 0/17。** 在 mock mode 下的流程、Auth owner isolation、SQLite 幂等/恢复与 Docker 备份测试，只证明 P1 已批准的骨架范围。

| CAP | 业务后端现状及相关 DB 证据 | Agent 当前真实实现 | 可否作为 Agent 业务验收 |
|---|---|---|---|
| CAP01 活动/账目/债务读取 | 业务表/RLS 与确定性查询存在；见 scope、financial-finalization、RLS/outsider 断言。 | Registry 为 mock_read_only；MockBackendAdapter 读取固定 fixture。默认 UnimplementedBackendAdapter.read 明确抛出“live business reads are not installed”。 | **不可**。没有 live Supabase read adapter、真实 Activity scope 授权或 RLS-backed Agent read。 |
| CAP02 创建/加入活动 | 业务端有创建/加入 RPC 与 Activity lifecycle 约束。 | unavailable，没有 Agent create/join operation。 | **不可**。 |
| CAP03 Activity 设置/币种 | update_activity_settings 后端规则存在；phase7_finalization.sql 覆盖活跃/归档边界。 | unavailable，没有 Agent write proposal。 | **不可**。 |
| CAP04 Participant 名单/认领 | phase7_finalization.sql 覆盖创建、删除约束、认领与锁定/成员拒绝。 | unavailable，无名单/claim adapter。 | **不可**。 |
| CAP05 成员管理/Creator 移交 | phase7_finalization.sql 覆盖 Creator 移交和移除成员不删 Participant 历史。 | unavailable，无成员管理提案。 | **不可**。 |
| CAP06 子活动与 ledger scope | sub_activity_participant_scopes.sql 有显式 scope、payer/split、跨账本移动/退款锁等后端断言。 | unavailable，无 ledger-unit 管理提案或执行器。 | **不可**。 |
| CAP07 新增/修改 Expense | aa_original_currency_debt_contract.sql、scope、refund、FX 等 SQL 覆盖具体后端不变量。 | mock_proposal_only；registry 仅 expense.create。Proposal 是 mode=simulation，没有 canonical command、backend preconditions、digest、nonce 或 request receipt。 | **不可**。无 live preview 和写 RPC。 |
| CAP08 已有 Expense 财务/展示修改 | 后端 financial lock、linked-refund source history、presentation CAS 及无 callable restore 边界均有测试。 | mock_proposal_only；模拟 expense.update/expense.presentation.update，无 live lock/version/read-after-preview。 | **不可**。财务 Expense update RPC 无客户端 expected-version/CAS，需单独解决 Agent 并发保护。 |
| CAP09 Expense 软删除/恢复边界 | 删除受权限和财务锁约束；恢复对 client/server roles 撤权；见 linked_refund_contract.sql、phase3_deleted_expense_read_restore.sql。 | unavailable；没有 Agent delete；也不得添加 restore 工具来模拟账本恢复。 | **不可**。 |
| CAP10 外币与 FX 事实 | exchange_rate_expense_snapshots.sql、AA 与多币种分摊测试覆盖快照、精度和沿用历史 FX。 | unavailable，无 live FX 查询/Expense 写入。 | **不可**。 |
| CAP11 linked refund | phase5_prepayment.sql 和 linked_refund_contract.sql 覆盖 usage 恢复、累计退款限制、永久来源锁。 | unavailable，负金额与 refund source 不在 Agent operation allowlist。 | **不可**。 |
| CAP12 普通结算 Transfer | backend v2 preview/create 有 financial_version 和 request_id；targeted、并发和 replay SQL 有相关断言。 | unavailable；底层 RPC 从未注册为模型 operation。 | **不可**。 |
| CAP13 大型活动 prepayment | phase5_prepayment*.sql、normal_prepayment_restrictions.sql、scope 与 concurrency tests 覆盖 account、Usage、return、普通活动拒绝和跨 child 事实。 | unavailable；没有 FUND/RETURN 工具。 | **不可**。普通活动的 FUND/use/RETURN 必须失败关闭，不能转成别的操作。 |
| CAP14 Transfer void/replacement | backend Transfer immutable、void 可重建投影；恢复入口撤权，见 transfer restore contract 与 settlement/prepayment tests。 | unavailable；没有 Transfer mutation/restore adapter。 | **不可**。 |
| CAP15 Final plan/付款记录 | phase6_final_settlement.sql、phase11/12、并发和 normal prepayment tests 覆盖 Final 计划与普通/大型 return 区别。 | unavailable；无 Final preview/execute。 | **不可**。 |
| CAP16 争议/备注/审计事实 | phase7_finalization.sql 覆盖相关成员 dispute add/remove、审计和财务版本不变；业务主数据含 audit/RLS。 | unavailable；CAP01 读不等于 dispute write 授权。 | **不可**。 |
| CAP17 Activity archive/unarchive/delete | phase6_final_settlement.sql 覆盖 unsettled warning、Creator unarchive 与 archived write rejection；phase7_finalization.sql 覆盖 Activity 删除与保留逻辑历史。 | unavailable，没有 lifecycle operation。 | **不可**。 |

代码交叉核对：默认 components.py 组装 DisabledModelProvider、UnimplementedBackendAdapter、UnimplementedRuntime、UnimplementedGateway；默认 Scope authorizer fail-closed。只有显式 provider_mode=mock 才注入 deterministic MockModelProvider、MockBackendAdapter 和 MockRuntime。Gateway 仅 health/not-implemented；模拟 proposal 明确没有 executable command 或 confirmation binding。API confirm 对模拟提案记录 confirmation unavailable/拒绝，不发业务写入。P1 的 126 pytest、Auth 29/29 与 Docker lifecycle/backup PASS 仍有效，但不能改写为真实 CAP 或模型质量 PASS。

## B01–B14 金标准与真实 SQL assertion 映射

以下映射是源码级预审，不等于已运行。级别指现有断言对指南具体案例的覆盖：**近似**表示同一关键不变量、但不是指南的精确输入；**部分**表示只覆盖了子情形或缺一项验收维度；没有标“精确全覆盖”的项即不具备完整指南案例 PASS。复杂 SQL 文件常把多个 pg_temp.assert_true 聚合到一项 plan(1)；所以 237 是测试计划数量，不是 237 个彼此独立的 B 项业务金标准。

| Guide case | 对应当前 backend SQL 断言 | 覆盖判断 | 当前 Agent 能否真实跑 |
|---|---|---|---|
| B01 AA 尾差、守恒、负数方向 | aa_original_currency_debt_contract.sql:289–301 精确验证 100/3 原币尾差和 base 33.4/33.3/33.3；同文件 :137–193, :386–430 覆盖负 AA/退款方向；mass500_micro_aa_debt_allocation.sql 覆盖微小 base debt 非负与守恒。 | **部分**：指南另要求 10.0/6 人为 1.7/1.7/1.7/1.7/1.6/1.6；未找到该精确六人 vector 的断言。负方向和确定性顺序有相邻证据。 | 否；只有 simulated proposal/read。 |
| B02 三人 split 后只剩 C→A 120，重复重算稳定 | phase3_debt_projection.sql 检查 projection/schema/conservation；phase9_fair_aa_final_settlement.sql:154–178 有不同四账单的 bilateral debts 与 Final plan。 | **部分**：未定位指南中的 300、200/100、80/100/120 精确数据向量及其重复 rebuild 断言；237 不足以推导该 case 覆盖。 | 否。 |
| B03 双向 A/B 债务净额，不跨无关第三人 | phase6_final_settlement.sql:108–120, :228–244 覆盖跨 unit path、弱连接/断开参与人的 plan；critical_financial_ordering.sql:246–274 覆盖 reverse-debt netting 与 prepayment Usage 顺序。 | **部分**：邻近覆盖 settlement optimizer 与反向债净额，但未定位 B→A 100、A→B 40 得 B→A 60 的精确 fixture/断言。 | 否。 |
| B04 大型活动既有预存 500，child 消费使用 300、余 200、无普通同向债 | phase5_prepayment.sql:69–86 覆盖账户使用/余额与超过余额后的剩余普通债；sub_activity_participant_scopes.sql:224–261 覆盖 child Expense 与 Activity 级既有账户的结合。 | **近似**：核心 Usage/account 机制与跨 child 路径有测试，未跑指南 500/300 原向量；owner/custodian 跨 child 资格还应按明确角色矩阵验收。 | 否；MockScopeAuthorizer 只接受单一固定 demo Activity。 |
| B05 大型活动欠债 300，再 FUND 1000，preview 和结果都给 300/700 | phase5_prepayment.sql:74–77 覆盖先清偿同向旧债、余款进入 balance 的 Transfer component；normal_prepayment_restrictions.sql:97–114 覆盖 large preview/create 及新账户状态。 | **部分**：preview 与“旧债+剩余预存”未在一个 300/1000 组合中同时断言。 | 否。 |
| B06 预存 1000 与反向债 200 同时保留 | critical_financial_ordering.sql:246–274 验证反向债 netting 在使用预存之前发生，账户余额保留；phase6_final_settlement.sql:269–277 验证 Final return component 方向与 ordinary debt 处理。 | **近似**：关键反向不抵扣逻辑有相邻测试，但未找到指南的精确 1000/200 完整账户与债务双断言。 | 否。 |
| B07 linked refund 把实际 Usage 300→200、余额 700→800，Transfer 不变 | phase5_prepayment.sql:91–99 验证退款只恢复原 Usage（测试值 50→30，余额 50→70）；critical_financial_ordering.sql:157–230 覆盖真实结算与后来退款的排序；linked_refund_contract.sql 覆盖来源锁。 | **近似**：Usage 恢复与 Transfer 来源历史有分离证据，但未找到同一 case 对原 Transfer 字段完全不变的 300/100 场景断言。 | 否。 |
| B08 普通/大型 Final、base_unified/original_currency；只有大型 return | normal_prepayment_restrictions.sql:93–104 验证普通 Final 不含 return，large prepayment preview/create 可用；phase6_final_settlement.sql:269–283 验证 large return 路径及完成状态；phase11_multi_currency_settlement.sql、phase12_multi_currency_allocation_invariants.sql、phase9_fair_aa_final_settlement.sql 覆盖对应币种/计划规则。 | **覆盖主要规则，仍非单一全矩阵**：指南所列 A→B、B→C 和两个 Final mode 的全排列不是一项端到端 fixture。 | 否。 |
| B09 Expense 解锁/锁定编辑删除、restore 禁止、Transfer 只 void | linked_refund_contract.sql:87–207 覆盖 linked refund cap、永久 source lock 和 presentation update；phase7_finalization.sql:66–78, :131–137 覆盖来源锁与 restore ACL；phase3_deleted_expense_read_restore.sql:199–215、transfer_restore_contract.sql 覆盖 restore 被撤权。 | **较强但分散**：关键 lock/refund/restore 边界有 SQL；不可调用 Expense restore、不可恢复 Transfer 是当前正式边界。完整指南 B09 全角色与所有生命周期组合仍需标注缺例。 | 否；Agent CAP07/08 是 simulation，CAP09 unavailable。 |
| B10 Transfer dispute 显示但不改账 | phase7_finalization.sql:154–162 覆盖相关成员创建、移除并断言 financial_version 不变，另查 audit log。 | **部分**：有财务版本不变，未见相同断言直接比较 dispute 前后余额 projection。 | 否。 |
| B11 FX snapshot、多付款/分摊/还款/Final、精度、历史不重估 | exchange_rate_expense_snapshots.sql:79, :117, :152–165 验证 cache snapshot 与旧记录字段；aa_original_currency_debt_contract.sql:280–301, :354–445 覆盖四位原币、一位 base、外币/负数 AA；phase11/12 与 targeted multicurrency tests 覆盖还款/分配。 | **覆盖主要不变量**：需确认 selected full run 包含相关文件；指南全流组合不是一个单独 B11 fixture。 | 否；CAP10/12/15 未注册。 |
| B12 超额 settlement、超额 RETURN、stale Final 原子拒绝 | phase4_settlement_transfer.sql:228 起验证在锁后债额已变化时超额 settlement 不留 fact/projection/version；phase4_settlement_transfer_concurrency.sql 覆盖并发竞争；phase5_prepayment.sql:82–86 覆盖超额返还拒绝；phase6_final_settlement.sql:127–137 验证 stale Final plan 无财务副作用；critical_financial_concurrency.sql 覆盖跨操作串行化。 | **组合覆盖**：分别有保护性断言，但不是指南一个统一向量；Fresh full run 必须整体执行。 | 否。 |
| B13 已完成后新账、unsettled archive warning、归档只读、Creator unarchive | phase6_final_settlement.sql:279–319 覆盖完成 archive、unsettled warning、unarchive 与归档后写拒绝；phase7_finalization.sql 覆盖归档生命周期/权限。 | **部分**：归档告警、只读与取消归档有覆盖；未定位“completed 后新增 ledger fact 再断言重新变 active”的同一精确路径。 | 否。 |
| B14 普通 activity 新增/使用/返还预存明确拒绝；large 正常预览/执行 | normal_prepayment_restrictions.sql:60–91 覆盖 ordinary preview/FUND/RETURN 以及无 transfer/component/account/usage/version 变化；:93–114 覆盖 ordinary final no-return 与 large preview/create；phase5_prepayment.sql 覆盖 large usage/return。 | **后端规则覆盖较强，分散在多个 fixture**；Agent operation 尚不存在。普通活动拒绝不能被模型映射成普通 Transfer 或其他写入。 | 否。 |

### 当前金标准尚未覆盖的精确向量

至少需把 B01 的六人 10.0 例、B02 的 300 三人 split、B03 的 100/40 双向债务、B04 的 500/300、B05 的 300/1000 preview+结果、B06 的 1000/200、B07 的 300 usage/100 refund 与真实 Transfer 不变，作为未来专项后端回放中的明确断言。B08、B11、B12 应说明对应 mode/并发矩阵，而不是只引用单项算法测试。B13 需验证“完成后新增事实导致状态回到 active”的具体转换。当前不新增这些测试、不改业务 SQL；这是后续可执行 acceptance backlog，不是无限扩展本轮任务的理由。

## P2/P3 最小可验收增量与角色边界

**P2（先只读 CAP01）**至少需要一个真实 SupabaseBackendAdapter，沿认证用户 session/JWT 执行 allowlisted activity/expense/debt reads；服务端用当前身份重核 membership、activity scope，并由后端 RLS 再限行。components.py 默认依然 fail-closed，只有显式 P2 mode 才能装配真实 adapter。Agent 应返回可溯源的来源时间/financial version/实体引用；不使用模型提供的 ID 代替授权，也不把 service_role 或 fixture 当用户权限。所需代码影响集中在 backend/ports/components/settings/API read path 和相应 Agent tests；按两个用户跨 owner、非成员、跨 Activity ID、无 token/失效 token 与 read-only/no-write 做本地真实 Auth + RLS replay。此项不要求新增业务写 RPC。

**P3（仅在 P2 通过后启 CAP07/08）**远超“把 Gateway 指到当前 RPC”：需实现 live backend preview、服务端绑定的 canonical command/preconditions、proposal revision+digest+nonce、确认后二次授权/业务重读、固定 operation allowlist、数据库版本/CAS、可重复安全的 request key、durable receipt、超时未知结果的 status/recovery。当前 Expense create/update RPC 未提供通用 request_id；财务 update 无调用方 expected_version/CAS，行锁并不等于确认时的 stale-preview 拒绝。Presentation update 有可选 Expense version 检查，但无 request receipt。故需为 Agent 建专用、事务化的 write contract/RPC 或经过业务审查的等效事务实现；不能以 direct table DML/service role 绕过业务规则，也不能冒称 current RPC 已满足固定执行。最少代码边界是 backend/gateway/ports/components/runtime/API/store，加新的 Agent 业务契约与故障恢复测试；若数据库 contract 需扩展，应在后续明确授权下增加 migration/pgTAP，而非本轮碰 main。

P2 完成只让 CAP01 有资格做真实读验收。P3 第一小片完成后，才可对 CAP07 create 与 CAP08 presentation/financial change 分别做有确认的两用户真实后端测试；每个操作仍须独立证明业务 lock、scope、CAS、重放与未知结果恢复。它不会让 CAP02–06、CAP09–17 自动通过。P1 的 126 pytest、Auth 29/29 和 Mock proposal 只能作为工程前提，不是这些 P2/P3 证据。

## 执行/验收门槛

1. 资源条件解除后，先验证 preregistration 的 main HEAD、clean status 和全部输入 SHA-256；不匹配即重建 preregistration。
2. 只启动 runner 创建的全新随机 local project，在任务专属 D 盘 TEMP/TMP 和 run root 下按全量 32 文件/237 declared pgTAP assertions 执行。此套 SQL 的结果是“当前 backend 迁移回归”，不等于 Agent CAP 通过。
3. 记录完整 exit code、文件级/总 assertion 输出、随机 project/workdir、Docker before/after container 与 volume 差异、cleanup 结果、时间和新日志 hash。失败或中断按真实 phase 记录，不修改为 PASS。
4. Agent CAP acceptance 单独保持 NOT_IMPLEMENTED，直到 P2/P3 真实适配器及所需合同具备。模型/训练质量使用冻结数据和真实模型链，另开主会话批准的后续评估；不混入本次 DB 结果。

