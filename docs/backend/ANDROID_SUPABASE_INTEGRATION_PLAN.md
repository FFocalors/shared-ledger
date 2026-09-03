# Android × Supabase 联调路线

> 状态：`执行基线`
>
> 目标：将已经冻结的 Supabase 后端契约与 Android 前端原型按真实业务链逐段接通，最终实现 Runtime Demo/Fake 数据归零和双账号端到端验收。

## 1. 联调基线

当前阶段由“前后端各自完成”切换为 **Android × Supabase Integration**。

唯一有效的后端契约由以下内容共同定义，优先级从高到低：

1. `supabase/migrations/` 中当前 16 条 migration；
2. [BACKEND_INTEGRATION_READINESS.md](./BACKEND_INTEGRATION_READINESS.md) 中冻结的公开 RPC、读取、错误、Realtime 与 Storage 契约；
3. 对应数据库测试和 [BUSINESS_LOGIC.md](./BUSINESS_LOGIC.md) 中不与 migration 冲突的业务规则。

[api-contracts.md](./api-contracts.md) 是早期目标设计，已标记为废弃，不得用于生成新的 RPC 名称、表名或 DTO。契约发生变化时必须新增 migration，并同步更新 readiness 文档和本路线。

## 2. 架构与安全边界

Android 数据调用必须保持以下分层：

```text
Compose UI / ViewModel
          ↓
Repository
          ↓
Supabase DataSource
          ↓
Supabase Auth / PostgREST / RPC / Storage / Realtime
```

- Compose 页面不得直接调用 Supabase SDK。
- Android 只能配置 `SUPABASE_URL` 和 publishable key（或兼容 anon key）；`service_role`、secret key、数据库密码和 Storage 管理凭据不得进入 APK、源码或日志。
- 简单读取使用受 RLS 保护的 Data API；多表财务写入只调用冻结的 RPC。
- `Participant` 与 `ActivityMember` 必须保持独立 domain/DTO 模型，不能合并成通用 `Person`。
- 金额在传输和 domain 层使用字符串/`BigDecimal`，不得使用浮点数保存账务事实。
- 客户端只提交金额、付款、分摊、币种和汇率等事实输入，不写 `base_amount`、债务投影或预存使用量。
- Realtime 事件只作为缓存失效和重新读取的提示，Android 不自行重算债务或结算结果。

## 3. 开始联调前的准备

- [ ] 确认 [BACKEND_INTEGRATION_READINESS.md](./BACKEND_INTEGRATION_READINESS.md) 与 16 条 migration 为唯一后端契约。
- [x] 将旧 [api-contracts.md](./api-contracts.md) 标记为废弃。
- [ ] 将本机 `JAVA_HOME` 修正为 JDK 根目录，而不是 `bin` 目录。
- [ ] 安装 Supabase CLI，并通过 `supabase --help`、`supabase --version` 和项目状态检查验证环境。
- [ ] 在空本地数据库重新应用全部 migration，并运行数据库测试与安全检查。
- [ ] 确认 `main` clean 后创建 integration feature 分支。
- [ ] 确认 Android 环境配置不会把本地或生产密钥提交到 Git。

## 4. Integration Phase 1：基础设施与 Auth

### 实施范围

- 引入并固定 Supabase Kotlin 客户端、Auth、PostgREST/RPC、Serialization 和网络引擎依赖版本。
- 建立环境配置、`SupabaseClient`、DataSource、Repository、DTO/mapper、统一错误模型和依赖装配。
- 使用 `AuthRepository` 替换 Runtime `DemoAuth`，但不影响 `@Preview` 的 Sample Data。
- 接入注册、登录、Session 恢复、退出、当前用户 Profile 和 Auth Gate。
- 启动流程调整为：恢复 Session；有效进入 Home，无效进入 Auth。
- 本阶段不接入资金业务。

### 验收门槛

```text
真机注册账号
→ 登录
→ 杀进程
→ 重启后仍保持登录
→ 退出后返回登录页
```

- [ ] APK 和日志中不存在 `service_role`、secret key 或数据库密码。
- [ ] Session 过期能够刷新或明确回到登录页。
- [ ] 注册、登录、恢复和退出均有 loading、error 与重复点击保护。

## 5. Integration Phase 2：活动与身份主链

### 实施顺序

```text
Home
→ Activity Detail
→ Participant / ActivityMember
→ LedgerUnit
```

接入真实活动列表、普通/大型活动创建、加入码加入、Participant 创建、Claim/Unclaim、Member、Creator、子活动、活动设置和 Financial Status。

对应页面包括：首页、加入活动、活动管理、普通活动、大型活动、创建子活动和账本单元。

### 模型约束

- `Participant` 表示活动中的账务身份。
- `ActivityMember` 表示 Auth 用户在活动中的成员和权限身份。
- Claim 关系连接二者；付款、分摊、转账方向使用 Participant ID，权限使用 Member/User 身份判断。

### 验收门槛

```text
A 创建大型活动
→ A 添加 Participant
→ B 使用加入码加入
→ B Claim Participant
→ A 创建子活动
→ A/B 刷新后看到一致数据
```

- [ ] 非成员无法读取活动。
- [ ] 普通成员无法执行 Creator 专属操作。
- [ ] 页面路由和 Repository 使用真实 UUID，不使用显示名称或 Demo ID。

## 6. Integration Phase 3：Expense 完整链路

### 实施顺序

```text
Expense List
→ Expense Detail
→ Create
→ Update
→ Delete
→ Restore
→ Refund
```

接入 Payment、Split、AA、Manual Split、多付款人、多币种、FX Rate 和统一错误映射。Attachment UI 可以保留占位，Storage 在 Phase 5 接入。

客户端只提交原始金额、付款事实、分摊事实、原币种、汇率和必要元数据；`base_amount`、`expense_debts`、`bilateral_debts` 和 `prepayment_usages` 均以服务端计算为准。

### 错误映射

- `28000`：未认证或会话无效；刷新 Session 或重新登录。
- `42501`：无权限或不属于活动；不盲目重试。
- `P0002`：资源不存在或不可见。
- `22023` / `23514`：输入或业务约束错误，映射到字段/业务提示。
- `23505` / `23503`：唯一或关联冲突。
- `55000`：活动生命周期或设置锁定。
- `40001`：并发序列化冲突，按幂等策略有限重试。

不得直接向用户展示 PostgreSQL 原始错误文本。

### 验收门槛

```text
双账号新增消费
→ 对方刷新后看到
→ 修改
→ Debt 投影正确变化
→ 删除后投影恢复
→ Restore
→ Refund
```

- [ ] Android 金额与数据库投影一致。
- [ ] 快速重复点击不会产生重复消费。
- [ ] 并发修改能显示明确冲突并重新读取。

## 7. Integration Phase 4：资金链与 Final Settlement

### 统一资金记录范围

- `settlement`
- `prepayment`
- `prepayment_return`
- `final_settlement`

依次接入 Bilateral Debt、普通/部分结算、Prepayment、Prepayment Return、Void、Dispute、统一资金记录、资金详情、Activity Settlement Preview、Final Settlement Preview 和 Final Settlement Execute。

### 并发约束

Final Settlement 必须遵循：

```text
读取当前方案和 financial_version
→ 用户确认
→ 服务端重新校验
→ 成功后重新读取方案
```

若账务已变化，客户端停止旧方案执行并提示：

> 当前结算方案已发生变化，请重新查看最新方案。

### 验收门槛

- [ ] A 欠 B，部分还款后剩余债务正确。
- [ ] 预存先抵扣旧债，余额形成预存，新消费自动使用，剩余金额可返还。
- [ ] 大型活动包含多个子活动时，推荐方案与服务端投影一致。
- [ ] 执行任意结算项后重新读取并更新推荐方案。
- [ ] 作废和争议不覆盖原始资金事实，权限与审计记录正确。

## 8. Integration Phase 5：Storage、Realtime 与 E2E

### Storage

- 使用私有 bucket `activity-attachments`。
- 支持 JPEG、PNG、WebP，单文件最大 10 MiB。
- 按冻结协议执行：创建 pending metadata → 上传对象 → complete attachment。
- 支持 Expense 和 LedgerUnit 附件的查看、删除及 archived 只读。
- 不保存永久公开 URL；读取必须遵守 Activity 成员权限。

### Realtime

使用 Activity-scoped Realtime Coordinator，不为 16 张表分别建立独立 UI 监听器。

事件到达后标记对应 Repository 数据失效，并带短 debounce 重新读取服务端状态。客户端不得依据事件自行累加 Debt、Prepayment 或 Settlement。

### E2E Acceptance

固定两个真实测试账号：A 为 Creator，B 为 Member。从空账号完整验证：

```text
注册 → 登录 → 创建活动 → 加入活动 → Claim → 创建子活动
→ 新增/修改/删除/恢复 Expense
→ Settlement → Prepayment → Refund → Final Settlement
→ Attachment → Dispute → Archive → 双端 Realtime 同步
```

同时覆盖断网、超时、Session 过期、重复点击、并发修改、archived 后写入、权限不足、stale version 和杀进程恢复。

完成后状态从 `Integration GO` 升级为 `E2E Acceptance READY`。

## 9. Demo/Fake 退出策略

Runtime Demo/Fake 必须按阶段退出，不一次性删除：

| 阶段 | 退出范围 |
| --- | --- |
| Phase 1 | `DemoAuth` Runtime 依赖 |
| Phase 2 | Home、Activity、Participant、Member、LedgerUnit 的 `DemoData` |
| Phase 3 | Expense Runtime Demo 数据与本地假写入 |
| Phase 4 | `FakeFinancialRecordRepository` 和资金/结算本地假写入 |
| Phase 5 | 全局搜索并清除剩余 Runtime `Demo` / `Fake` 引用 |

`@Preview`、截图测试和纯 UI 预览使用的 Sample Data 可以保留，但必须位于清晰的 preview/sample 边界内，不能成为正式运行时数据源。

## 10. 完成定义

```text
Backend Contract Freeze ✅
Frontend Prototype Freeze ✅
        ↓
Phase 1  Supabase Foundation + Auth
        ↓
Phase 2  Activity + Participant + Member
        ↓
Phase 3  Expense End-to-End
        ↓
Phase 4  Transfer + Prepayment + Final Settlement
        ↓
Phase 5  Storage + Realtime + E2E
        ↓
Runtime Demo/Fake = 0
双账号真实环境验收
        ↓
MVP Feature Complete
```

五阶段完成后，后续工作转向稳定性、UX、异常处理、可观测性和发布准备，不再扩张 V0.1 核心业务模型。
