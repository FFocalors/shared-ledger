# SharedLedger 后端文档

> 文档状态：`后端契约冻结 / Android × Supabase 联调开始`
>
> 本目录用于约束 SharedLedger V0.1 的业务规则、Supabase 数据模型、权限边界和 Android 接入契约。业务规则以 `BUSINESS_LOGIC.md` 为基线；数据库实际状态以已应用 migration 为准。

## 当前状态

- Android 端已完成 Kotlin + Jetpack Compose 前端原型、正式路由和阶段性 UI 优化。
- Supabase Phase 1–7 共 16 条 migration 已冻结身份、活动、消费、债务、资金流、预存、最终结算、争议、附件、Realtime 和 Storage 契约。
- Android 当前仍未接入 Supabase SDK、真实 Auth 和生产 Repository；Runtime 仍包含 `DemoData`、`DemoAuth`、`FakeFinancialRecordRepository` 和本地 UI state。
- 项目当前状态为 `Integration GO`，尚未达到 `E2E Acceptance READY`。
- 后续实施统一按 [ANDROID_SUPABASE_INTEGRATION_PLAN.md](./ANDROID_SUPABASE_INTEGRATION_PLAN.md) 的五个阶段进行。

## V0.1 后端目标

为熟人群体的聚餐、旅行等活动建立一个可审计、可结算的最小闭环：

1. 用户能够登录并维护自己的展示资料。
2. 用户能够创建、加入、查看和归档活动。
3. 普通活动使用一个根账本；大型活动可以包含多个子活动/账本单元。
4. 成员能够记录消费、付款人和分摊人，并支持主币种及多币种设计。
5. 成员能够记录转账、收款、预存和退款等资金流。
6. 系统能够生成结算预览、锁定最终结算批次，并逐项记录支付状态。
7. 每项业务写入具备权限校验、事务一致性、幂等重试和基本并发保护。

## 文档导航

| 文档 | 用途 | 状态 |
| --- | --- | --- |
| [BUSINESS_LOGIC.md](./BUSINESS_LOGIC.md) | 已确认的业务规则、金额口径、权限边界和 MVP 完成标准 | `业务基线` |
| [BACKEND_INTEGRATION_READINESS.md](./BACKEND_INTEGRATION_READINESS.md) | 已冻结的真实 RPC、读取、错误、Realtime 与 Storage 契约 | `执行基线` |
| [ANDROID_SUPABASE_INTEGRATION_PLAN.md](./ANDROID_SUPABASE_INTEGRATION_PLAN.md) | Android × Supabase 五阶段联调路线、验收和 Demo 退出策略 | `执行基线` |
| [database-schema.md](./database-schema.md) | 早期实体设计与 schema 说明；实际状态以 migration 为准 | `参考` |
| [api-contracts.md](./api-contracts.md) | 早期 API 目标设计，部分名称与已冻结数据库不一致 | `废弃` |

阅读顺序建议：先阅读业务逻辑，再阅读 Backend Integration Readiness，最后按 Android × Supabase 联调路线实施。不得从废弃的 API 契约复制 RPC 或表名。

## 架构边界

```text
Android UI/ViewModel/Repository
            │
            ├── Supabase Auth：注册、登录、会话刷新、退出
            ├── Data API：带 RLS 的简单读取和单资源查询
            └── RPC：带权限检查的原子多表写入和结算计算
                         │
                         └── PostgreSQL + RLS + 安全视图

Edge Functions：仅用于第三方 webhook、邀请邮件、复杂文件处理等外部/长任务
Realtime：后续按资源范围增加，不作为 V0.1 首次接入前提
Storage：附件能力单独设计，使用私有 bucket 和短期 signed URL
```

边界规则：

- Android 不直接连接 PostgreSQL，不持有数据库密码或服务端密钥。
- 简单查询可使用已暴露且受 RLS 保护的表/安全视图；跨表写入不由客户端拼接多次请求完成。
- 消费写入必须一次性处理消费、付款人、分摊和必要的汇率/附件关联。
- 结算必须基于服务端快照生成，不能以客户端本地金额累加作为最终结果。
- Edge Function 不能被用来绕过 RLS；只有确实需要服务端密钥、第三方回调或长任务时才引入。
- Realtime/Storage 是后续能力，不应阻塞 V0.1 的 Auth、查询、消费、资金流和结算闭环。

## 安全不变量

以下条件在任何 schema、RPC、客户端接线和测试中都必须保持：

1. 所有暴露 schema 的业务表启用 RLS；RLS 是行级授权，不等同于 Data API 的表暴露/GRANT 配置，两者都要检查。
2. 业务授权依据 `auth.uid()` 与数据库中的活动成员、角色和资源关系；不使用可由用户编辑的 `user_metadata` 判定权限。
3. `TO authenticated` 只代表已认证，不代表有权访问指定活动；每条 policy 还必须检查资源归属或成员关系。
4. UPDATE policy 必须同时有 SELECT policy，以及完整的 `USING` 和 `WITH CHECK`，防止把资源转移给其他用户。
5. 视图优先使用 `security_invoker=true`；确需 `SECURITY DEFINER` 时只能放非暴露 schema，显式验证 `auth.uid()`，固定 `search_path`，并撤销 `PUBLIC EXECUTE`。
6. Android 只使用 publishable key/兼容 anon key + 用户 JWT；`service_role`、secret key、数据库连接密码和 Storage 管理 token 永不进入 APK、源码、日志或客户端配置。
7. 金额使用精确 decimal/numeric，不使用浮点作为账本事实；跨币种必须保存原币金额、币种和服务端汇率快照。
8. 删除账本事实优先使用作废/软删除；已进入结算的消费、资金流和结算批次不得被静默物理删除。
9. 消费、转账、邀请、结算等可重试写入必须带 `clientOperationId`，服务端通过唯一约束或幂等记录避免重复副作用。
10. 敏感错误对无权用户统一表现为不可见/`not_found`，避免通过错误信息枚举活动或成员。

## 建议实施顺序

1. **Phase 1**：Supabase 基础设施、数据分层和 Auth。
2. **Phase 2**：Activity、Participant、ActivityMember 和 LedgerUnit。
3. **Phase 3**：Expense 创建、修改、删除、恢复、Refund 和债务投影核对。
4. **Phase 4**：Settlement、Prepayment、资金记录、争议与 Final Settlement。
5. **Phase 5**：Storage、Activity-scoped Realtime 和双账号 E2E 收口。

每个阶段完成后再退出对应 Runtime Demo/Fake 数据；`@Preview` Sample Data 可以继续保留。

## 阶段验收门槛

### 设计阶段

- [ ] 产品待确认决策已记录并有最终结论。
- [ ] Schema 与 API 文档字段、枚举、ID 和权限含义一致。
- [ ] 明确每个操作是 Data API 查询还是 RPC 原子写入。
- [ ] 未将未实现的表、视图或函数描述成“已上线”。

### 数据库阶段

- [ ] migration 可在空项目重复执行，并可审查、回滚或明确不可逆步骤。
- [ ] 所有暴露表启用 RLS；Data API 暴露/grants 与 RLS 均通过检查。
- [ ] 非成员、错误角色、跨活动 ID、伪造 owner/memberId 的测试均被拒绝。
- [ ] 金额合计、币种、外键、状态机、版本和幂等约束在数据库侧生效。
- [ ] advisors/安全检查无未处理的高风险项。

### Android 接入阶段

- [ ] Auth 会话、publishable key 和环境配置不泄露敏感密钥。
- [ ] 所有业务 ID 使用 UUID/memberId，不用显示姓名或 Demo ID。
- [ ] RPC 失败、409 并发冲突、重复 operation、401/403/404 均映射到统一客户端错误。
- [ ] 成功提交后再更新页面；旋转、进程恢复和网络重试不产生重复消费/转账。
- [ ] 真机或模拟器完成一条端到端业务链路，且工作区和 release 检查无本地密钥。

## 文档状态标签与变更规则

状态标签只允许使用以下含义：

- `设计中`：契约已提出，尚未完成实现或验证。
- `已实现未部署`：代码/migration 已准备，但尚未应用到目标 Supabase 项目。
- `已部署待验证`：已应用到目标环境，但仍缺少完整验收证据。
- `已验证`：有对应 migration、RLS/API 测试和 Android/E2E 证据。
- `废弃`：不再作为新代码依据，必须保留替代方案和迁移说明。

每次变更必须：

1. 同步更新本入口、`BACKEND_INTEGRATION_READINESS.md` 和 `ANDROID_SUPABASE_INTEGRATION_PLAN.md` 中受影响的字段、枚举、权限、阶段和验收项；历史文档只补充必要的废弃说明。
2. 说明变更原因、兼容性、migration 影响、客户端最小改动和测试范围。
3. 不把本地实验、未执行 SQL 或临时 mock 误标记为已实现/已部署。
4. 先更新契约和测试，再实现 migration、RPC 或 Kotlin 接线；需要破坏兼容性时增加版本或迁移说明。
5. 禁止在文档、示例 JSON、日志或截图中写入真实密码、Token、API Secret 或 service role key。

## 当前正式页面范围

以下 15 个页面/route 是当前 Android 联调范围；测试展示页不属于正式业务页面：

1. 登录/注册：`auth`
2. 首页：`home`
3. 加入活动：`join-activity`
4. 创建活动：`create-activity`
5. 普通活动详情：`normal-activity/{activityId}`
6. 大型活动详情：`large-activity/{activityId}`
7. 创建子活动：`create-sub-activity/{activityId}`
8. 账本单元：`ledger-unit/{activityId}/{ledgerUnitId}`
9. 新增消费：`new-expense/{activityId}?ledgerUnitId={ledgerUnitId}`
10. 消费详情：`expense-detail/{expenseId}`
11. 转账/收款：`transfer/{activityId}?mode={mode}&ledgerUnitId={ledgerUnitId}`
12. 统一资金记录：`fund-records/{activityId}?ledgerUnitId={ledgerUnitId}`
13. 资金记录详情：`transfer-detail/{activityId}/{transferId}?ledgerUnitId={ledgerUnitId}`
14. 活动管理：`activity-management/{activityId}`
15. 最终结算：`final-settlement/{activityId}`

页面当前仍以原型数据运行为主，真实数据替换顺序和验收门槛见 [ANDROID_SUPABASE_INTEGRATION_PLAN.md](./ANDROID_SUPABASE_INTEGRATION_PLAN.md)。

## 当前实施边界

数据库 Phase 1–7 契约已经冻结，包含身份、活动生命周期、消费、债务投影、转账、预存、最终结算、争议、附件、Realtime publication 和私有 Storage 协议。当前实施重点已切换为 Android SDK、Repository、UI 接线和真实环境 E2E；未来数据库变化必须通过新 migration 和显式契约修订完成。
