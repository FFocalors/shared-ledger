# SharedLedger V0.1 数据库结构设计

> 状态：设计稿，供后续 Supabase/Postgres 实现与 Android 数据层对齐。本文只描述契约，不代表已经创建 Supabase 项目、执行 SQL 或接入 SDK。
>
> 依据：当前 Compose 原型的首页、普通活动、大型活动、子活动、消费录入、转账/收款和最终结算流程；UI 中的 `DemoData` 仍是展示夹具，不是数据库实体。

## 1. 范围与非目标

### 本文范围

- 为 V0.1 支持活动创建、成员/邀请码、普通活动与大型活动、子活动、消费、多人付款与分摊、转账/收款、预存、争议和最终结算。
- 为 Supabase Data API、RPC、RLS 和 Android Repository 提供稳定的字段、状态值、ID、金额及权限约定。
- 统一普通活动和大型活动的模型：`activities.kind` 区分活动类型，`ledger_units` 承载账本范围。

### 明确不在本轮

- 不创建 Supabase 项目、表、迁移、函数、Storage bucket 或 Edge Function。
- 不在 Android 中安装 Supabase SDK，不替换现有本地 Demo 状态，不修改 Gradle、Compose UI 或导航。
- 不决定第三方汇率供应商、支付渠道、通知服务、OCR、离线同步和运营后台。
- 不允许 Android 持有 `service_role`/secret key；后续客户端只使用 publishable key（旧项目可能称 anon key）和用户 JWT。

## 2. 当前 UI 流程到数据实体

当前正式路由可归纳为以下数据边界：

| UI 流程 | 主要实体 | 备注 |
| --- | --- | --- |
| 首页“进行中/已归档”与活动卡片 | `activities`、`activity_members`、`profiles` | 卡片金额、状态和参与人数应由查询视图/聚合返回，不存 UI 文案 |
| 创建活动（普通/大型、名称、基础币种、多币种） | `activities`、`activity_members`、`ledger_units` | 必须原子创建活动、创建者 owner 和 root unit |
| 普通活动详情 | root `ledger_units`、`expenses`、`money_transfers`、结算汇总 | 普通活动只有一个 root unit，详情页直接打开它 |
| 大型活动详情 | root `ledger_units`、子 `ledger_units`、`ledger_unit_members` | 早餐/门票/酒店等均为 `subactivity` |
| 新增消费 | `expenses`、`expense_payers`、`expense_splits` | 表头和付款/分摊行必须一个事务提交 |
| 转账/收款 | `money_transfers` | “转账”和“收款”只是同一笔资金流的 UI 入口/方向文案 |
| 预存与返还 | `money_transfers.transfer_type` | 使用 `prepayment` / `prepayment_refund`，不另造余额快照表 |
| 最终结算 | `settlement_runs`、`settlement_entries`、争议记录 | 结算结果是可追溯快照；最终化后不原地重算 |

## 3. 核心建模原则

1. **活动是隔离边界。** 所有消费、成员、账本、转账和结算都必须能追溯到一个 `activity_id`。
2. **统一两类活动。** `activities.kind` 使用 `normal` / `large`；每个活动必须有且仅有一个 `ledger_units.kind = root`。大型活动可以在 root 下拥有多个 `subactivity`，普通活动不创建子活动。
3. **成员是记账主体。** `activity_members` 是分摊、付款和转账引用的主体。V0.1 推荐所有成员都是 Auth 账号；guest 成员仅作为兼容预留，尚未启用，必须先经过产品决策再选择迁移方案。这样 UI 展示的“张三”等名称仍可通过活动内显示名快照实现。
4. **权限基于成员关系和角色。** `authenticated` 只是 Postgres 角色，不等于有权访问某个活动；每条暴露表的策略都必须再检查活动成员关系和角色。
5. **显示名称是快照。** `activity_members.display_name` 记录活动内显示名；`profiles` 的昵称改变不应改写历史消费和结算文本。
6. **金额用精确十进制。** Postgres 使用 `numeric`，Android 使用 `BigDecimal`；禁止 `float`/`double` 作为账务持久化类型。
7. **账务记录可追溯。** V0.1 不从 Data API 物理删除消费、转账和已生成结算；使用 `voided`/`void` 状态或生成反向记录。
8. **对外 ID 使用 UUID。** 优先 UUIDv7 以获得时间有序索引；部署前必须确认 Supabase/Postgres 是否已启用相应扩展和函数。若未确认，统一使用 `gen_random_uuid()`，不能在文档与迁移中假定 UUIDv7 已存在。
9. **所有外键都有索引。** Postgres 不会自动为外键创建索引；除主键/唯一约束自动生成的索引外，所有 FK 都显式建索引，并为 RLS 常用复合条件建立组合索引。
10. **跨表写入走原子边界。** 简单查询可使用 Data API；活动创建、消费保存、转账、结算等跨表写入必须用事务函数（RPC）或受控服务端函数完成。

## 4. ER 图

```mermaid
erDiagram
    AUTH_USERS ||--|| PROFILES : "has"
    PROFILES ||--o{ ACTIVITIES : creates
    ACTIVITIES ||--o{ ACTIVITY_MEMBERS : contains
    PROFILES o|--o{ ACTIVITY_MEMBERS : joins
    ACTIVITIES ||--o{ ACTIVITY_INVITES : issues
    ACTIVITY_MEMBERS o|--o{ ACTIVITY_INVITES : targets
    ACTIVITIES ||--|{ LEDGER_UNITS : owns_root_and_children
    LEDGER_UNITS ||--o{ LEDGER_UNITS : parent
    ACTIVITY_MEMBERS ||--o{ LEDGER_UNIT_MEMBERS : selected
    LEDGER_UNITS ||--o{ LEDGER_UNIT_MEMBERS : includes
    LEDGER_UNITS ||--o{ EXPENSES : records
    PROFILES o|--o{ EXPENSES : creates
    EXPENSES ||--|{ EXPENSE_PAYERS : paid_by
    EXPENSES ||--|{ EXPENSE_SPLITS : split_to
    ACTIVITY_MEMBERS ||--o{ EXPENSE_PAYERS : pays
    ACTIVITY_MEMBERS ||--o{ EXPENSE_SPLITS : owes
    ACTIVITIES ||--o{ MONEY_TRANSFERS : records
    LEDGER_UNITS o|--o{ MONEY_TRANSFERS : scopes
    ACTIVITY_MEMBERS o|--o{ MONEY_TRANSFERS : from
    ACTIVITY_MEMBERS o|--o{ MONEY_TRANSFERS : to
    MONEY_TRANSFERS ||--o{ TRANSFER_DISPUTES : disputed_by
    ACTIVITIES ||--o{ SETTLEMENT_RUNS : has
    SETTLEMENT_RUNS ||--|{ SETTLEMENT_ENTRIES : contains
    ACTIVITY_MEMBERS o|--o{ SETTLEMENT_ENTRIES : from
    ACTIVITY_MEMBERS o|--o{ SETTLEMENT_ENTRIES : to
    EXPENSES ||--o{ EXPENSE_ATTACHMENTS : attaches
```

`AUTH_USERS` 是 Supabase Auth 的系统表，不由应用在 `public` schema 中创建；`PROFILES` 是应用公开资料表。`EXPENSE_ATTACHMENTS` 在 V0.1 标为延期，但保留关系位置以避免将来改变 `expenses` 主键模型。

## 5. 表结构

### 5.1 `public.profiles`（V0.1 核心）

与 `auth.users` 一对一。只保存应用所需公开资料，不复制密码、Token 或任何 secret。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `uuid` | 否 | `auth.uid()`/触发器 | PK，FK `auth.users(id)` `ON DELETE CASCADE` | 与 Auth 用户同 ID |
| `version` | `bigint` | 否 | `1` | `CHECK version >= 1` | 行级乐观并发版本；每次有效更新递增 |
| `display_name` | `text` | 否 | 无 | `length(trim(display_name)) BETWEEN 1 AND 80` | 默认展示名 |
| `avatar_url` | `text` | 是 | `NULL` | 仅存公开 URL/Storage 路径；禁止写入 token | V0.1 可不使用 |
| `timezone` | `text` | 否 | `'Asia/Shanghai'` | 合法 IANA 时区由应用校验 | 用于日期展示，不改变账务时间 |
| `created_at` | `timestamptz` | 否 | `now()` | 不可由普通客户端改写 | 创建时间 |
| `updated_at` | `timestamptz` | 否 | `now()` | 服务端触发器维护 | 更新时间 |

### 5.2 `public.activities`（V0.1 核心）

活动是 RLS 的主要租户边界。`owner` 不单独存用户字段，而由 `activity_members.role = owner` 表达，便于转移所有权且保持成员历史。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `uuid` | 否 | UUID 函数 | PK | 对外活动 ID |
| `created_by_user_id` | `uuid` | 是 | `auth.uid()` | FK `auth.users(id)` `ON DELETE SET NULL` | 创建者审计；删除用户后保留活动 |
| `name` | `text` | 否 | 无 | trim 后 1–120 字符 | 活动名称 |
| `kind` | `text` | 否 | `'normal'` | CHECK `normal|large` | 对应 `ActivityKind` |
| `status` | `text` | 否 | `'in_progress'` | CHECK 见状态表 | 首页“进行中/已归档”及结算状态 |
| `base_currency` | `char(3)` | 否 | `'CNY'` | 大写 ISO 4217 代码；部署时确认货币表/代码集 | 活动汇总币种 |
| `multi_currency_enabled` | `boolean` | 否 | `false` | 无 | 是否允许消费使用非基础币种 |
| `revision` | `bigint` | 否 | `0` | `CHECK revision >= 0` | 每次有效账务/成员变更递增，结算乐观并发依据 |
| `archived_at` | `timestamptz` | 是 | `NULL` | status 为 archived 时应非空（由 RPC 保证） | 归档时间 |
| `settled_at` | `timestamptz` | 是 | `NULL` | status 为 settled 时应非空（由 RPC 保证） | 最终结算完成时间 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | 创建时间 |
| `updated_at` | `timestamptz` | 否 | `now()` | 服务端维护 | 最后修改时间 |

### 5.3 `public.activity_members`（V0.1 核心，账号成员方案）

V0.1 推荐只启用 Auth 账号成员：迁移时可将 `user_id` 设为 `NOT NULL`、移除 `guest` 分支，并让邀请接受流程创建已登录用户成员。当前设计稿保留 `user_id` 可空和 `member_kind` 字段，仅为未来 guest 兼容方案留出位置；guest **不是当前已确认的 V0.1 能力**，必须在产品确认后单独决定是否启用及是否保留这些可空字段。若最终启用 guest，guest 没有直接调用 API 的身份，访问活动仍必须由已认证的活动成员完成。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `uuid` | 否 | UUID 函数 | PK | 分摊/付款/转账引用此 ID，不直接引用昵称 |
| `version` | `bigint` | 否 | `1` | `CHECK version >= 1` | 行级乐观并发版本；每次有效更新递增 |
| `activity_id` | `uuid` | 否 | 无 | FK `activities(id)` `ON DELETE RESTRICT` | 活动边界 |
| `user_id` | `uuid` | 是（账号方案应否） | `NULL` | FK `auth.users(id)` `ON DELETE SET NULL`；账号方案要求非空 | 已注册成员；仅 guest 方案允许为空 |
| `member_kind` | `text` | 否（兼容字段） | `'user'` | 当前只允许 `user`；若产品启用 guest 才扩展为 `user|guest` | 成员身份类型；guest 预留未启用 |
| `display_name` | `text` | 否 | 无 | trim 后 1–80 字符 | 活动内名称快照 |
| `role` | `text` | 否 | `'member'` | CHECK `owner|admin|member` | 活动权限角色 |
| `status` | `text` | 否 | `'active'` | CHECK `invited|active|left|removed` | 成员生命周期 |
| `joined_at` | `timestamptz` | 是 | `NULL` | active 时由 RPC 填写 | 加入时间 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | 记录时间 |
| `updated_at` | `timestamptz` | 否 | `now()` | 服务端维护 | 更新时间 |

唯一约束：`UNIQUE (activity_id, user_id)` 仅对 `user_id IS NOT NULL` 建唯一部分索引；同一活动的访客成员名称是否唯一待产品确认，不用名称作为稳定身份。

### 5.4 `public.activity_invites`（V0.1 核心）

邀请码只存不可逆 hash；明文邀请码通过 RPC 返回一次，不能写入数据库日志或普通表列。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `uuid` | 否 | UUID 函数 | PK | 邀请记录 |
| `version` | `bigint` | 否 | `1` | `CHECK version >= 1` | 邀请状态更新的行级版本 |
| `activity_id` | `uuid` | 否 | 无 | FK `activities(id)` `ON DELETE RESTRICT` | 目标活动 |
| `target_member_id` | `uuid` | 是 | `NULL` | FK `activity_members(id)` `ON DELETE SET NULL` | 仅未来启用 guest 方案时关联预创建成员；V0.1 账号方案通常为空 |
| `code_hash` | `text` | 否 | 无 | 唯一；只允许 hash，不存明文 | 邀请码校验值 |
| `invited_email` | `text` | 是 | `NULL` | 可选格式校验；V0.1 不强制邮件邀请 | 目标邮箱 |
| `role` | `text` | 否 | `'member'` | CHECK `member|admin`；禁止邀请 owner | 接受后的角色上限 |
| `status` | `text` | 否 | `'pending'` | CHECK `pending|accepted|expired|revoked` | 邀请生命周期 |
| `expires_at` | `timestamptz` | 否 | `now() + interval '7 days'` | 必须晚于创建时间 | 有效期 |
| `created_by_user_id` | `uuid` | 是 | `auth.uid()` | FK `auth.users(id)` `ON DELETE SET NULL` | 创建者审计；用户删除后保留邀请历史 |
| `accepted_by_user_id` | `uuid` | 是 | `NULL` | FK `auth.users(id)` `ON DELETE SET NULL` | 接受者 |
| `accepted_at` | `timestamptz` | 是 | `NULL` | accepted 时由 RPC 填写 | 接受时间 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | 创建时间 |

### 5.5 `public.ledger_units`（V0.1 核心）

root 和 subactivity 使用同一张表。正常活动的 root 是唯一账本；大型活动的子活动均挂在 root 下。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `uuid` | 否 | UUID 函数 | PK | 账本单元 ID |
| `version` | `bigint` | 否 | `1` | `CHECK version >= 1` | 行级乐观并发版本；每次有效更新递增 |
| `activity_id` | `uuid` | 否 | 无 | FK `activities(id)` `ON DELETE RESTRICT` | 活动边界 |
| `parent_unit_id` | `uuid` | 是 | `NULL` | 自 FK `ledger_units(id)` `ON DELETE RESTRICT` | root 为 NULL，子活动指向 root |
| `kind` | `text` | 否 | `'root'` | CHECK `root|subactivity` | 账本层级 |
| `name` | `text` | 否 | 无 | trim 后 1–120 字符 | root 可与活动同名；子活动名称 |
| `status` | `text` | 否 | `'active'` | CHECK `active|archived` | 软归档 |
| `created_by_user_id` | `uuid` | 是 | `auth.uid()` | FK `auth.users(id)` `ON DELETE SET NULL` | 创建者审计；用户删除后保留账本历史 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | 创建时间 |
| `updated_at` | `timestamptz` | 否 | `now()` | 服务端维护 | 更新时间 |

关键约束：部分唯一索引 `UNIQUE (activity_id) WHERE kind = 'root'`；root 的 `parent_unit_id` 必须为空，subactivity 的 parent 必须是同一活动 root，这类跨行约束在创建/更新 RPC 中再次验证。

### 5.6 `public.ledger_unit_members`（V0.1 核心）

root unit 通常由活动成员初始化；子活动可选择活动成员子集。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `ledger_unit_id` | `uuid` | 否 | 无 | FK `ledger_units(id)` `ON DELETE RESTRICT` | 账本单元 |
| `activity_member_id` | `uuid` | 否 | 无 | FK `activity_members(id)` `ON DELETE RESTRICT` | 活动成员 |
| `version` | `bigint` | 否 | `1` | `CHECK version >= 1` | 成员状态更新的行级版本 |
| `status` | `text` | 否 | `'active'` | CHECK `active|removed` | 子活动成员状态 |
| `added_by_user_id` | `uuid` | 是 | `auth.uid()` | FK `auth.users(id)` `ON DELETE SET NULL` | 操作者 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | 加入时间 |

主键：`(ledger_unit_id, activity_member_id)`。跨表同活动约束由 RPC/触发器校验；不允许把其他活动成员插入此表。

### 5.7 `public.expenses`（V0.1 核心）

消费金额以原币种保存，同时保存用于活动汇总的基础币种快照，避免将来汇率变化重写历史账。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `uuid` | 否 | UUID 函数 | PK | 消费 ID |
| `version` | `bigint` | 否 | `1` | `CHECK version >= 1` | 行级乐观并发版本；每次有效更新递增 |
| `ledger_unit_id` | `uuid` | 否 | 无 | FK `ledger_units(id)` `ON DELETE RESTRICT` | 消费所属账本 |
| `title` | `text` | 否 | 无 | trim 后 1–120 字符 | UI 的消费名称 |
| `amount` | `numeric(20,4)` | 否 | 无 | `amount > 0` | 原币种金额 |
| `currency_code` | `char(3)` | 否 | 活动基础币种 | 大写 ISO 4217；需与活动多币种开关一致 | 原币种 |
| `base_amount` | `numeric(20,4)` | 否 | 无 | `base_amount > 0` | 按当时汇率换算后的活动基础币种金额 |
| `fx_rate` | `numeric(20,10)` | 否 | `1` | `fx_rate > 0`；同币种必须为 1 | `base_amount = amount * fx_rate` 的快照 |
| `fx_rate_source` | `text` | 是 | `NULL` | `manual|provider|same_currency` | V0.1 可仅允许 manual/same_currency |
| `split_method` | `text` | 否 | `'custom'` | CHECK `equal|custom` | UI 选项对应的分摊方式 |
| `occurred_at` | `timestamptz` | 否 | `now()` | 无 | 消费发生时间，不使用本地 timestamp |
| `note` | `text` | 是 | `NULL` | 最大长度由 RPC 校验 | 备注 |
| `created_by_user_id` | `uuid` | 是 | `auth.uid()` | FK `auth.users(id)` `ON DELETE SET NULL` | 创建者审计 |
| `status` | `text` | 否 | `'active'` | CHECK `active|voided` | 不物理删除 |
| `client_operation_id` | `uuid` | 是 | `NULL` | 同用户唯一；写入 RPC 幂等键 | Android 重试防重复 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | 创建时间 |
| `updated_at` | `timestamptz` | 否 | `now()` | 服务端维护 | 更新时间 |

`expense_payers` 和 `expense_splits` 的原币金额与 `base_amount` 必须在同一事务校验总和；V0.1 不依赖浮点四舍五入。

### 5.8 `public.expense_payers`（V0.1 核心）

一笔消费可以由多个活动成员共同付款。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `expense_id` | `uuid` | 否 | 无 | FK `expenses(id)` `ON DELETE RESTRICT` | 消费 |
| `activity_member_id` | `uuid` | 否 | 无 | FK `activity_members(id)` `ON DELETE RESTRICT` | 付款人 |
| `amount` | `numeric(20,4)` | 否 | 无 | `amount > 0` | 原币付款金额 |
| `base_amount` | `numeric(20,4)` | 否 | 无 | `base_amount > 0` | 基础币种快照 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | 创建时间 |

主键：`(expense_id, activity_member_id)`。总付款金额必须等于 `expenses.amount`。

### 5.9 `public.expense_splits`（V0.1 核心）

记录每个成员在一笔消费中的应承担份额，保证结算可重放。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `expense_id` | `uuid` | 否 | 无 | FK `expenses(id)` `ON DELETE RESTRICT` | 消费 |
| `activity_member_id` | `uuid` | 否 | 无 | FK `activity_members(id)` `ON DELETE RESTRICT` | 承担人 |
| `amount` | `numeric(20,4)` | 否 | 无 | `amount >= 0` | 原币承担金额 |
| `base_amount` | `numeric(20,4)` | 否 | 无 | `base_amount >= 0` | 基础币种承担额 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | 创建时间 |

主键：`(expense_id, activity_member_id)`。所有分摊行合计必须等于 `expenses.amount`；V0.1 不保存可变算法输入，保存最终分摊结果即可。

### 5.10 `public.money_transfers`（V0.1 核心）

统一承载普通转账、收款入口、预存和预存返还。`transfer_type` 仅允许 `transfer|prepayment|prepayment_refund`；UI 的 `transfer`/`receive` 是入口方向和文案，不是数据库枚举值。普通转账始终是 `from_member_id -> to_member_id`。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `uuid` | 否 | UUID 函数 | PK | 资金流记录 |
| `version` | `bigint` | 否 | `1` | `CHECK version >= 1` | 行级乐观并发版本；每次有效更新递增 |
| `activity_id` | `uuid` | 否 | 无 | FK `activities(id)` `ON DELETE RESTRICT` | 活动边界 |
| `ledger_unit_id` | `uuid` | 是 | `NULL` | FK `ledger_units(id)` `ON DELETE RESTRICT` | 可限定子活动；活动级转账为空 |
| `transfer_type` | `text` | 否 | `'transfer'` | CHECK 仅 `transfer|prepayment|prepayment_refund` | 资金语义；不存在 `receive` 类型 |
| `from_member_id` | `uuid` | 是 | `NULL` | FK `activity_members(id)` `ON DELETE RESTRICT` | 普通转账/预存付款方 |
| `to_member_id` | `uuid` | 是 | `NULL` | FK `activity_members(id)` `ON DELETE RESTRICT` | 普通转账/返还收款方 |
| `amount` | `numeric(20,4)` | 否 | 无 | `amount > 0` | 原币金额 |
| `currency_code` | `char(3)` | 否 | 活动基础币种 | 大写 ISO 4217 | 原币种 |
| `base_amount` | `numeric(20,4)` | 否 | 无 | `base_amount > 0` | 基础币金额快照 |
| `fx_rate` | `numeric(20,10)` | 否 | `1` | `fx_rate > 0` | 换算快照 |
| `status` | `text` | 否 | `'pending'` | CHECK `pending|confirmed|disputed|void` | 资金记录状态 |
| `note` | `text` | 是 | `NULL` | 最大长度由 RPC 校验 | 备注 |
| `occurred_at` | `timestamptz` | 否 | `now()` | 无 | 转账发生时间 |
| `created_by_user_id` | `uuid` | 是 | `auth.uid()` | FK `auth.users(id)` `ON DELETE SET NULL` | 录入者 |
| `client_operation_id` | `uuid` | 是 | `NULL` | 同用户唯一；写入 RPC 幂等键 | 防重复录入 |
| `confirmed_at` | `timestamptz` | 是 | `NULL` | confirmed 时由 RPC 填写 | 确认时间 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | 创建时间 |
| `updated_at` | `timestamptz` | 否 | `now()` | 服务端维护 | 更新时间 |

方向检查（由 RPC/约束共同保证）：

- `transfer`：`from_member_id`、`to_member_id` 都非空，且不可相同。
- `prepayment`：`from_member_id` 非空，`to_member_id` 为空，表示成员向活动预存池缴款。
- `prepayment_refund`：`from_member_id` 为空，`to_member_id` 非空，表示活动预存池向成员返还。

预存池不伪造一个用户成员；余额由同一活动、同一币种下的预存与返还流水计算。

### 5.11 `public.transfer_disputes`（V0.1 核心）

争议与原转账分离，保留多次提出/处理的审计信息。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `uuid` | 否 | UUID 函数 | PK | 争议 ID |
| `version` | `bigint` | 否 | `1` | `CHECK version >= 1` | 争议状态更新的行级版本 |
| `money_transfer_id` | `uuid` | 否 | 无 | FK `money_transfers(id)` `ON DELETE RESTRICT` | 被争议流水 |
| `reported_by_member_id` | `uuid` | 否 | 无 | FK `activity_members(id)` `ON DELETE RESTRICT` | 提出人 |
| `status` | `text` | 否 | `'open'` | CHECK `open|acknowledged|resolved|rejected` | 争议状态 |
| `reason` | `text` | 否 | 无 | trim 后 1–1000 字符 | 说明 |
| `resolved_by_user_id` | `uuid` | 是 | `NULL` | FK `auth.users(id)` `ON DELETE SET NULL` | 处理人 |
| `resolution_note` | `text` | 是 | `NULL` | 无 | 处理说明 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | 提出时间 |
| `resolved_at` | `timestamptz` | 是 | `NULL` | resolved/rejected 时填写 | 处理时间 |

### 5.12 `public.settlement_runs`（V0.1 核心）

只持久化已经执行最终化的结算批次；客户端的 settlement preview 是只读计算结果，不创建 `settlement_runs` 行。最终结算不会直接覆盖上一版结果。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `uuid` | 否 | UUID 函数 | PK | 结算批次 |
| `version` | `bigint` | 否 | `1` | `CHECK version >= 1` | 仅在允许 void 等状态更新时递增 |
| `activity_id` | `uuid` | 否 | 无 | FK `activities(id)` `ON DELETE RESTRICT` | 活动 |
| `status` | `text` | 否 | `'finalized'` | CHECK 仅 `finalized|void` | 只有 finalize RPC 持久化结算批次；preview 不落库 |
| `input_revision` | `bigint` | 否 | 无 | 非负 | 计算时的 `activities.revision` |
| `algorithm_version` | `text` | 否 | `'v0.1'` | 非空 | 结算算法版本 |
| `base_currency` | `char(3)` | 否 | 活动基础币种 | 大写 ISO 4217 | 汇总币种快照 |
| `total_expense_base` | `numeric(20,4)` | 否 | `0` | `>= 0` | 总消费 |
| `total_prepayment_base` | `numeric(20,4)` | 否 | `0` | `>= 0` | 预存合计 |
| `total_transfer_base` | `numeric(20,4)` | 否 | `0` | `>= 0` | 普通转账合计 |
| `created_by_user_id` | `uuid` | 是 | `auth.uid()` | FK `auth.users(id)` `ON DELETE SET NULL` | 发起人 |
| `finalized_by_user_id` | `uuid` | 是 | `NULL` | FK `auth.users(id)` `ON DELETE SET NULL` | 最终化人 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | finalize 成功后创建记录的时间 |
| `finalized_at` | `timestamptz` | 是 | `NULL` | finalized 时填写 | 最终化时间 |

### 5.13 `public.settlement_entries`（V0.1 核心）

结算建议中的每一条“谁给谁多少钱”或预存返还。最终化后视为不可变快照；已执行状态由资金流水关联。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `uuid` | 否 | UUID 函数 | PK | 结算条目 |
| `version` | `bigint` | 否 | `1` | `CHECK version >= 1` | 记录/争议/void 更新的行级版本 |
| `settlement_run_id` | `uuid` | 否 | 无 | FK `settlement_runs(id)` `ON DELETE RESTRICT` | 结算批次 |
| `sequence_no` | `integer` | 否 | 无 | `> 0`；同 run 唯一 | 稳定展示顺序 |
| `entry_type` | `text` | 否 | `'transfer'` | CHECK `transfer|prepayment_refund` | 条目类型 |
| `from_member_id` | `uuid` | 是 | `NULL` | FK `activity_members(id)` `ON DELETE RESTRICT` | transfer 的付款方；返还时为空 |
| `to_member_id` | `uuid` | 是 | `NULL` | FK `activity_members(id)` `ON DELETE RESTRICT` | transfer 的收款方；返还时为成员 |
| `amount` | `numeric(20,4)` | 否 | 无 | `amount > 0` | 原币金额 |
| `base_amount` | `numeric(20,4)` | 否 | 无 | `base_amount > 0` | 基础币金额 |
| `currency_code` | `char(3)` | 否 | 无 | 大写 ISO 4217 | 原币种 |
| `status` | `text` | 否 | `'proposed'` | CHECK `proposed|recorded|disputed|void` | 执行状态 |
| `recorded_transfer_id` | `uuid` | 是 | `NULL` | FK `money_transfers(id)` `ON DELETE RESTRICT` | 已记录时关联实际流水 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | 创建时间 |

唯一约束：`UNIQUE (settlement_run_id, sequence_no)`。`entry_type` 的方向检查和“同一 run 只能对应一个活动”的一致性由最终化 RPC 校验。

### 5.14 `public.expense_attachments`（延期）

V0.1 不接 Storage；若启用，数据库只存元数据，文件放 Supabase Storage 私有 bucket。

| 字段 | 类型 | 可空 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `uuid` | 否 | UUID 函数 | PK | 附件 ID |
| `expense_id` | `uuid` | 否 | 无 | FK `expenses(id)` `ON DELETE RESTRICT` | 所属消费 |
| `storage_bucket` | `text` | 否 | 无 | 固定私有 bucket 名 | 不暴露公开 URL |
| `storage_path` | `text` | 否 | 无 | 同 bucket 唯一 | Storage 对象路径，不含 secret |
| `file_name` | `text` | 否 | 无 | 长度限制 | 原文件名 |
| `mime_type` | `text` | 否 | 无 | allow-list | 内容类型 |
| `byte_size` | `bigint` | 否 | 无 | `> 0` 且上限由 RPC 校验 | 文件大小 |
| `checksum` | `text` | 是 | `NULL` | 可选 | 去重/完整性校验 |
| `uploaded_by_user_id` | `uuid` | 是 | `auth.uid()` | FK `auth.users(id)` `ON DELETE SET NULL` | 上传人；用户删除后保留附件元数据 |
| `created_at` | `timestamptz` | 否 | `now()` | 无 | 创建时间 |

### 5.15 版本字段约定

除 `activities` 使用聚合级 `revision` 外，所有允许状态或资料更新的资源使用 `version bigint NOT NULL DEFAULT 1 CHECK (version >= 1)`。当前包括 `profiles`、`activity_members`、`activity_invites`、`ledger_units`、`ledger_unit_members`、`expenses`、`money_transfers`、`transfer_disputes`、`settlement_runs` 和 `settlement_entries`；付款/分摊明细在创建后由 bundle RPC 整体替换，因此不单独开放更新。

行更新必须携带 `expected_version`，在同一事务中执行条件更新并将该行 `version + 1`。任何有效账务或成员变化还要将所属 `activities.revision + 1`。`activities` 本身的名称、状态等更新只使用 `expected_revision`，不再添加同义的 `version` 字段。

## 6. 状态值与状态转移

数据库实际存小写 snake_case；Android 可映射为 Kotlin enum。禁止直接把中文 UI 文案存为状态。

| 范围 | 状态值 | 说明 |
| --- | --- | --- |
| Activity | `in_progress` | 可记账、可邀请、可转账 |
| Activity | `pending_settlement` | 已发起/等待最终结算，是否允许继续记账由产品确认 |
| Activity | `settled` | 最终结算完成；原则上只读，可查看历史 |
| Activity | `archived` | 首页已归档；不等于删除 |
| Activity | `disputed` | 存在未解决争议，禁止最终化 |
| Member | `invited`, `active`, `left`, `removed` | `left/removed` 保留历史引用 |
| Invite | `pending`, `accepted`, `expired`, `revoked` | 接受/撤销/过期互斥 |
| Ledger unit | `active`, `archived` | 归档子活动保留账目 |
| Expense | `active`, `voided` | void 需要操作者权限和原因（原因可后续放审计表） |
| Transfer | `pending`, `confirmed`, `disputed`, `void` | disputed 不得被结算 RPC 当作已确认资金 |
| Dispute | `open`, `acknowledged`, `resolved`, `rejected` | unresolved 会阻断最终化 |
| Settlement run | `finalized`, `void` | 只持久化最终化批次；preview 是只读结果，不落库 |
| Settlement entry | `proposed`, `recorded`, `disputed`, `void` | recorded 应关联一笔 money transfer |

推荐的主要转移：

```text
in_progress -> pending_settlement -> settled
in_progress -> archived
pending_settlement -> disputed -> pending_settlement
expense active -> voided
transfer pending -> confirmed | disputed | void
只读 settlement preview -> finalize RPC 创建 finalized run/entries；或因 revision/争议变化而重新计算
```

所有状态转移必须经过角色和前置状态检查；不要通过开放的 PATCH 让客户端随意写入 status。

## 7. 金额、币种和舍入规则

- 所有金额列使用 `numeric(20,4)`；汇率快照使用 `numeric(20,10)`。Android 使用 `BigDecimal`，网络 DTO 以 JSON number 的十进制字符串或明确 decimal 序列化约定传输，禁止 binary float。
- `currency_code` 统一大写 ISO 4217 三字符代码。活动 `base_currency` 是所有汇总/结算的币种；V0.1 先支持 CNY、EUR 等 UI 已出现的代码，但完整 allow-list 需在实现时确认。
- `multi_currency_enabled = false` 时，消费和资金流水的币种必须等于 `base_currency`；开启后允许其他币种，但每一条记录必须保存 `fx_rate`、`base_amount` 和汇率来源快照。
- 同币种 `fx_rate = 1` 且 `base_amount = amount`。跨币种换算在写入事务中完成；不可在查询时使用“当前汇率”重算旧账。
- 录入层精度最多 4 位小数；展示层可按币种 fraction digits 格式化，但不能把展示舍入值反写数据库。
- 分摊合计、付款合计在原币种精度下必须等于消费金额；换算后的基础币分配若出现最小单位余数，由 RPC 按固定、可解释的 remainder 规则分配，并记录算法版本。
- 结算只在同一活动的基础币种中聚合；不同币种必须先有明确汇率快照，否则拒绝最终化。

## 8. 必要唯一约束和索引

主键和唯一约束会自动生成索引；下面列出额外必须显式规划的索引。所有外键列都应被单列或组合索引覆盖。

| 表 | 索引/约束 | 用途 |
| --- | --- | --- |
| `activities` | `activities_created_by_user_idx (created_by_user_id)` | 创建者查询/RLS |
| `activities` | `activities_status_updated_idx (status, updated_at DESC, id)` | 首页进行中/归档游标列表 |
| `activity_members` | 部分唯一 `(activity_id, user_id) WHERE user_id IS NOT NULL` | 同一用户不可重复入活动 |
| `activity_members` | `activity_members_activity_status_idx (activity_id, status)` | 成员/RLS 查询 |
| `activity_members` | `activity_members_user_status_idx (user_id, status) WHERE user_id IS NOT NULL` | 首页活动列表/RLS |
| `activity_invites` | 唯一 `(code_hash)` | 邀请码校验 |
| `activity_invites` | `(activity_id, status, expires_at)` | 管理邀请和过期清理 |
| `ledger_units` | 部分唯一 `(activity_id) WHERE kind = 'root'` | 每活动唯一 root |
| `ledger_units` | `(activity_id, kind, status, updated_at DESC, id)` | 大型活动子账本列表 |
| `ledger_units` | `(parent_unit_id)` | 自 FK 与子活动查询 |
| `ledger_unit_members` | PK `(ledger_unit_id, activity_member_id)` | 去重与 RLS 连接 |
| `ledger_unit_members` | `(activity_member_id, status)` | 成员反查账本 |
| `expenses` | `(ledger_unit_id, status, occurred_at DESC, id)` | 明细时间线/游标分页 |
| `expenses` | `(created_by_user_id)` | 审计/RLS |
| `expenses` | 部分唯一 `(created_by_user_id, client_operation_id) WHERE client_operation_id IS NOT NULL` | 消费写入幂等 |
| `expense_payers` | `(activity_member_id)` | 成员付款汇总/FK |
| `expense_splits` | `(activity_member_id)` | 成员承担汇总/FK |
| `money_transfers` | `(activity_id, status, occurred_at DESC, id)` | 活动流水/争议 |
| `money_transfers` | `(from_member_id)`, `(to_member_id)` | 方向汇总和 FK |
| `money_transfers` | 部分唯一 `(created_by_user_id, client_operation_id) WHERE client_operation_id IS NOT NULL` | 转账写入幂等 |
| `transfer_disputes` | `(money_transfer_id, status)` | 争议检查/阻断结算 |
| `settlement_runs` | `(activity_id, created_at DESC, id)` | 历史结算和最新批次 |
| `settlement_entries` | 唯一 `(settlement_run_id, sequence_no)` | 稳定顺序/去重 |
| `settlement_entries` | `(from_member_id)`, `(to_member_id)` | 参与者查询 |
| `expense_attachments` | 唯一 `(storage_bucket, storage_path)`、`(expense_id)` | Storage 元数据关联 |

首页、活动明细和流水列表应使用 `(updated_at/occurred_at, id)` 组合游标，而不是深分页 `OFFSET`。索引是否符合真实查询计划，待迁移后用 `EXPLAIN` 和 Supabase advisors 验证。

## 9. RLS 与 GRANT 权限矩阵

### 9.1 总原则

- `public` 中每一张暴露给 Data API 的表都必须启用 RLS；是否暴露表（GRANT/Data API exposure）与是否允许某一行（RLS）是两个独立层次。
- 所有客户端策略至少 `TO authenticated`，并追加 `activity_members` 的活动/成员/角色谓词。`TO authenticated` 单独不能阻止越权读取（BOLA/IDOR）。
- 不使用 `user_metadata`、`raw_user_meta_data` 或用户可编辑 JWT 字段做授权。角色、成员关系只来自数据库表/RPC；如将来使用 `app_metadata`，必须接受 JWT 刷新延迟。
- UPDATE 必须同时有可读该行的 SELECT policy、`USING`（旧行）和 `WITH CHECK`（新行）；否则可能出现静默更新 0 行或把行转给其他用户的问题。
- Android 永远不拿 `service_role`；service role 只限受控服务端/迁移环境。默认不授予 `anon` 任何业务表权限。
- 所有客户端可调用 RPC 默认为 `SECURITY INVOKER`，让调用者的 RLS/GRANT 生效；`SECURITY DEFINER` 仅可作为经过审计的内部非暴露 helper 备选，不能作为客户端越权写入的捷径。

### 9.2 表级最小权限矩阵

符号含义：`R`=SELECT，`I`=INSERT，`U`=UPDATE，`D`=DELETE；“RPC”表示客户端不应直接写表，而通过显式事务函数。表格是产品目标权限，不是已经执行的 SQL。

| 表 | anon | authenticated 读取 | authenticated 写入 | 授权依据 |
| --- | --- | --- | --- | --- |
| `profiles` | 无 | 读自己；必要时活动共同成员的公开展示字段 | 仅更新自己允许字段；创建由 Auth 后置流程/RPC | `profiles.id = auth.uid()` 或共同活动成员 |
| `activities` | 无 | 活动 active member 可读 | 创建 RPC；owner/admin 更新；不开放删除 | `activity_members` active + role |
| `activity_members` | 无 | 同活动 active member 可读 | 邀请/加入/角色变更走 RPC；本人可退出 | 同活动关系；owner/admin 管理 |
| `activity_invites` | 无 | owner/admin 读写管理字段；接受邀请码走 RPC | owner/admin 创建/撤销；接受 RPC 锁定邀请码 | 活动角色，邀请码 hash 不下发 |
| `ledger_units` | 无 | 同活动 member 可读 | owner/admin 创建；creator/owner/admin 更新；归档 RPC | 活动成员 + 角色 |
| `ledger_unit_members` | 无 | 同活动 member 可读 | 子活动创建/成员调整走 RPC | 活动成员 + unit 管理权限 |
| `expenses` | 无 | 活动/unit member 可读 active/voided | 消费 bundle RPC；void RPC；不开放物理 DELETE | unit membership + 活动角色 |
| `expense_payers` | 无 | 与 expense 同范围可读 | 仅消费 bundle RPC | expense 所属活动成员 |
| `expense_splits` | 无 | 与 expense 同范围可读 | 仅消费 bundle RPC | expense 所属活动成员 |
| `money_transfers` | 无 | 同活动 member 可读；可按参与方过滤 | record/dispute RPC；不开放删除 | 活动成员，涉及方与 admin 的更细规则待确认 |
| `transfer_disputes` | 无 | 提出人、转账涉及方、admin 可读 | member 提出；admin/授权处理 RPC | 转账关系 + 活动角色 |
| `settlement_runs` | 无 | 同活动 member 可读 | 仅 finalize RPC 创建 finalized run；void RPC；普通客户端无直接 INSERT/U | 活动成员；finalize 需 owner/admin |
| `settlement_entries` | 无 | 同活动 member 可读 | record entry RPC；不开放删除 | settlement 活动关系 + 涉及方/admin |
| `expense_attachments` | 无 | 同活动 member 可读元数据；Storage 用独立 policy | 上传/删除走签名 URL + RPC；延期 | expense 活动关系 |

实现时建议：

- 业务表只向 `authenticated` grant 必要的 `SELECT`，复杂写入表的 `INSERT/UPDATE/DELETE` 可以不向客户端 grant，改为只 `GRANT EXECUTE` 给明确的 RPC；这不替代 RLS，函数返回的数据仍须遵守活动授权。
- RLS 中频繁的成员判断要有索引。若出现 policy recursion，需要审计过的 `private` schema helper：`SECURITY DEFINER`、固定 `search_path = ''`、函数体显式检查 `auth.uid()`、放在非暴露 schema，并撤销 `PUBLIC/anon/authenticated` 不必要的 EXECUTE。它是备选，不是默认解法；客户端 RPC 仍默认为 `SECURITY INVOKER`。
- `activity_summaries`、`activity_prepayment_summary`、`member_balance` 等只是未来的只读查询视图/投影名称，不是当前已部署表。若将来提供，必须使用 `security_invoker = true`（Postgres 15+）或放非暴露 schema/撤销客户端访问，不能以视图绕过源表策略。

## 10. 原子事务与 RPC 边界

### 10.1 需要 RPC/事务函数的写操作

| 建议函数名 | 输入摘要 | 原子保证/校验 |
| --- | --- | --- |
| `create_activity_with_owner` | name、kind、base_currency、multi_currency、初始成员 | 创建 activity、owner member、唯一 root unit、root members；一次提交或全部回滚 |
| `join_activity_by_invite` | 明文邀请码、display_name | hash 校验、未过期/未撤销、锁定 invite、防重复 membership、写 accepted 状态 |
| `create_ledger_unit_with_members` | activity_id、kind、parent root、name、member IDs、expected revision | 创建 root/subactivity 和成员关系；parent 为 root；成员必须属于同一活动；递增 revision |
| `update_ledger_unit` | ledger_unit_id、patch、expected version/revision | 仅 owner/admin 或授权成员更新名称/状态；校验活动关系；递增该行 version 和 activities.revision |
| `archive_ledger_unit` | ledger_unit_id、expected version/revision | 软归档 unit，不删除消费和成员历史；递增该行 version 和 activities.revision |
| `create_expense_with_allocations` | unit、表头、payer rows、split rows、client_operation_id、expected revision | 验证 unit/member 同属活动、币种/汇率、付款与分摊合计；幂等返回原 expense，并 bump 活动 revision |
| `void_expense` | expense_id、reason、expected version/revision | 只允许 owner/admin 或原录入者的规定范围；不删除 payer/split；递增 expense version 和活动 revision |
| `record_money_transfer` | activity/unit、type、from/to、金额、client_operation_id、expected revision | 方向、成员、币种、余额/状态检查；幂等；递增活动 revision |
| `open_transfer_dispute` / `resolve_transfer_dispute` | transfer/dispute、原因/处理说明、expected version/revision | 检查涉及方/角色，更新 transfer/dispute version 和状态一致性 |
| `preview_activity_settlement` | activity_id、current/expected revision（可选） | 只读计算并返回建议、阻断原因和 input revision；不创建 `settlement_runs` 或 `settlement_entries` |
| `finalize_activity_settlement` | activity_id、expected revision | 锁活动并确认 revision 未变化；写 finalized run/entries；更新 activity 状态；一次提交 |
| `record_settlement_entry` | entry_id、expected version、client_operation_id | 将已执行结算写成 money transfer，并把 entry 标记 recorded；禁止重复记账；递增 entry version 和活动 revision |

### 10.2 可直接使用 Data API 的读取

- 活动列表、活动详情、成员列表、root/子活动列表、消费时间线、转账历史可以通过表查询或安全视图读取，前提是 RLS 已经覆盖完整关系路径。
- 聚合 DTO（首页卡片金额、待结算卡、成员净额、结算建议）优先提供 `security_invoker` 视图或只读 RPC，避免 Android 在本地重复拼接多表账务逻辑。
- RPC 不应包含网络请求、邮件发送或长时间外部调用；先在事务外完成外部工作，再用短事务写库，减少锁竞争。

## 11. 并发与幂等

- 除 `activities` 外，带有可变状态或资料的资源使用行级 `version bigint NOT NULL DEFAULT 1 CHECK (version >= 1)`（当前包括 `profiles`、`activity_members`、`activity_invites`、`ledger_units`、`ledger_unit_members`、`expenses`、`money_transfers`、`transfer_disputes`、`settlement_runs` 和 `settlement_entries`）。每次有效 UPDATE 必须以 `expected_version` 条件更新并将 `version + 1`；不匹配返回 `conflict/stale_version`。
- `activities.revision` 是活动聚合版本，不增加另一个 `activities.version`。活动本身的资料/状态更新也接收 `expected_revision`；任何有效账务或成员变更同时 bump `activities.revision`，避免结算读到半套数据。
- 消费和转账写入携带客户端生成的 `client_operation_id`（UUID）。对 `(created_by_user_id, client_operation_id)` 建部分唯一约束；网络重试必须返回同一结果，不能插入第二笔流水。
- 最终结算保存 `input_revision` 和 `algorithm_version`。最终化时锁定活动短事务，发现 revision 或未解决争议变化则拒绝；客户端重新执行只读 preview，不能生成或保存预览批次。
- 结算 entry 一经 finalized 不更新金额/方向；若实际执行错误，创建反向/冲正 money transfer 或将 entry 标为 void，并保留原因。
- 列表使用 `(occurred_at/updated_at, id)` keyset cursor；API 返回 `next_cursor`，不使用无限增长的 OFFSET。
- 事务内只做校验、锁行和写入，不调用汇率、Storage、通知等外部服务；设置合理 statement timeout，并记录 request/correlation ID 供诊断。

## 12. 数据生命周期与删除策略

- 活动、账本、成员、消费和转账在 App 内默认软状态变更，不提供普通客户端硬删除。归档/结算后仍可读取历史。
- 成员离开或被移除时保留 `activity_member_id`、display_name 快照和历史金额；不能级联删除消费分摊。
- 删除 Auth 用户时，用户外键多用 `SET NULL`，保留创建者/处理者的审计时间和成员显示名；`profiles` 可随 Auth 用户级联删除。拥有活动的用户删除前必须先转移 owner 或由受控后台处理。
- 邀请过期/撤销只更新状态；定时清理可删除过期且未被引用的邀请，但不得删除已接受历史。
- 物理删除活动及其子表仅限维护/迁移操作，并应先导出审计数据；V0.1 不提供 App API。
- `settlement_runs`/entries 只保存 finalize 成功后的结算历史，finalized 后保留；只读 preview 不落库，因此不存在需要清理的预览批次。
- 附件延期启用后，先删除 Storage 对象，再在短事务删除 metadata；失败时进入清理队列，不能留下可公开访问对象。
- 具体保留年限、GDPR/隐私导出和“删除我的数据”流程是待确认产品/合规决策。

## 13. V0.1 核心与延期项

### V0.1 核心

- Auth 用户与 `profiles`。
- `activities`（normal/large）、`activity_members`（V0.1 推荐账号成员）、`activity_invites`。
- `ledger_units` 和 `ledger_unit_members`，保证普通活动 root 与大型活动 subactivity 统一。
- `expenses`、`expense_payers`、`expense_splits`，支持多人付款/自定义分摊/多币种快照。
- `money_transfers`（普通转账、收款、预存、返还）和 `transfer_disputes`。
- `settlement_runs`、`settlement_entries`（仅 finalize 持久化）、RLS、最小 GRANT、上述事务 RPC。

### 延期

- `expense_attachments` + 私有 Storage、缩略图、签名 URL。
- 外部实时汇率、汇率历史表和自动刷新策略。
- Realtime 通知、推送、邮件邀请和在线 presence。
- 离线写入队列、冲突解决日志、同步 checkpoint。
- OCR、重复消费检测、导入导出、周期性消费。
- 独立审计事件表/后台管理台（V0.1 先依靠不可变流水和 created_by 字段）。
- 多活动跨账本结算、AA 算法插件、复杂税费/小费模型。

## 14. 待确认产品决策

1. **成员身份：** 推荐 V0.1 要求加入活动的成员都是 Auth 账号，并将 `activity_members.user_id` 迁移为非空、`member_kind` 固定为 `user`。是否保留/启用无账号 guest 仅是兼容方案，当前未启用，不能按 V0.1 能力开发。
2. **邀请方式：** 是一次性邀请码、可重复邀请码还是深链；邀请码有效期、最大使用次数和是否绑定邮箱需确定。
3. **角色权限：** admin 是否可以最终结算、void 消费、处理争议、修改成员角色；还是只有 owner 可以做这些操作？
4. **pending_settlement：** 发起最终结算后是否冻结新增消费/转账，还是允许继续追加并使只读 preview 失效？
5. **收款语义：** “收款”是否只是记录对方已还款，还是需要对方确认；当前统一落为 `money_transfers`，默认由录入者确认。
6. **预存池：** 预存是否由活动 owner 持有、由虚拟活动池持有，还是每位成员只记录一项“对活动余额”；当前采用虚拟活动池语义，不伪造成员。
7. **汇率来源：** 跨币种汇率由谁输入/确认、换算时点和允许精度；当前只保存写入时快照，不依赖实时 provider。
8. **结算算法：** 是否允许最少转账次数优化、如何处理四舍五入余数、预存是否先抵扣个人应付；必须固定 `algorithm_version` 后再上线最终化。preview 始终只读，只有 finalize 才写 runs/entries。
9. **争议规则：** 任意 open dispute 是否阻断全活动结算；争议解决后由谁确认原流水有效。
10. **活动生命周期：** settled 与 archived 的关系、能否重新打开、是否允许 settled 后补录冲正。
11. **隐私范围：** 活动成员是否能看所有人的真实邮箱/头像，还是只能看 `display_name` 和公开头像路径。
12. **删除与导出：** 用户注销、活动删除、账务导出和附件保留年限的产品/合规要求。

## 15. 实施前检查清单

- [ ] 确认 Supabase Postgres 版本、Data API 暴露 schema 和 UUIDv7/`pg_uuidv7` 是否可用；未确认前使用 UUIDv4 fallback。
- [ ] 将本文的状态值、字段名和 DTO 名称与 Android data/domain 层评审一次；不要把当前 `DemoData` ID 当成生产 ID。
- [ ] 先定义迁移中的 enum/check、FK、索引，再定义 RLS policy 与最小 grant；每个暴露表确认 RLS 已启用。
- [ ] 为每个 RPC 写正向、越权、重复请求、stale revision、金额合计不一致和跨活动 ID 混用测试。
- [ ] 用 `EXPLAIN`/Supabase advisors 验证活动列表、明细、结算汇总及 RLS 成员判断走索引。
- [ ] 仅在安全审查完成后创建 Supabase 项目配置；Android 配置不得包含 service role、数据库密码或签名密钥。
