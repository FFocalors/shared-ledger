# SharedLedger V0.1 API 契约（历史设计）

> 状态：`废弃`。本文保留用于追溯早期设计，不得作为 Android 联调、RPC 命名、表名或 DTO 实现依据。
>
> 当前唯一真实契约是 [BACKEND_INTEGRATION_READINESS.md](./BACKEND_INTEGRATION_READINESS.md) 与 `supabase/migrations/` 中当前 16 条 migration；实施顺序见 [ANDROID_SUPABASE_INTEGRATION_PLAN.md](./ANDROID_SUPABASE_INTEGRATION_PLAN.md)。本文中的 `create_activity_with_owner`、`join_activity_by_invite`、`create_expense_with_allocations`、`money_transfers` 等名称可能与已冻结数据库不一致。
>
> 设计边界：V0.1 只覆盖活动、参与者、分账、转账和结算的最小闭环。简单读取使用 Supabase Data API；涉及多个表的写入使用数据库函数 RPC，以保证事务和权限检查集中在数据库侧。

## 1. 调用总则

### 1.1 传输和认证

- Android 仅保存 Supabase publishable key（或兼容旧项目的 anon key）和用户 JWT。`service_role`/secret key 永不进入 APK、日志或客户端请求。
- 未登录只允许 Auth 注册/登录/刷新会话等 Auth 操作；业务 Data API 和 RPC 默认要求 `authenticated`。
- 业务接口统一使用 HTTPS。请求头由 Supabase 客户端负责设置：`apikey: <publishable-key>` 和 `Authorization: Bearer <access-token>`。
- 授权以数据库中的 `activity_members`、角色和资源关系为准，不能使用用户可自行修改的 `user_metadata` 作为权限来源。
- 所有暴露到 Data API 的表和视图必须有 RLS。视图优先 `security_invoker=true`；确需 `SECURITY DEFINER` 的函数只能放在非暴露 schema，显式校验 `auth.uid()`，固定 `search_path`，并撤销 `PUBLIC` 的 `EXECUTE`。

### 1.2 数据格式

| 项目 | 约定 |
| --- | --- |
| JSON 命名 | Kotlin DTO 使用 `camelCase`；Supabase Data API 查询、RPC 参数和响应在线上统一使用数据库的 `snake_case`，由 data 层显式映射；不要把 DB 行直接当 UI model。 |
| ID | UUID 字符串；线上字段使用 `activity_id`、`ledger_unit_id`、`member_id`、`expense_id` 等，不能使用显示名称代替。 |
| 时间 | JSON 使用 ISO-8601 UTC，例如 `2026-08-30T12:30:00Z`；数据库使用 `timestamptz`。本地展示再转换时区。 |
| 金额 | 数据库使用 `numeric(20,4)`；JSON 传字符串，例如 `"2480.00"`，避免浮点误差。金额必须大于 0，分摊和付款金额按币种分别校验。 |
| 币种 | ISO 4217 大写代码，例如 `CNY`、`EUR`；货币符号只属于展示层。多币种活动必须保存原币金额、原币种、汇率快照和折算后的活动主币金额。 |
| 枚举 | API 使用小写稳定字符串，例如 `in_progress`、`archived`；未知枚举客户端应保留兼容分支，不因新增服务端枚举崩溃。 |
| 空值 | 可选字段缺省或为 `null` 的含义必须在 DTO 中固定；列表字段没有数据返回 `[]`，不要返回 `null`。 |

### 1.3 查询、分页和并发

- 首屏列表使用稳定排序 `updated_at DESC, id DESC`。超过首屏后使用基于 `(updated_at,id)` 的 keyset 游标，不使用 offset 分页。
- 建议查询参数：`limit`（默认 20，最大 100）和 `cursor`（opaque base64url）；响应统一为 `{ "items": [], "next_cursor": null }`。
- Kotlin 写入 DTO 带 `clientOperationId`（UUID），在线上 RPC 参数中映射为 `client_operation_id`。服务端对每个业务写入表建立“调用方 + operation id”的唯一约束或幂等记录；重试应返回第一次成功的结果，而不是产生重复消费/转账。
- 活动及其聚合摘要使用 `revision`/`expected_revision`/`source_revision`；其他可变行使用 `version`/`expected_version`。服务端只在版本匹配时更新并递增对应字段；不匹配返回 `409 conflict`，客户端重新读取后让用户确认。
- Android 不直接拼接多次 insert 来完成一个业务动作。消费必须同时写入消费、付款人和分摊；结算必须同时生成结算批次和结算项。

### 1.4 错误模型

Data API 原始错误由 data 层归一化为以下模型：

```json
{
  "error": {
    "code": "validation_error",
    "message": "expense split total must equal amount",
    "field": "splits",
    "request_id": "optional-server-request-id",
    "retryable": false
  }
}
```

约定的 `code`：

| code | 含义 | Android 行为 |
| --- | --- | --- |
| `unauthenticated` | 会话缺失、过期或无效 | 刷新/重新登录 |
| `forbidden` | 已登录但不是活动成员或无相应角色 | 不重试，提示权限不足 |
| `not_found` | 资源不存在或对当前用户不可见 | 返回列表/详情空状态 |
| `validation_error` | 字段、金额、币种或业务规则不合法 | 定位表单字段 |
| `conflict` | `expected_revision`/`expected_version` 过期、重复 operation 或状态不允许 | 重新读取，重复 operation 可直接视为成功 |
| `rate_limited` | 请求频率受限 | 按 `Retry-After` 延迟重试 |
| `network_error` | 客户端未收到服务端响应 | 仅对幂等操作重试 |
| `server_error` | 服务端未知错误 | 记录 requestId，有限重试 |

## 2. API 形态分层

### 2.1 Supabase Auth（已提供能力，待客户端接入）

| 操作 | 调用形态 | 请求 | 响应/权限 |
| --- | --- | --- | --- |
| 注册 | Supabase Auth `signUp` | `email`、`password`；是否支持 magic link 由产品决定 | 返回 session 或待验证状态；无需业务表权限 |
| 登录 | `signInWithPassword`（或最终确认的登录方式） | `email`、`password` | 返回 session/JWT；业务接口从 JWT 识别 `auth.uid()` |
| 刷新会话 | `refreshSession` | refresh token 由 Auth 客户端管理 | 返回新 access token |
| 退出 | `signOut` | 当前 session | 本地清除会话；服务端敏感操作仍依赖有效 JWT |
| 当前用户 | `getUser`/`getSession` | 无业务参数 | 返回用户身份；业务 profile 另查 `profiles` |

### 2.2 Data API 简单查询和单资源更新

Data API 通过 `/rest/v1/<resource>` 访问已暴露且有 RLS 的表或安全视图。以下只允许单资源、无跨表副作用的读写；复杂写入转 RPC。

| resource | 允许的用途 | 最小权限规则 |
| --- | --- | --- |
| `profiles` | 读取当前用户资料；更新自己的昵称/头像 | 只能读写本人；活动成员展示资料应通过受保护的成员视图 |
| `activities` | 读取本人参与的活动；读取详情；更新允许编辑的活动字段 | 成员可读；owner/admin 可编辑名称、设置和状态 |
| `activity_members` | 读取活动成员列表 | 同活动成员可读；角色、状态和 `user_id` 不能由普通成员任意改写 |
| `ledger_units` | 读取活动下的根账本/子活动详情和列表 | 活动成员可读；创建、归档建议走 RPC |
| `expenses` | 按账本单查询消费详情/列表 | 具有关联账本权限的成员可读；删除仅限创建者或 owner/admin 且未结算 |
| `expense_payers`、`expense_splits` | 与消费详情一起读取 | 只能通过关联消费的成员权限读取，不单独向不相关用户暴露 |
| `money_transfers` | 查询活动转账/收款记录 | 活动成员按产品规则可读；敏感备注和争议信息不能越权返回 |
| `settlement_runs`、`settlement_entries` | 查询结算预览/已生成结算 | 活动成员可读；只有 owner/admin 能生成或最终确认 |

直接表写入若被保留，也必须在 RLS 中同时限制 `USING` 和 `WITH CHECK`，并提供 UPDATE 的 SELECT policy。禁止用 `TO authenticated` 作为唯一授权条件。

### 2.3 数据库函数 RPC：原子多表写入

RPC 通过 `POST /rest/v1/rpc/<function_name>` 调用。客户端可调用的 RPC 默认 `SECURITY INVOKER`，在函数体和相关 RLS 中校验当前用户及活动角色。`SECURITY DEFINER` 仅允许用于非暴露 schema 的内部 helper，不能作为 Android 可直接调用的 RPC；若确需使用，必须显式校验 `auth.uid()`、固定 `search_path` 并撤销 `PUBLIC EXECUTE`。所有返回值使用稳定的 DTO/视图形状，不返回内部权限信息。

| RPC | 事务内动作 | 关键权限与结果 |
| --- | --- | --- |
| `create_activity_with_owner` | 创建活动、主账本单元、当前用户 owner 成员记录 | 登录用户；返回 `activity`、`root_ledger_unit`、`membership` |
| `update_activity` | 校验 revision 后更新活动名称、主币种、多币种开关或状态 | owner/admin；返回更新后的活动和新 `revision` |
| `archive_activity` | 校验无未处理结算或按规则归档活动 | owner/admin；幂等；返回活动摘要 |
| `invite_activity_member` | 创建邀请记录或生成邀请 token 的摘要 | owner/admin；token 只返回一次，数据库存 hash/过期时间 |
| `join_activity_by_invite` | 校验邀请、创建/恢复成员记录并使邀请已使用 | 登录用户；幂等；不允许客户端直接伪造 `activity_id` 成员关系 |
| `update_activity_member` | 修改成员角色/状态或退出活动 | owner/admin 可管理他人；本人只能执行允许的退出流程 |
| `create_ledger_unit_with_members` | 创建大型活动子活动及其成员选择 | 活动 owner/admin；成员必须属于父活动；返回 unit 和成员 |
| `update_ledger_unit` | 修改名称、时间、状态、成员范围 | owner/admin；账本已有消费后限制成员变更 |
| `create_expense_with_allocations` | 创建消费，并一次写入 payer、split、汇率快照/附件元数据 | 活动/账本成员且未封存；校验分摊合计、付款合计和参与者归属；幂等 |
| `update_expense_with_allocations` | 版本校验后替换消费的 payer/split 集合 | 原创建者或 owner/admin；不可修改已锁定结算消费 |
| `void_expense` | 软删除/作废消费及关联分摊 | 原创建者或 owner/admin；保留审计语义；幂等 |
| `record_money_transfer` | 创建转账、收款、预存或退款的一笔资金流 | 付款方/收款方本人或授权 admin；金额和方向必须合法；幂等 |
| `update_transfer_status` | 按状态机将资金流确认或作废 | 相关成员或 admin；版本校验；可处理 `confirmed`/`void` |
| `open_transfer_dispute` | 创建转账争议记录并将资金流标记为 `disputed` | 相关成员；不能覆盖原始转账记录 |
| `preview_activity_settlement` | 读取活动快照，按主币种计算净额和建议结算项 | 活动成员可调用；只读、不可写；建议由安全视图/RPC 返回 |
| `finalize_activity_settlement` | 锁定活动账本快照，仅在 finalize 时创建 `finalized` run/entries | owner/admin；幂等 |
| `record_settlement_entry` | 记录某一建议结算项已支付/已收款 | 对应付款方或收款方，或 admin；版本校验；不直接改写计算结果 |

函数命名是客户端契约草案。实现时可调整 SQL 名称，但应在本文件和 Kotlin repository 中同步变更；未实现前不得在客户端假设函数存在。

## 3. 领域 API 契约

以下路径以 Supabase Data API 约定描述。示例省略通用 `apikey`、`Authorization` 和错误包装。

### 3.1 Profiles

#### `GET /rest/v1/profiles?id=eq.<user_id>&select=id,display_name,avatar_url,updated_at`

- **用途**：加载当前用户或活动成员的展示资料（成员展示优先使用安全视图）。
- **响应**：`{ "items": [{ "id": "uuid", "display_name": "张三", "avatar_url": null, "updated_at": "..." }], "next_cursor": null }`。
- **权限**：本人可读写本人；同活动成员可读最小展示字段。
- **幂等/事务**：更新昵称/头像可用 `PATCH` + `expected_version`；不影响活动账本。

#### `PATCH /rest/v1/profiles?id=eq.<user_id>`

线上请求：`{ "display_name": "张三", "avatar_url": null, "expected_version": 3 }`。只能写自己的 `id`；返回新版本资料。禁止从请求体写入角色、owner 等授权字段。

### 3.2 Activities

#### `GET /rest/v1/activities?select=...&order=updated_at.desc,id.desc`

- **用途**：首页“进行中/已归档”活动列表。
- **权限**：只返回当前用户存在 active membership 的活动；RLS 过滤不能依赖客户端传入 userId。
- **响应字段**：`id`、`name`、`kind`、`status`、`base_currency`、`multi_currency_enabled`、`participant_count`、`total_amount`、`updated_at`、`revision`。
- **分页**：按通用 keyset 游标；聚合字段建议来自 `activity_summaries` 安全视图。

#### `GET /rest/v1/activities?id=eq.<activity_id>&select=...`

返回活动详情和状态。未加入活动时统一表现为 `not_found`，避免泄露活动是否存在。

#### `POST /rest/v1/rpc/create_activity_with_owner`

请求：

```json
{
  "name": "日本旅行",
  "kind": "large",
  "base_currency": "CNY",
  "multi_currency_enabled": true,
  "client_operation_id": "1f1d8c40-3d1e-4df6-9a4e-0f9a7f43c3b5"
}
```

响应：

```json
{
  "activity": {
    "id": "activity-uuid",
    "name": "日本旅行",
    "kind": "large",
    "status": "in_progress",
    "base_currency": "CNY",
    "multi_currency_enabled": true,
    "revision": 1
  },
  "root_ledger_unit": { "id": "ledger-unit-uuid", "kind": "root" },
  "membership": { "id": "member-uuid", "role": "owner", "status": "active" }
}
```

登录用户调用；事务内完成三类记录，operation 重试返回同一结果。

#### `POST /rest/v1/rpc/update_activity` 与 `POST /rest/v1/rpc/archive_activity`

线上请求至少包含 `activity_id`、`expected_revision`、`client_operation_id`。owner/admin 才能修改；归档必须是幂等状态转换，并保留 `archived_at`。结算完成后是否允许重新打开是待确认产品决策。

### 3.3 Members / Invites

#### `GET /rest/v1/activity_members?activity_id=eq.<activity_id>&select=...`

返回成员最小资料：`id`（activity member id）、`user_id`、`display_name`、`avatar_url`、`role`、`status`。同活动 active member 可读；客户端后续所有 payer/split/from/to 均使用 `member_id`，不使用姓名。

#### `POST /rest/v1/rpc/invite_activity_member`

线上请求：`{ "activity_id": "...", "email": "...", "role": "member", "client_operation_id": "..." }`。按账号邀请；不能仅凭 display name 创建匿名成员。响应只返回邀请 id、过期时间和一次性明文 invite code（若采用链接邀请）；数据库只存 token hash。owner/admin 调用，幂等键防止重复邀请。

#### `POST /rest/v1/rpc/join_activity_by_invite`

线上请求：`{ "invite_code": "...", "client_operation_id": "..." }`。登录用户调用，服务端校验未过期、未撤销和活动状态后创建 active membership；返回活动摘要和自己的 `member_id`。禁止通过 Data API 直接插入 membership。

#### `POST /rest/v1/rpc/update_activity_member`

线上请求：`activity_id`、`member_id`、`status`/`role`、`expected_version`、`client_operation_id`。owner/admin 管理他人；普通成员只能走“退出”受限流程。成员已经出现在消费或结算中时，建议改为 `left`，不要物理删除。

### 3.4 Ledger Units（根账本和大型活动子活动）

#### `GET /rest/v1/ledger_units?activity_id=eq.<activity_id>&order=created_at.asc,id.asc`

返回 `id`、`activity_id`、`parent_unit_id`、`kind`（`root`/`subactivity`）、`name`、`status`、`member_count`、`total_amount`、`updated_at`、`version`。活动成员可读；聚合字段来自安全视图。

#### `POST /rest/v1/rpc/create_ledger_unit_with_members`

请求：

```json
{
  "activity_id": "activity-uuid",
  "name": "门票",
  "member_ids": ["member-a", "member-b"],
  "client_operation_id": "uuid"
}
```

响应：`{ "ledger_unit": { "id": "...", "kind": "subactivity", "name": "门票", "version": 1 }, "members": [...] }`。owner/admin 调用，事务内校验所有 `member_id` 属于父活动。

#### `POST /rest/v1/rpc/update_ledger_unit` / `POST /rest/v1/rpc/archive_ledger_unit`

用于名称、成员范围和状态变更；均要求 `expected_version`。已有消费的子活动不能无提示地移除成员；归档只允许在未锁定结算时执行。

### 3.5 Expenses + Payers + Splits

#### `GET /rest/v1/expenses?ledger_unit_id=eq.<ledger_unit_id>&order=occurred_at.desc,id.desc`

返回消费摘要：`id`、`ledger_unit_id`、`title`、`amount`、`currency_code`、`base_amount`、`occurred_at`、`created_by_user_id`、`status`、`version`。详情按 `expense_id` 查询时同时返回 `payers`、`splits`、`attachments`。只能看到关联账本权限范围内的数据。

#### `POST /rest/v1/rpc/create_expense_with_allocations`

请求：

```json
{
  "ledger_unit_id": "ledger-unit-uuid",
  "title": "早餐",
  "amount": "320.00",
  "currency_code": "CNY",
  "occurred_at": "2026-08-30T03:42:00Z",
  "note": "含饮料",
  "payers": [
    { "member_id": "member-a", "amount": "320.00" }
  ],
  "splits": [
    { "member_id": "member-a", "amount": "160.00" },
    { "member_id": "member-b", "amount": "160.00" }
  ],
  "attachment_ids": [],
  "client_operation_id": "uuid"
}
```

响应：

```json
{
  "expense": {
    "id": "expense-uuid",
    "ledger_unit_id": "ledger-unit-uuid",
    "amount": "320.00",
    "currency_code": "CNY",
    "status": "active",
    "version": 1
  },
  "payers": [{ "member_id": "member-a", "amount": "320.00" }],
  "splits": [
    { "member_id": "member-a", "amount": "160.00" },
    { "member_id": "member-b", "amount": "160.00" }
  ]
}
```

调用者必须是活动/账本成员；服务端校验 `sum(payers) = amount`、`sum(splits) = amount`、所有成员属于该账本，以及多币种汇率规则。三组表写入必须同一事务；重复 `client_operation_id` 返回原消费。

#### `POST /rest/v1/rpc/update_expense_with_allocations` / `POST /rest/v1/rpc/void_expense`

修改请求包含完整的 payer/split 集合和 `expected_version`，服务端以事务方式替换子项。作废采用软删除并保留审计信息；已 finalized settlement 引用的消费默认不可编辑。

### 3.6 Transfers / Prepayments / Disputes

统一资金流表建议使用 `money_transfers`，通过 `transfer_type` 区分 `transfer`、`prepayment`、`prepayment_refund`。`receive` 只是 UI 操作方向，不是资金流类型。预存余额和待结算金额由安全视图计算，不在客户端自行累加。

#### `GET /rest/v1/money_transfers?activity_id=eq.<activity_id>&order=occurred_at.desc,id.desc`

返回 `id`、`activity_id`、可选 `ledger_unit_id`、`from_member_id`、`to_member_id`、`amount`、`currency_code`、`transfer_type`、`status`、`occurred_at`、`created_by_user_id`、`version`。活动成员可读的字段范围由产品确认；至少不能把不相关活动的记录暴露给用户。

#### `POST /rest/v1/rpc/record_money_transfer`

请求：

```json
{
  "activity_id": "activity-uuid",
  "ledger_unit_id": null,
  "from_member_id": "member-a",
  "to_member_id": "member-b",
  "amount": "200.00",
  "currency_code": "CNY",
  "transfer_type": "transfer",
  "occurred_at": "2026-08-30T04:00:00Z",
  "note": null,
  "client_operation_id": "uuid"
}
```

响应：`{ "transfer": { "id": "...", "status": "pending", "version": 1 }, "balances": [...] }`。相关成员或授权 admin 调用；服务端校验双方属于活动、金额为正、作用域一致。转账、收款、预存和退款不可通过前端修改余额字段。

#### `POST /rest/v1/rpc/update_transfer_status`

线上请求包含 `transfer_id`、`status`（`confirmed`/`void`）、`expected_version` 和 `client_operation_id`。`open_transfer_dispute` 会把资金流状态设为 `disputed`；争议解决后根据结果回到 `confirmed` 或 `void`。转账何时从 pending 变为 confirmed，以及“收款”是否需要对方确认，是待确认决策。

#### `POST /rest/v1/rpc/open_transfer_dispute`

请求：`{ "transfer_id": "...", "reason": "金额不符", "attachment_ids": [], "client_operation_id": "..." }`。只允许相关成员；以独立 dispute 记录保存，并将原始资金流状态设为 `disputed`，不覆盖金额和方向。争议解决后根据结果通过状态更新回到 `confirmed` 或 `void`；争议解决流程不属于 V0.1 自动化范围。

#### `GET /rest/v1/activity_prepayment_summary?activity_id=eq.<activity_id>`

只读安全视图，返回每个 member 的 `paid_in`、`refunded`、`applied_amount`、`remaining_amount`，由数据库按币种/汇率规则计算。大型活动顶部“预存”卡片从此摘要读取。

### 3.7 Settlement preview / finalize / record

#### `POST /rest/v1/rpc/preview_activity_settlement`

线上请求：`{ "activity_id": "...", "scope": "activity", "expected_revision": 12 }`。`expected_revision` 可选，仅用于拒绝陈旧读取，不产生幂等副作用。活动成员可调用。响应示例：

```json
{
  "activity_id": "activity-uuid",
  "base_currency": "CNY",
  "total_amount": "5980.00",
  "member_balances": [
    { "member_id": "member-a", "net_amount": "420.00", "direction": "receive" },
    { "member_id": "member-b", "net_amount": "-420.00", "direction": "pay" }
  ],
  "suggestions": [
    { "from_member_id": "member-b", "to_member_id": "member-a", "amount": "420.00", "currency_code": "CNY" }
  ],
  "source_revision": 12
}
```

该接口只读且不落库；`source_revision` 用来提示预览期间数据是否变化。算法、舍入策略和多币种结算顺序必须在 schema 设计文档中固定。

#### `POST /rest/v1/rpc/finalize_activity_settlement`

线上请求：`{ "activity_id": "...", "source_revision": 12, "client_operation_id": "uuid" }`。owner/admin 调用。事务内锁定账本快照并写入 `settlement_runs` + `settlement_entries`；若活动 revision 已变化返回 `409 conflict`，不可静默使用旧预览。重复 operation 返回同一个 settlement run。

响应：`{ "settlement_run": { "id": "...", "status": "finalized", "input_revision": 12 }, "entries": [...] }`。

#### `POST /rest/v1/rpc/record_settlement_entry`

线上请求：`{ "settlement_entry_id": "...", "status": "recorded", "expected_version": 1, "client_operation_id": "uuid" }`。对应付款方/收款方或 admin 调用；只改变执行状态，不重算 entry 金额。返回新 entry 和结算批次完成度。

### 3.8 Attachments

附件 V0.1 只定义契约，具体存储延期到 Storage 接入阶段：

1. 客户端先请求受保护的 upload 预签名/路径（未来可用 Edge Function 或受控 RPC）。
2. 客户端上传到私有 Storage bucket；对象路径必须包含 `activity_id/ledger_unit_id/expense_id`，不能由用户跨活动指定。
3. 上传成功后写 `expense_attachments` 元数据，并在 `create_expense_with_allocations` 中以 `attachment_ids` 原子关联。
4. 查看附件时按成员权限返回短期 signed URL；不返回永久公开 URL。

建议的未来接口：

| 操作 | 形态 | 约束 |
| --- | --- | --- |
| 创建上传会话 | `POST /rest/v1/rpc/create_attachment_upload` | 校验活动/消费权限、MIME、大小；返回短期 path/token |
| 记录元数据 | `POST /rest/v1/rpc/attach_expense_file` | 校验对象 path 所属消费；幂等 |
| 获取下载地址 | `POST /rest/v1/rpc/create_attachment_download_url` | 返回短期 signed URL；按关联消费 RLS 授权 |
| 删除附件 | `POST /rest/v1/rpc/delete_attachment` | 软删除元数据并删除/回收对象；V0.1 可延期 |

## 4. 页面/路由到 API 映射

当前正式页面为 9 个；`LargeActivitySmokeTestScreen` 是测试展示页，不作为业务 API 页面。
本节 route 名称和 UI callback 缺口中的字段名属于 Android/Kotlin 层，因此保留 `camelCase`；真正发送到 Supabase 的请求和响应字段仍必须按前文使用 `snake_case`。

| 页面 / route | 首次加载 | 用户动作对应 API | 当前原型接入缺口 |
| --- | --- | --- | --- |
| 首页 `home` | `GET activities`（进行中/已归档）+ 活动摘要安全视图 | 创建进入 `create_activity_with_owner`；加入活动进入 `join_activity_by_invite` | `DemoData` 静态；卡片没有稳定 activityId；`onJoinActivity` 尚为空 |
| 创建活动 `create-activity` | 可读取货币配置（若需要） | `create_activity_with_owner` | `onCreate` 仅回调 `ActivityKind`；缺少 name、baseCurrency、multiCurrencyEnabled、clientOperationId |
| 普通活动 `normal-activity/{activityId}` | 活动详情、根账本、成员、消费摘要、资金流摘要 | 新增消费、转账、收款分别进入 expense/transfer RPC | 页面数据为静态展示；路由只传 id，回调不携带操作结果/错误 |
| 大型活动 `large-activity/{activityId}` | 活动详情、子活动列表、预存摘要、总体结算预览 | 创建子活动、预存/转账/收款、最终结算 | `onShowPrepayment` 和部分快捷动作无数据契约；预存 sheet 仍是本地 UI 状态 |
| 创建子活动 `create-sub-activity/{activityId}` | 父活动和可选成员列表 | `create_ledger_unit_with_members` | `onCreate` 无 payload；父活动名硬编码；成员选择未回调 |
| 账本单元 `ledger-unit/{ledgerUnitId}` | 子活动详情、成员、消费列表、余额摘要 | 新增消费、转账、收款对应 RPC | 当前 transfer 导航把 `ledgerUnitId` 放进名为 `activityId` 的 route 参数；接入前要明确 activity scope 和 ledger scope |
| 新增消费 `new-expense/{ledgerUnitId}` | 账本成员、默认币种、可选附件配置 | `create_expense_with_allocations` | `onSave` 无 payload；名称、金额、币种、payer、split、备注、时间和 attachmentIds 均未上送 |
| 转账/收款 `transfer/{activityId}?mode={mode}` | 活动成员、债务/预存摘要 | `record_money_transfer`，必要时随后 `update_transfer_status` | `onConfirm` 无 payload；当前选中成员、金额、mode 未上送；若从子活动进入需改为显式 `activityId + ledgerUnitId` |
| 最终结算 `final-settlement/{activityId}` | `preview_activity_settlement` | `finalize_activity_settlement`；逐项 `record_settlement_entry` | 页面按钮是本地 recorded 状态；无 activityId 数据加载、source_revision、确认结果和错误处理 |

## 5. Android 接入前置清单

在添加 Supabase SDK 或 repository 前，先完成以下契约对齐：

1. 给创建活动、创建子活动、新增消费、转账/收款、最终结算页面定义 typed input/output DTO；不要继续使用无参数 `onSave`/`onConfirm` 回调。
2. 为 UI participant model 增加 `memberId`；姓名只能用于展示，不能作为 payer/split/from/to 外键。
3. 将 `DemoRouteIds` 与真实 UUID 解耦；所有详情页面从 route 获取 typed id，再由 ViewModel 加载数据。
4. 修正 transfer route 的 scope：普通活动使用 `activityId`，子活动操作同时传 `activityId` 和 `ledgerUnitId`，不要把 ledgerUnitId 冒充 activityId。
5. 为每个页面增加 loading、empty、error、retry、提交中和重复点击保护；提交结果只能在 RPC 成功后返回上一页。
6. 为金额输入实现字符串到 `BigDecimal` 的边界校验，提交前检查币种、正数、精度和 payer/split 合计；UI 的本地分配提示不能代替服务端校验。
7. repository 层区分简单查询、RPC 写入和 Auth；不要把 `service_role`、数据库直连密码或 Storage 管理 token 放入 Android。
8. 对消费、转账、创建活动/子活动、最终结算保存 `clientOperationId`，在旋转屏幕、断网重试和进程恢复时复用同一 id。
9. 先实现 DTO/mapper 和 fake repository，再接 Supabase；用契约测试覆盖 401、403、404、409、重复写入和金额合计错误。

## 6. 暂不纳入 V0.1

- 不在本契约中执行任何 SQL、创建 Supabase 项目或生成迁移文件。
- 不安装 Supabase Android SDK，不改变当前 Gradle/AGP/Kotlin/Compose 配置。
- 不实现离线优先同步、冲突合并、后台队列和多设备事件溯源。
- Realtime 订阅（活动成员、消费、转账和结算变化）延期；首版先用显式刷新/成功后 invalidate。后续启用时仍须按 RLS 和最小频道范围设计。
- Storage 附件上传、图片压缩、病毒扫描和 signed URL 延期。
- Edge Functions 仅在需要第三方 webhook、邀请邮件、复杂文件处理或不能安全放在客户端的编排时引入；不能用 Edge Function 绕过 RLS。
- 默认采用账号成员；guest 成员模型仅兼容预留、尚未启用。跨活动共享成员、账本间转移、自动银行流水导入、复杂 AA 算法配置和争议仲裁后台不属于 V0.1。

## 7. 待确认决策

1. 参与活动的人是否必须拥有 Auth 账号；推荐 V0.1 只支持账号成员。guest 成员模型仅兼容预留/未启用，若未来开启需增加 `guest_members`/claim 流程，不能把自由文本姓名塞进 payer/split。
2. 邀请方式是链接 token、邀请码、邮箱邀请还是组合；token 过期时间和是否允许重复使用需固定。
3. “预存”是活动级资金池还是个人对活动的资金流；当前契约按 `money_transfers.transfer_type=prepayment` 建模。
4. 收款是否需要对方确认；转账和收款的状态机需由产品确定。
5. 多币种活动采用创建时汇率、消费发生时汇率还是手动汇率；汇率来源和舍入精度需固定。
6. 普通活动是否总是一个 root ledger unit；当前统一用 root unit，避免两套消费模型。
7. 结算最终确认后能否新增/修改消费；建议 finalized 后只允许通过新批次或显式 reopen，并保留旧批次。
8. 成员能看到全活动的金额、转账备注和争议信息，还是只看到与自己相关的记录。
9. 删除策略是统一软删除还是只允许作废；账本和结算历史建议不可物理删除。
10. 是否需要服务端推送通知、审计日志和管理后台；这些会影响 Realtime、Edge Functions 和额外表设计。
