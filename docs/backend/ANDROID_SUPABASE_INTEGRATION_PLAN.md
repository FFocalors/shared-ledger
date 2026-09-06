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

- [x] 确认 [BACKEND_INTEGRATION_READINESS.md](./BACKEND_INTEGRATION_READINESS.md) 与 16 条 migration 为唯一后端契约。
- [x] 将旧 [api-contracts.md](./api-contracts.md) 标记为废弃。
- [x] 将本机 `JAVA_HOME` 修正为 JDK 根目录，而不是 `bin` 目录（当前用户环境为 `D:\project\JDK`）。
- [x] 安装 Supabase CLI，并通过 `supabase --help`、`supabase --version` 和项目状态检查验证环境（CLI 2.116.0；Docker Engine 29.7.2）。
- [x] 在空本地数据库重新应用全部 16 条 migration；本次未修改 migration。`supabase test db --local` 已执行：7 个脚本的 78 项断言通过，另有 5 个历史脚本因缺少 TAP plan 被 pg_prove 判为解析失败，详见 Phase 1 实测记录。
- [x] 确认 `main` clean 后创建 integration feature 分支：`codex/integration-phase-1-auth`。
- [x] 确认 Android 环境配置不会把本地或生产密钥提交到 Git。

## 4. Integration Phase 1：基础设施与 Auth

### 实施范围

- 引入并固定 Supabase Kotlin 客户端、Auth、PostgREST/RPC、Serialization 和网络引擎依赖版本。
- 建立环境配置、`SupabaseClient`、DataSource、Repository、DTO/mapper、统一错误模型和依赖装配。
- 使用 `AuthRepository` 替换 Runtime `DemoAuth`，但不影响 `@Preview` 的 Sample Data。
- 接入注册、登录、Session 恢复、退出、当前用户 Profile 和 Auth Gate。
- 启动流程调整为：恢复 Session；有效进入 Home，无效进入 Auth。
- 本阶段不接入资金业务。

### Phase 1 实际进展（2026-09-05，已完成）

- [x] 已固定并引入 Supabase Kotlin 3.8.0、Ktor 3.5.1、Kotlin serialization
  1.11.0 和 coroutines 1.11.0；仅启用 core/Auth/PostgREST，没有 Storage、
  Realtime 或 Activity 业务接线。
- [x] 已建立 `SupabaseClientProvider`、`AuthRepository`、
  `SupabaseAuthRepository`、Auth 状态/错误映射和 `AuthViewModel` 分层。
- [x] 已接入真实邮箱密码注册/登录、昵称 metadata、profiles 读取、Session
  初始化/恢复、失效回 Auth、退出登录和重复提交保护。
- [x] 已移除 `DemoAuth` Runtime 文件及 Debug 假账号提示；Preview/Sample、
  Home/Activity/Expense DemoData 和 FakeFinancialRecordRepository 保留。
- [x] 已加入 INTERNET 权限和 fail-safe BuildConfig 配置读取；Debug 仅允许
  `10.0.2.2`、`127.0.0.1`、`localhost` 使用本地 HTTP，Release 仍要求 HTTPS。
- [x] Docker Desktop 重装后 Engine 29.7.2 正常；Supabase 本地最小栈已启动。
- [x] 空库顺序应用 16 条 migration 并完成 seed；migration history 全部匹配，
  本次验证未产生 migration 文件变化。
- [x] 本地 API URL 与 publishable key 已写入 Git 忽略的 `local.properties`；
  Android Emulator 使用 `10.0.2.2:54321`，未写入 service role/secret key。
- [x] 本地 Auth API 实测完成：随机测试账号完成昵称注册、登录、当前用户/session、
  `profiles` 读取和退出；publishable/anon 兼容入口均返回成功。
- [x] 真机 UI 验收完成：注册、登录、进入 Home、force-stop 后重启恢复 Session、
  退出回 AuthScreen、Auth Gate 和同账号重新登录均通过。
- [!] Supabase `vector` 是日志采集辅助服务，当前重启属于已知非阻塞技术债；
  Auth、DB、Kong、REST 等本阶段核心服务健康，不影响本阶段 Auth 验收。

详细配置见 [ANDROID_SUPABASE_SETUP.md](./ANDROID_SUPABASE_SETUP.md)。

### 验收门槛

```text
真机注册账号
→ 登录
→ 杀进程
→ 重启后仍保持登录
→ 退出后返回登录页
```

- [x] 已核对 APK/日志和 Git diff，不存在 `service_role`、secret key 或数据库密码；
  `local.properties` 已被 Git 忽略。
- [x] Session 失效能够刷新或明确回到登录页。
- [x] 注册、登录、恢复和退出均有 loading、error 与重复点击保护。

Phase 1 已完成并可进入后续集成排期。Phase 2 的 Activity、Participant、
ActivityMember（用户）和 LedgerUnit Android 真实接线已完成收尾；本次仅修改
Android、真机准备脚本和集成文档，未修改或创建任何后端 migration。Expense、
资金记录、结算、Storage 和 Realtime 仍按后续阶段处理。

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

### Phase 2 后端契约摘要（2026-09-05）

本阶段以 `BACKEND_INTEGRATION_READINESS.md` 和当前 16 条 migration 为准，已逐条核对 migration 中的表、RLS、公开 RPC 和返回列；`api-contracts.md` 继续保持废弃状态。

活动与身份主链使用以下公开表和字段：

- `activities`：`id`、`join_code`、`name`、`type`（`normal`/`large`）、`base_currency`、`multi_currency_enabled`、`created_by`、`archived_at`、`is_deleted`、`participants_locked_at`、`financial_version` 及生命周期时间/操作者字段。
- `activity_members`：`id`、`activity_id`、`user_id`、`joined_at`、`created_at`；权限成员与账务 Participant 分离。
- `ledger_units`：`id`、`activity_id`、`name`、`type`（`default`/`root`/`sub_activity`）、删除标记及时间/操作者字段。
- `participants`：`id`、`activity_id`、`name`、`participant_order`、删除标记及时间/操作者字段。
- `participant_claims`：`id`、`activity_id`、`participant_id`、`user_id`、`claimed_at`；每个用户和 Participant 的唯一 Claim 约束由数据库维护。

Phase 2 写入只调用以下公开 RPC：

```text
create_activity(name, type, base_currency, multi_currency_enabled)
  -> activity_id, join_code, activity_name, activity_type,
     activity_base_currency, activity_multi_currency_enabled
join_activity_by_code(join_code)
  -> activity_id, is_new
create_participant(activity_id, name, participant_order)
  -> participant_id, participant_name, participant_order
claim_participant(activity_id, participant_id)
  -> claim_id, claimed_participant_id, is_new
unclaim_participant(activity_id)
  -> boolean
create_sub_activity(activity_id, name)
  -> parent_activity_id, ledger_unit_id, created_name, created_type
update_activity_settings(activity_id, name, base_currency, multi_currency_enabled)
  -> activity_id, activity_name, activity_base_currency,
     activity_multi_currency_enabled
archive_activity(activity_id), unarchive_activity(activity_id)
  -> activity_id, archived, changed, archived_at, total_debt,
     total_prepayment, completed, has_unsettled, warning
delete_participant(participant_id), delete_activity(activity_id)
remove_activity_member(activity_id, user_id)
transfer_activity_creator(activity_id, new_creator_user_id)
```

活动列表、成员、Participant、LedgerUnit、Claim 和金融状态使用受 RLS 保护的 Data API 读取。客户端必须保存公开 RPC 的 `snake_case` 返回列并映射为 Android domain model；不能依据 private helper 的内部列名或旧契约重命名。`participant_financial_status` 和 `activity_financial_status` 只作为服务端计算结果读取，不能由客户端自行推导权限或金融状态。

### Phase 2 本地真实 API 验收（2026-09-05）

使用本地 Supabase 的两个一次性普通账号，通过 publishable/anon 客户端入口完成以下链路；测试输出未记录 key 或 token：

```text
A 注册                                  PASS
B 注册                                  PASS
A create_activity(type=large)           PASS
A create_participant                    PASS
B join_activity_by_code                 PASS
B claim_participant                     PASS
A create_sub_activity                   PASS
A 通过 Data API 读取                    PASS
B 通过 Data API 读取                    PASS
A/B 数据快照一致                        PASS
```

两端最终读取结果均为 `1 activity / 2 activity_members / 1 participant / 2 ledger_units / 1 participant_claim`，包含大型活动的 root unit 和新建 sub-activity unit。A/B 读取均经过各自认证会话和 RLS；没有使用 service role 模拟客户端授权。16 条 migration 的本地 history 全部匹配，`supabase/migrations/` 零改动。

本次链路未发现 Backend Contract 问题，也未发现种子/测试数据导致的失败。此前一次数量断言失败是测试脚本对 PowerShell 嵌套 JSON 数组的处理问题，使用保留原始数组的验收脚本复核后已通过，不属于后端或 Android 客户端缺陷。

当前仍未执行的 Phase 2 负向验收包括：非成员读取拒绝、普通成员执行 Creator 专属操作被拒绝、归档后写入被拒绝，以及设置/成员移除/Creator 转移的真机 UI 验收。这些不阻塞本次主链路记录，但在 Phase 2 完成前必须补齐。

### Phase 2 Android 实际进展（2026-09-05，已完成主链路收尾）

- [x] 已建立 Activity Repository、DTO/domain mapper 和 ViewModel；Compose 页面不
  直接调用 Supabase SDK。
- [x] 首页活动列表、普通/大型活动创建、加入码加入、Participant 创建、Claim/
  Unclaim、子活动创建、活动设置/生命周期操作和活动管理已接入真实 UUID 与冻结
  契约中的公开 RPC/Data API。
- [x] 已明确区分账务 Participant 与真实 Auth 用户（ActivityMember）；加入时可
  立即绑定或暂不绑定，加入后可在活动管理中绑定/解除绑定，创建者同样需要绑定
  Participant 后才能进入资金类操作。
- [x] 未绑定 Participant 的用户仍可浏览活动，但转账、收款、新增消费和最终结算
  等资金入口会被引导至绑定流程；活动页右上角成员头像改为读取真实活动用户。
- [x] 已修复不同登录用户复用 Activity ViewModel 导致活动列表串用的问题，并为
  Home、Join、Activity Detail 和管理页补齐加载、重试和操作状态接线。
- [x] 用户已使用两台真机账号完成 Activity 主链路的基本验证：创建活动、加入码
  加入、绑定 Participant、创建子活动以及双方刷新后查看一致数据。
- [x] 真机准备脚本已固定目标设备并串联本地 Supabase 端口映射、Debug 构建、安装
  和启动，便于后续联调复验。

以下项目仍保留为未验收项，不因本次主链路通过而标记完成：非成员读取拒绝、普通
成员执行 Creator 专属操作被拒绝、归档后写入被拒绝，以及设置/成员移除/Creator
转移的真机 UI 负向验收。资金类 Expense、Transfer、资金记录和结算仍使用现有
Demo/Fake 实现，分别留到 Phase 3/4 接线。

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

- [x] A 创建大型活动，B 使用加入码加入并绑定 Participant，A 创建子活动，A/B
  刷新后看到一致数据（用户真机双账号主链路基本通过）。
- [ ] 非成员无法读取活动。
- [ ] 普通成员无法执行 Creator 专属操作。
- [x] 页面路由和 Repository 使用真实 UUID，不使用显示名称或 Demo ID。

Phase 2 后端主链路和 Android Activity/Participant/ActivityMember/LedgerUnit 真实接线
已完成；用户真机双账号主链路基本通过。本阶段 Demo/Fake 退出边界保持为：退出
Home、Activity、Participant、Member、LedgerUnit 的 Runtime `DemoData`；Expense、
资金记录和结算的 Runtime Demo/Fake 数据保留到 Phase 3/4，不提前清理。上述未验收
的负向用例仍需在后续验收中补齐。

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

### Phase 3 Android 实际进展（2026-09-05，UI/ViewModel/Navigation 已接线）

- [x] 已复用现有 `ExpenseRepository`，新增按当前 Auth 用户隔离的
  `ExpenseViewModel`、列表/详情/表单状态和 Factory。
- [x] 普通活动默认 LedgerUnit、大型活动子账本均通过真实 UUID 加载 active
  Expense；列表空态、加载态、失败重试和详情入口已接入。
- [x] 新增、编辑、作废、恢复、退款路由与真实 Supabase RPC 已接通；退款仍由
  repository 统一转负并携带 `original_expense_id`。
- [x] 表单已接入真实 Participant UUID、单/多付款人、AA/手动分摊、金额合计校验、
  币种/汇率、ISO-8601 `occurred_at` 和备注；重复提交会被阻止。
- [x] 详情页付款人和分摊人使用真实名称，暂不伪造 Paid/debt/settlement 状态；
  附件保留不可用占位，Storage 延后到 Phase 5；永久删除入口已移除。
- [x] 已新增 ViewModel、payload、mapper、错误映射测试；migrations 当前为 17
  条，其中唯一新增项为 deleted Expense 读取/恢复契约修复。
- [ ] 双账号真机新增、修改、作废、恢复、退款及金额投影一致性仍待用户验收。
- [ ] 并发修改、快速重复点击和服务端权限负向用例仍待真机验收。

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
Phase 1  Supabase Foundation + Auth ✅
        ↓
Phase 2  Activity + Participant + Member ✅（Android 真实接线完成，双账号主链路基本通过；负向验收保留）
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
