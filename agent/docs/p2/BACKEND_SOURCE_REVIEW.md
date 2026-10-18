# P2 后端源事实与只读接口审查

日期：2026-10-11（Asia/Shanghai）  
状态：只读设计审查；没有实现 P2 backend、连接真实 Supabase、运行数据库/容器或更改合约。

## 审查基线

| Checkout | Branch | HEAD | 审查开始时状态 |
|---|---|---|---|
| `D:\project\Android\shared-ledger`（业务事实只读） | `main` | `3f938ee6114b763e6cd3dbd10792a78c691eb526` | `git status --short` 为空 |
| `D:\project\Android\shared-ledger-agent`（P2 文档唯一写入目标） | `agent` | `1a80a0f29e1ea432a60b95e7437af23d51182938` | 有既存 P1/T1 修改和未跟踪文件；下列清单是在本审查文档写入前记录的基线 |

Agent 基线中的既存修改：`agent/README.md`、`agent/docs/dev-status.md`、`agent/docs/shared-ledger-agent-development-guide-v0.4.html`。既存未跟踪内容包括 `agent/.dockerignore`、`.env.example`、`.gitignore`、`app/`、`contracts/`、`dataset_contracts/`、`deploy/`、`docs/p1/`、`docs/p2/`、`docs/t1/`、`evaluation/`、`migrations/`、`tests/`、`pyproject.toml`、`requirements-contracts.txt`、`toolchain-contracts.json`、`uv.lock`。这些 P1/T1 和共享文档/目录不是本审查的编辑目标。

在 main 与 Agent checkout 内递归查找，没有发现 `AGENTS.md`。本审查只写入本文件；没有执行 checkout、reset、clean、stash、commit、push，也没有写 main、SQL、业务代码或远端数据。

## 已读取材料与哈希

任务附件完整读取：`C:\Users\zhy20\.codex\attachments\b185c6ff-4b75-49b1-89ac-0ba86fb21892\已粘贴的文本.txt`，SHA-256 `73CEDFE34E928E84153D8826D8DE2F425AE0CD893D884B0FF28A3BB4668234F4`。Agent 内重复的任务说明 `agent/docs/p2/TASK-P2-READONLY.md` 也已读取。

| Main checkout 已读源 | SHA-256 |
|---|---|
| `docs/backend/BUSINESS_LOGIC.md` | `91C5907CCDA95C118BD4B4B89A7C7F5B012E73664076CF01EFD6DE18291B25D9` |
| `docs/backend/BACKEND_INTEGRATION_READINESS.md` | `12EF19D0A0B9B8370CD24259CAFB41F231997CBFAABD3E875B8AFE1E9F7F2D9F` |
| `supabase/migrations/20260830100429_foundation_rls.sql` | `2B92E78D3D7B83F5DBB3A360560F4B17898047277A15B348AD2D5C83E61FAA49` |
| `supabase/migrations/20260830115418_expense_core_rls.sql` | `11D9D3DC363F45CF0A149AE4B3157F6377BD4BB2CFD9C2702D4185592A83535E` |
| `supabase/migrations/20260905151820_expense_deleted_read_restore.sql` | `0E3D72FC29C10DE00D14EFB1D6A53048A1290CC5C4AB9AA332B571D6C8913A36` |
| `supabase/migrations/20260830191659_backend_debt_projection.sql` | `58268AC227B17D5484940189218EE3AA88BE8A827B79E432D91D90B35E919959` |
| `supabase/migrations/20260831034645_backend_settlement_transfer.sql` | `891252D21DE940979E9A33BC9BD57B67528823022BDA0117472A1B8D8D6ABF97` |
| `supabase/migrations/20260831055425_backend_prepayment.sql` | `6496A004E6CAA032D52634C7E5E80251A3D01AE63D892A3C6EA8D285D5780C0C` |
| `supabase/migrations/20260831160108_backend_final_settlement_archive.sql` | `97B0E0A5412A435E6BB976E7163FCECDEC77B9A1AF21A0F4433CD2D40BBA82B1` |
| `supabase/migrations/20260919164707_multi_currency_settlement.sql` | `0BBD478A18ADBEDB645B5E905C07AF76433FA42A532642126A4778EBAF1C07E8` |
| `supabase/migrations/20260920120259_fix_multi_currency_allocation_invariants.sql` | `EA962F18B93E3E36A84FA5817AD3240AFF9C7D86C069DF7FEA3B4918F9D76FE0` |
| `supabase/migrations/20260921051720_targeted_expense_repayment_contract.sql` | `D7D198CE22395E512D4049A92C3AF22F728914D8DA8B36E52F509A404BE4BE34` |
| `supabase/migrations/20260923022250_business_logic_finalization.sql` | `4E000B18EC5A66E09A77838B26B854D21C731E4B72A712F2BB160FD314C20B28` |
| `supabase/migrations/20261006142507_sub_activity_participant_scopes.sql` | `77F11F989A044ABAE93D29B921C878C2FB1357E18FD506769BA629351BC877ED` |
| `app/src/main/java/com/ffocalors/sharedledger/data/activity/ActivityRepository.kt` | `D6C3C989539A596E67809AD7B1627186AA86E394DE08CA32609652C6814431C0` |
| `app/src/main/java/com/ffocalors/sharedledger/data/activity/ActivityModels.kt` | `EE4F81C157D100E0137A1C58E3A20C22CB599032D2ADF6D3540073DC8C23E6AF` |
| `app/src/main/java/com/ffocalors/sharedledger/data/expense/ExpenseRepository.kt` | `433A477889C381E8B3EB8699213F8E0AF73102F9ADA4C86BC095E771ECEDDAAF` |
| `app/src/main/java/com/ffocalors/sharedledger/data/expense/ExpenseDtos.kt` | `5E5068F45995AC66AF1680C168EA4BC8986AB6C6F65603C37E1088246DF3EF93` |
| `app/src/main/java/com/ffocalors/sharedledger/data/transfer/TransferRepository.kt` | `EA0029A9750C6AE5D36375DC814DA605ACFB3118EE2D689AF41A54B5E8D02631` |
| `app/src/main/java/com/ffocalors/sharedledger/data/transfer/TransferDtos.kt` | `A5763EBB6772BF4E77B4303D6E50ACC43A484DFFFE1A4DD46C621C4C257DB604` |
| `app/src/main/java/com/ffocalors/sharedledger/data/financial/FinancialRemoteDataSource.kt` | `AA201E29CCC01AA7BAEBBDADE245DAAB8817A8C8CD95D9A3F00C409BE615597B` |

| Agent checkout 已读源 | SHA-256 |
|---|---|
| `agent/docs/shared-ledger-agent-development-guide-v0.4.html` | `DD43F57450AA13153BEA9CEB8EAA38EF7B51D3F46E38777470F61D4F9C7A14C8` |
| `agent/docs/dev-status.md` | `E89B13CF9C9C9C62A1A79AC70DBDCE376309459B4533A2CD4A7B6AB9C4C9C26E` |
| `agent/docs/p1/FINAL_REVIEW.md` | `24F13850138523796CA57966C02C02F7B418FA713800E5009E4AA5D38F3A06BC` |
| `agent/docs/t1/README.md` | `FE0C7C4EB3CE5DAD8B485FEAF370B7CD4B4A71BE94846C488D13758E553CE991` |
| `agent/docs/t1/COVERAGE-T1.md` | `46B62B116CE21702FEA3F30B8197AB568A7583D287BB70287DDFDC769FB4905A` |
| `agent/docs/t1/MODEL_PREPARATION-T1-v1.md` | `3E0084942CB5662687C2A6ED8CC5E1E9E938E2D88FF1542FAB76563281195842` |
| `agent/docs/t1/BUSINESS_ACCEPTANCE.md` | `572D00543448AE61DFB600D88E0175AF8DA9AF9E07EE8FD459DEC29D9110593D` |
| `agent/docs/p2/TASK-P2-READONLY.md` | `A98D2D1C3A900575B8152BE88A52D534B3D274CA80FDCDE327C620E4A86895AB` |
| `agent/app/ports.py` | `C71A78FD4E42BE21F1654B174E5764720C8EE5B4F1F3DAB051293C57107496AC` |
| `agent/app/backend.py` | `0D76021508A3B976B3755E3B94712E66D9DA7C0742A717CA6946522A2E06ABDE` |
| `agent/app/model_provider.py` | `7C29229B6508796297439594E82E097D6E89912685CD862ADF6B105A6505C042` |
| `agent/app/runtime.py` | `DC370CF61E8C91F950DA3A414F95BD638EE54869936AD9E542F1A594D920DC1D` |
| `agent/app/harness.py` | `E334275B89F9A29A4F3D4B88DB56C734BF6BBEE80E5E5A933CE12D763CD6E2F3` |
| `agent/app/gateway.py` | `903E441B9220DF5DF0558F9EF06802A7EBDA260D3D634A742C2713E6C02A28C3` |
| `agent/app/settings.py` | `84778D4A4098AC6E4D464237113F5550D332BD483E1DAA6EA27B7DC50B06B839` |
| `agent/app/contracts.py` | `9FD214D9D8EB43C6F5B03B1D7E95B2BEF274DBF9E8BE495F536F495B48A5BF2D` |
| `agent/app/components.py` | `E89AF3921F85F930C0B9D56A17B87CF354E1EBDCAC292F68DCB0111819BB8E3F` |
| `agent/app/api.py` | `D31FEA0B3093F876503168C076B3ABAD52F2F3CCA27AF726766027803ED10635` |
| `agent/app/auth.py` | `DB0C88BE1BE15222C43B936FA5556175916C273C8262ED081AA133C593CEC712` |

## Main 当前只读事实：授权、成员与子账本范围

Activity 是财务边界。RLS 中 `activities`、`activity_members`、`ledger_units`、`participants`、`participant_claims` 及其关联表按已登录用户的 Activity membership 读；迁移显式授予 `authenticated` SELECT。`expenses`、`payments`、`splits` 也有 `authenticated` SELECT，但各自策略使用 `private.can_read_expense`。当前 helper 为 `STABLE SECURITY DEFINER`，只允许登录用户读取非删除 Activity、非删除 Ledger Unit 下，且其仍是该 Activity 成员的 Expense；它没有执行子账本 participant scope。

`participant_claims` 只表示登录用户与某个 Participant 的身份关联，不构成 Activity 访问授权。授权判断要依赖经 Auth 验证的 `auth.uid()` 和当前 `activity_members`；不能用模型给出的 UUID、ParticipantRef 或 claim 自行授权。为得到“我”对应的 participant，若确需读取 claims，应把查询限制到当前已验证用户，并只取必要的 Activity/participant 字段。

大 Activity 的子账本 participant scope 是独立、Activity-wide 的数据约束。新配置子账本由 `ledger_units.participant_scope_configured=true` 和 `sub_activity_participants` 的显式映射表达；payer 与每个 split bearer 都必须属于该集合。`participant_scope_configured=false` 仅表示旧子账本未配置历史范围；配置为 true 但映射为空或不一致时必须 fail closed，不能猜测或补造历史选择。普通 Activity 不启用子账本预存功能。

RLS 仍以 Activity membership 开放整组 Activity 财务行；它不是按 child unit 的 participant scope 做行级过滤。因此，后端必须把已授权 Activity 与 `expense.ledger_unit_id` 连接起来，查找该子账本状态，并在投影 Expense 前自行核对 payer/splits 与 child participant scope。对于配置子账本中缺少 participant 映射、payer/split 越界、Expense 与 Unit/Activity 关系不一致、删除状态冲突的记录，应拒绝该范围的投影并产出脱敏错误，不能静默忽略违规行后回答金额问题。

以下固定 GET 表候选具有对应的 RLS/显式 SELECT 基础，且足以支撑保守 v1 读数；实现时只允许这些表名与显式字段投影，所有 Activity/Expense/Participant/Unit 过滤值必须来自服务端绑定：

| 固定表名 | 只读用途 | 关键过滤/限制 |
|---|---|---|
| `activities` | 活动名、类型、币种、归档/删除状态、财务版本 | 仅当前用户可读的 Activity；显式排除逻辑删除行；不要读 profiles |
| `activity_members` | 验证当前用户的 Activity membership | `user_id` 必须取已验证 `auth.uid()`；只选 `activity_id`，不枚举成员身份 |
| `ledger_units` | root/child 归属、删除标记、`participant_scope_configured` | 必须绑定到 Activity；不把模型输入当 unit id |
| `participants` | Activity 内的 participant refs/显示名与有效状态 | 只限服务端已绑定 Activity；避免读取无关用户身份 |
| `sub_activity_participants` | 配置 child 的显式 participant scope | 只限已绑定 Activity 和有效 child；不从 UI/模型推测 |
| `expenses` | Expense 的正金额候选、日期、锁定/版本、原始币种与链接退款标记 | 只限已绑定 Activity 的有效 Unit；仅向 v1 投影正金额 |
| `payments` | 必要时内部区分 payer 及付款金额 | 由服务端 Expense IDs 精确限制；不能把该角色压成普通 participant ref |
| `splits` | 必要时内部区分承担人及分摊金额 | 由服务端 Expense IDs 精确限制；逐项检查 child scope |

`participant_claims` 是可选的受限内部读：若 P2 需要确定当前用户的 Participant，只允许按 `auth.uid()` 过滤并只选择必要字段；它不属于将 claims 列表交给模型的许可。禁止 GET `profiles`、原始 `expense_debts`/`bilateral_debts`、余额/状态视图、transfers/allocations、预存表及任意服务端可达对象。读债务时必须调用明确 RPC，不能回退到旧的 base-only `bilateral_debts` 行。

当前 `activity_financial_status` 和 `participant_financial_status` 视图重定义为 `security_invoker=true`，且 authenticated SELECT；但活动状态视图含预存/完成信息，不在本 v1 allowlist 中。由于没有连接现网或读取项目 Data API schema 配置，本审查确认的是仓库里的 grants/RLS/函数定义；部署项目是否将 `public` 暴露给 Data API 仍须由 owner 在安全可用的 runner 中核实。

## 固定只读 RPC 候选

**v1 允许的唯一 RPC：**

```http
GET /rest/v1/rpc/list_settlement_options?p_activity_id=<server-resolved-activity-uuid>
Authorization: Bearer <this-turn-validated-user-access-token>
apikey: <project-publishable/anon-key>
```

源定义先见 `20260919164707_multi_currency_settlement.sql`，后由 `20260920120259_fix_multi_currency_allocation_invariants.sql` 更新。精确签名为 `public.list_settlement_options(p_activity_id uuid)`，`RETURNS TABLE(debtor_participant_id uuid, creditor_participant_id uuid, currency character(3), original_amount numeric(20,4), base_amount numeric(20,1), base_total numeric(20,1), financial_version bigint)`；当前定义为 `STABLE SECURITY INVOKER`、固定空 `search_path`，函数体显式校验 `activity_members.user_id = auth.uid()`，仅返回正 original-amount 的方向/币种债务。ACL 从 `PUBLIC`/`anon` 撤权，授予 `authenticated` EXECUTE。Android `TransferRepository` 已使用该 RPC。

该 RPC 是服务端计算结果的读取源。v1 `DebtFact` 只可投影其原始 `amount + currency + debtor/creditor`；`base_amount`、`base_total`、`financial_version` 可留在内部可信 DTO/ModelPrompt metadata，不能冒充 canonical v1 字段。participant 过滤只可用服务端已解析 Participant ID。不得用模型自报 UUID 构造参数。

以下函数即使在 PostgreSQL 标记为只读，也不在此 v1 RPC allowlist：

* `public.get_expense_repayment_progress(p_activity_id uuid, p_expense_id uuid)` 返回债务/已还款/预存抵扣/余额和 `financial_version`，其 `remaining_*` 直接扣除 prepayment；ACL 是仅 `authenticated` EXECUTE，函数为 `STABLE SECURITY INVOKER`，但返回值不能安全映射到当前 v1 `read.debts` 或 `read.expenses`。不得把此函数的剩余值作为普通债务返回，也不得把 prepayment amount 藏进 v1 结果。
* `preview_prepayment` 是预览语义，且不属于只读事实读取；所有 preview/settlement/write/admin/service-role RPC 均排除。

PostgREST 的 GET/HEAD 表查询使用只读事务；RPC 还要求函数具有 `STABLE` 或 `IMMUTABLE` volatility 才能用 GET/HEAD 只读访问。上线实现应再按所用 Supabase/PostgREST 版本核验官方文档与当前 ACL。只读事务不代替 RPC 白名单、RLS、grant 或输入绑定。

## 当前 frozen v1 可表达范围与缺口

`agent/app/contracts.py` 当前只注册 `read.activities`、`read.expenses`、`read.debts`。没有 prepayment operation。

| v1 类型 | 当前能表达 | 不能无损表达的事实 |
|---|---|---|
| `ActivityFact` | ref、活动名、normal/large、base currency、active/archived/deleted、观察时间和 `context_version` | 完成状态/财务状态、Activity `financial_version`、child roster 与 participant scope |
| `ExpenseFact` | Expense ref、标题、**正** original amount/currency、时间、participant_refs、locked、expense_version、观察时间/context version | 负数退款/退款链接；payer 与 split bearer 角色、各自金额、base/FX；还款/余额/预存；来源 `financial_version` |
| `DebtFact` | debtor/creditor refs、正 amount/currency、观察时间/context version | base amount/total、settled/remaining/prepayment breakdown、source `financial_version` |
| `ToolReadResult` / `ModelReadResult` | operation、时间、context version、simulation、body | 来源标识、financial version、分页 continuation、结果是否完整 |

Expense/Split/Payment Android DTO 具备 payer/split 金额、base/FX 及退款关联信息；Settlement DTO 与上述 debt RPC 具备 base 总计与 financial version。模型 contract 比现有业务事实更窄。结果 list/body 和 `ModelContext.read_results` 也有固定 16 条上限且没有完整性标记；若查询有更多行，不能静默截断后回答“全部”。

所以安全 v1 建议限定为：列活动；列正金额 Expense 的基础事实（不回答退款、payer/split 金额或还款余额）；列服务器债务 RPC 给出的方向、原始金额和币种。预存余额/使用、预存抵扣后的剩余金额、退款净额、还款进度、完整 payer/split 账务事实、Activity 财务完成状态均应明确作为当前 v1 不支持项。尤其不能在 `read.debts` 中塞入预存，也不能把数据库基线不存在当成“没有预存”。

不改 frozen contracts/registry/OpenAPI 的内部补充空间仅限经 runtime owner 接受的可信 `P2 DTO` 与 `ModelPrompt` metadata，例如来源 `backend`、`financial_version`、查询完整性/观测时间。分页在单次 backend read 调用中完成，不保留 durable continuation；不允许模型提交任意 cursor、UUID 或路径。如果完整结果仍无法符合 v1 16 条上限，应明确拒绝完整枚举并报告 scope 限制，不能编造或漏报。新 semantic/operation/schema 需另由 root/T1 审批；本审查不修改合约，也不创建合约版本差异文件。

建议的具体内部 DTO（仅设计，不在此阶段新增代码；类型名可由 runtime owner 调整）：

```text
VerifiedReadGrant (one Turn, memory-only)
  turn_id: UUID
  user_id: UUID                 # 由 AuthVerifier 确认，与 request owner 相同
  access_token: Secret[str]     # repr/serialization 隐藏；不得持久化
  expires_at: UTC datetime
  refs: TurnBoundRefs           # 只能由 runtime 的 server-held state 构造

TurnBoundRefs
  activities: opaque ActivityRef -> BoundActivity(activity_id)
  expenses: opaque ExpenseRef -> BoundExpense(expense_id, activity_id, ledger_unit_id)
  participants: opaque ParticipantRef -> BoundParticipant(participant_id, activity_id)
  ledger_units: opaque LedgerUnitRef -> BoundLedgerUnit(ledger_unit_id, activity_id)

P2BackendReadResult (backend-internal, not a new model operation)
  facts: list[P2ActivityFact | P2ExpenseFact | P2DebtFact]
  source: "supabase_postgrest"
  observed_at: UTC datetime
  financial_versions: map[opaque ActivityRef, int]
  complete: bool
  safe_error_code: optional stable enum
```

建议显式 adapter 输入口和签名如下，供 runtime/root 定稿；接口定稿前不改共享 `ports.py`/`backend.py`：

```python
@dataclass(frozen=True, slots=True)
class BoundRef:
    kind: Literal["activity", "expense", "ledger_unit", "participant"]
    object_id: UUID
    activity_id: UUID | None = None
    ledger_unit_id: UUID | None = None

@dataclass(frozen=True, slots=True)
class VerifiedReadContext:
    owner_user_id: UUID
    turn_id: UUID
    principal_user_id: UUID
    access_token: str = field(repr=False, compare=False)
    expires_at: datetime
    refs_by_opaque_token: Mapping[str, BoundRef] = field(repr=False)

async def read(
    owner_user_id: UUID, turn_id: UUID, context: ModelContext, decision: ReadDecision,
    *, verified: VerifiedReadContext,
) -> P2BackendReadResult: ...
```

runtime 在每个 Turn 的新鲜 AuthVerifier 成功后构造 grant，并验证 owner/turn 与调用参数相等、`principal_user_id == owner_user_id`、JWT 未过期。`refs_by_opaque_token` 来自服务端持有的 Turn binding；backend 仅将 decision 中 opaque refs 做 kind/parent 校验后映射到 UUID。grant 只在内存一次调用中用，不实现 Pydantic/JSON 序列化，不持久化、不打印。`project_url`、publishable/anon project key 与 HTTP transport limits 由 adapter 的显式配置构造，绝不接收 service_role。

`P2ExpenseFact` 可保留 `expense_version`、`original_expense_id`、base/FX、payment role+amount、split role+amount，便于 runtime/provider 判断事实是否足够；这些字段不自动写入 frozen v1 `ExpenseFact`。`P2DebtFact` 只能保留 `list_settlement_options` 的方向、原币金额/币种、base 值和 `financial_version`；不得推导/计算债务、还款或预存。只把 v1 contract 可表达字段映射进 semantic `ModelReadResult`；来源、完整性、时间和版本通过 runtime 信任的 sidecar metadata 传入 `ModelPrompt`，而不是让模型构造这些字段。

分页/financial version 候选流程：固定查询的排序键稳定且唯一（例如 expenses 按 `occurred_at,id`；付款/分摊按 `expense_id,id`；RPC 按 debtor/creditor/currency）。查询用明确 `limit` + `offset`，发送 `Prefer: count=exact`，并验证每页 `Content-Range` 的 offset/end/total 与实际行数；offset 按实际返回行数推进。服务端可能在 requested limit 以下提前截页，因此短页不代表完整；total 未知、内容范围不匹配、total 中途变化、重复行、页数/行数/body-byte/请求数/总时限超界均须失败，不能把部分列表交给模型。单次 backend read 从 offset 0 开始，在本调用内完成所有页；cursor 不持久化、不进入 ReadDecision。Expense 连同 payments/splits 与 `list_settlement_options` 的多页查询以 Activity `financial_version` 作一致性围栏：开始前读版本 `v0`，读完后重读 `v1`；仅在 `v0 == v1`、membership 仍有效且 child scope 复核通过时返回。债务 RPC 行内版本必须与围栏版本一致；空 RPC 结果也要读 Activity 行取得版本。版本变化时丢弃整批事实并返回 `data_changed_during_read`，不可拼接不同版本。

当前 v1 body 最多 16 条且无完整性字段。若匹配结果超过 16 条，即使 backend 能在内存取完，也不得截断后伪称完整；推荐 runtime 暂不把该结果交给模型/Store，返回可脱敏的 `result_limit_exceeded`。typed error 可标记该结果不完整，但不能携带部分事实继续生成答案。`financial_version` 只覆盖成功财务事实变化；membership、claims 与 child scope 仍需每轮重新查询并校验，不能用版本号代替授权或 participant scope 复核。

按当前授权边界，阶段 B 真实后端资源**未运行（用户延期）**：本任务未连接真实 Auth/Data API、未使用真实 token，也未做 Auth/DB 写、SQL、service_role、Docker 重型栈。这里只完成 CPU 与 fake/loopback transport 验证；真实读取仍需用户后续明确开启并使用安全身份/已登记只读 runner。

## 后端边界与文件 ownership 建议

现有 `BackendAdapter.read(owner_user_id, turn_id, context, decision)` 没有 access token 或已解析数据库绑定参数。API 当前在 `_authenticate` 中验证 bearer token 后，把 token 放进 runtime 的内存 Auth grant；`Principal` 本身不含 token，runtime grant 按 owner UUID 保存。当前 `_activity_ids()` 仍能返回 fixture UUID。因此不能直接把现有 read 方法当作 real backend credential/scope API。

建议新增且仅由 P2 backend worker 管理：

* `agent/app/p2_backend.py`：独立实现固定表/函数 allowlist、只读 PostgREST 请求、内部 DTO、mapper。只用本 Turn 经 AuthVerifier 验证的用户 JWT + publishable/anon project key；JWT 只在内存本 Turn 使用，禁止落盘、进入模型、日志、异常或配置样例。禁止 service_role、admin key、SQL 和任意 RPC。
* `agent/tests/test_p2_backend.py`：fake transport 测试固定 method/path/参数、RLS 认证头来源、scope binding、拒绝 redirect、响应体上限、异常脱敏、错误/非 JSON 处理、分页完整性以及绝不构造写方法。测试不得连云端。

runtime/auth/contract worker 需另行提供仅服务端构造的本 Turn `VerifiedReadContext`（名字可调整）：经验证的 Principal、短时内存 token、Turn ID、服务端持有的 model ref→数据库 UUID binding，以及 activity/unit/participant scope。不要把 token 加入 `Principal` 持久化/序列化，也不要复用 model 文本 UUID。实现须在每个请求使用当前用户 bearer，令 PostgREST 重新执行 grants/RLS；并在应用层重新确认 Activity membership、Activity/Unit/Expense 归属、删除状态和 configured child scope。Token 不可经 redirect 转发；禁用 redirect、设置连接/读取 timeout 与响应大小上限，日志和返回值只给稳定脱敏错误，不包含请求 URL query、上游 body、header 或 secret。

`agent/app/backend.py` 与 `ports.py`/`api.py`/`runtime.py` 为共享接口面；本 worker 暂不编辑。任何新增参数/ownership 由 root 与 runtime worker 协调。Provider/runtime/settings 继续由已有 owner 管理。

## Supabase 文档核验与审查限制

已读取 Supabase skill：`C:\Users\zhy20\.codex\plugins\cache\openai-curated-remote\supabase\1.0.0\skills\supabase\SKILL.md`，SHA-256 `1171386737B231610FA42485707272765C3516A9BBC0BD2C6C161A8CEE3D7D33`。按技能要求复核官方当前文档：

* [Supabase: Securing your API](https://supabase.com/docs/guides/api/securing-your-api)：grants 决定 Data API 对象能否访问，RLS 决定行可见性；两者独立配置；函数不自动受表 RLS 保护。
* [Supabase: Database functions](https://supabase.com/docs/guides/database/functions)：EXECUTE grant 与函数体内的授权检查都重要；审查 SECURITY DEFINER 函数。
* [PostgREST: Pagination and count](https://docs.postgrest.org/en/stable/references/api/pagination_count.html)：服务端 max-row 可能使结果小于 requested range，需检查 `Content-Range` 与 total；短页本身不能判断完整。
* [PostgREST: Transactions](https://docs.postgrest.org/en/stable/references/transactions.html)：GET/HEAD 查询在只读事务中执行；RPC 的 GET/HEAD 只读访问受函数 volatility 约束。
* [Supabase Data API upgrade to PostgREST v14](https://supabase.com/changelog/41288-data-api-upgrade-to-postgrest-v14)：官方记录当前 Data API 版本升级；本次没有实时连接项目验证其暴露 schema 或 ACL。

没有真实 Supabase/Auth 请求或写操作；该事实核查仅基于 main migration、业务文档和 Android DTO。具体实现与 CPU fake 测试状态以文末“实现补充”记录为准；真实 ACL/运行时行为仍需之后在用户明确开启且安全的 runner 上只读验证。

## 实现补充（2026-10-11）

按 root 审批只新增独占文件 `agent/app/p2_backend.py`、`agent/tests/test_p2_backend.py` 和 `agent/tests/test_p2_result_binding.py`，没有修改 contracts、ports、API/runtime/provider、migration 或 main checkout。runtime 接口包括：`resolve_scope(verified: VerifiedReadContext, request: ScopeRequest) -> P2ResolvedScope`；`read(owner_user_id, turn_id, context, decision, *, verified) -> P2BackendReadResult`；`authorize_api_scope(principal_user_id, activity_ids, access_token, expires_at) -> None`；`verify_financial_versions(verified, expected) -> None`。Context validator 对当前 `ModelContext.verified_scope`、权限、全部 `bound_references` 与 decision refs 做类型/活动关系交叉核验；正确按 ContractEnum `.value` 查找 opaque binding。scope/version helpers 仅接收当前 grant 和服务端已绑定 IDs，使用独立有界预算，JWT 放在本次 GET headers，不保存全局 bearer。

内部 Expense DTO 保留 original signed amount、退款链接、base/FX、付款人 Payment 行与 Split bearer 行及各自金额；不会把负退款塞进只接受正金额的 frozen v1 `ExpenseFact`。只读调用仅有固定表 GET allowlist 与 GET RPC `list_settlement_options`；排除 `get_expense_repayment_progress`、prepayment、所有 preview/fallback/写路径。活动列表明确排除逻辑删除行并检查当前 membership；其 `financial_versions` 是单次观察 snapshot。expenses/debts 读取以 activity `financial_version` 做前后围栏，债务行版本也须相等；任何越界/过期/超预算/不完整结果都失败而不返回 partial facts。日期 `date.max` 使用 UTC 当日最大时刻边界，避免 next-day overflow；RPC currency 必须本身满足 `[A-Z]{3}`。

HTTP transport 使用标准库 `http.client`，只构造直接 GET、默认 TLS 证书校验、固定 `Accept-Encoding: identity`、不跟随 redirect/环境代理；请求级 timer 关闭本次 socket，读取用 `read1` 并按总 deadline 更新 socket timeout。Auth 401、权限 403、限流 429、超时、离线/上游不可用分别返回稳定 code；错误不带 token、URL query 或上游 body。fake 测试涵盖短页 server cap、Content-Range 错误/未知/total变化/重复页、JSON duplicate/NaN、HTTP error codes、token scope、子活动 payer/split scope、signed refund/role 保留、债务 RPC allowlist、financial_version 变化、redirect 禁止、响应上限及慢 header/body 主动 socket abort。

定向 CPU 验证：`uv run --offline python -m pytest -q tests/test_p2_backend.py tests/test_p2_result_binding.py`，**43 passed**；日志保存在 `D:\AI\runs\shared-ledger\p2\backend-final-20261011T033356Z\pytest.log`。含仅 loopback 的延迟 HTTP fixture，无公网/真实 Supabase/Auth 访问。阶段 B 真实验证状态为 **NOT_RUN_USER_DEFERRED**。

## Runtime 装配只读复核（2026-10-11）

本次只读查看 `agent/app/p2_runtime.py`、`api.py`、`components.py` 与后端 DTO。Runtime 将付款人 Payment 和分摊人 Split 分组，逐行保留原币及基准币金额，拒绝无法由 frozen v1 正金额 fact 表达的 refund/debt；同 debtor 多 creditor/currency debt 使用私有稳定行身份生成唯一 citation，opaque refs 按 `(kind, UUID)` 绑定。独立 `test_p2_result_binding.py` 用实际 `TurnAggregate` 验证这些映射，未修改 RT 所有权文件。

- 后端 `verify_financial_versions(verified, expected) -> None` 仅对当前 Turn 已绑定 Activity UUID 运行独立预算的 membership → 固定 scalar Activity GET → membership，不返回 DTO、不接受模型 ID。当前 runtime 在模型调用前、生成后和 finalization guard 执行该版本复查；auth 与 membership 也按当前 Turn/request grant 重验。
- Main migration `supabase/migrations/20260901124212_backend_finalization_integration_readiness.sql` 的 `update_activity_settings` 在已有财务写入（`financial_version > 0`）后禁止更改 `base_currency`；`financial_version == 0` 时该限制不成立。版本 helper 只验证 financial_version，不证明名称或 version-0 元数据绝对新鲜；因此测试只验证 version-0 空债务快照可表示，不声称 version-0 非空财务事实的币种新鲜性。Expense 原币可以合法不同于 Activity base currency，不能因此拒绝或自行换算。
- API 在 `_authenticate` 后只将当前请求 bearer/expiry 用于 request-local polling scope helper；P2 `components.py` 分支已连通 runtime/backend，backend lifecycle `start()`/`close()` 是 no-I/O hooks。所有这些 RT/API/components 源文件均未由本 worker修改。

最终 combined 定向 CPU 测试日志：`D:\AI\runs\shared-ledger\p2\backend-final-20261011T033356Z\pytest.log`，输出 `43 passed in 3.00s`。同一证据目录中的 `run-info.txt` 记录命令与环境，`manifest.sha256` 固定源码、测试、runtime 只读快照、文档和日志哈希。仅 loopback HTTP fixture，无真实 Supabase/Auth 请求；阶段 B 状态 **NOT_RUN_USER_DEFERRED**。
后端 freshness helper fake 覆盖：固定 GET 顺序、request bearer header、FV drift、401、403、未绑定 Activity ID 与非法版本拒绝；helper 使用独立 HTTP 预算，不增加模型 `read_calls`。Binding mapper 测试覆盖多 creditor/currency debt 唯一 citations、负退款拒绝、跨 kind 同 UUID typed refs、Payment/Split 原币及基准币金额/角色、financial_version=0 空 debt 快照、scope FV 漂移拒绝。
