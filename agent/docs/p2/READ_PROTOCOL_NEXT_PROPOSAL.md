# P2 只读协议增量提案

**状态：修订版 3；durable recovery/v2 候选待 root / T1 审阅，不授权 live Supabase。** 本版的 volatile same-scope multi-result 小节已按 root 单独批准实现，证据见 [`MULTI_RESULT_R2.md`](MULTI_RESULT_R2.md)；其余内容是下一阶段协议提案，不是实现授权。修订版 2 SHA-256 `2E1D327234B2AC1F74E29E9CA9D6BE20E61A295E1A2608B9CCDBEB572155F6E2` 和修订版 1 SHA-256 `ADCB643F78A4EA5A38AA8A3DA29C93D08E92981F49C6524D424FAAB1042E2C9C` 均保留为 **SUPERSEDED** 历史草稿；不得作为当前提案引用。本版采纳审查意见并把 volatile same-scope multi-result 与需 Store 的 durable recovery 分开。现有 canonical/export v1 保持冻结。业务真相仍来自 main 的 docs、Android DTO 与当前 SQL/RLS/ACL；真实 B/D 继续延期。任何 v2 semantic/operation/schema/hash/prereg 变化必须先由 root 决策并与 T1 协调，不在本提案中改动。

审计基准与源文件 SHA-256 见 [`P2_REQUIREMENTS_AUDIT_R2.md`](P2_REQUIREMENTS_AUDIT_R2.md)。主要业务证据：main `docs/backend/BUSINESS_LOGIC.md`；`ActivityRepository.kt`、`ExpenseRepository.kt`、`ExpenseDtos.kt`、`FinancialRemoteDataSource.kt`、`FinancialDtos.kt`、`TransferRepository.kt`；`supabase/migrations/20260830100429_foundation_rls.sql`、`20260830115418...expense_core_rls.sql`、`20260830191659_backend_debt_projection.sql`、`20260919164707_multi_currency_settlement.sql`、`20260920142845_multi_currency_prepayment_final_settlement_core.sql`、`20260921051720_targeted_expense_repayment_contract.sql` 和 `20261006142507_sub_activity_participant_scopes.sql`。本提案不假设某个远端项目已应用这些迁移。

## 不可破坏的约束

- Supabase bearer 只能来自本次 `/auth/v1/user` 成功验证的当前用户请求。每个 REST/RPC 请求用 request-local credential；不复用可变全局客户端 header。access token、密钥和 Auth 响应不能进入 Store/journal/model/log。服务 UUID 不得进入模型 prompt 或普通日志；**private Store 的 owner/Turn/activity/entity/FV binding 可以是严格类型化 UUID 列**，但只能作为服务端解析后的 owner-scoped 绑定，不能当授权凭据或自由字符串输入。任意 PostgREST cursor 不得进入模型 envelope。
- 业务调用始终以当前用户 bearer + publishable/anon public key 执行；RLS 与对象 grants 必须同时满足。没有 service-role/admin、SQL、DML、preview/write RPC、确认卡、Gateway 或后台绕过。
- backend 只从通过 Auth 的 User grant 导出；UI activity hint 与模型决定的 opaque reference 都是待 server 重新解析的线索。重新读取 membership / activity / child-scope 后，才能把当前 Turn 绑定映射为 private UUID。UUID 不作为授权因子。
- 完整性与新鲜度不同：`complete` 表示该 query/page 已按照来源边界完整读出；`current` 表示在当前重新认证、成员仍有效且 financial-version fence 一致的时点仍可用。旧结果可以永久完整，同时失去 current。混合不同 financial version 的来源不得回答一个财务状态问题。
- 金额、债务方向、FX、结算、预存抵销、退款额度均由 main 后端 DTO/RPC 产生。Agent 保留原币、base、payer、split、debt debtor→creditor 和版本字段；只呈现、引用和绑定，不重新求和/净额/换汇/abs/估算剩余。
- `ToolReadResult` body 是冻结 v1 事实的唯一持久正文。volatile provenance 仅在内存记 owner/Turn/scope/query/source/FV 与 ref 绑定。durable journal 候选只存无 credential 的 binding/provenance 摘要、query/raw DTO/projection/body hashes、观察/生命周期元数据，与 checkpoint append/CAS 同事务提交；不复制 v1 正文。缺少的 payer/split/base 等不是从 hash 恢复的事实；未来若批准 typed P2 supplement persistence，必须明示为链接到该 v1 body 的独立内部投影、规定一致性且通过 Store/P1 review，不得假称是现有 body。

## 立即可实施候选：volatile 同 scope 多结果 currentness（无 Store/schema 变化）

源码锚点：`p2_runtime.py:53–55` 已按 Turn 在内存保存多条 provenance/supplement/label；`:645–657` 将多结果 provenance 和 current supplements 发给 Harness；`:680–688` 在模型生成后校验 FV，`:1099–1134` 对所有 current financial provenance 合并期望版本并在冲突时 fail closed，`:1146–1148` 在 final commit 前再次验证身份和版本。当前真正阻断同一进程 multi-read closure 的 runtime 行为在 `:793–797`：成功 append 新结果后无条件把所有此前 provenance 改为 `current=False`。Harness 已按多个 result_ref 校验 provenance、逐 citation 读取 current facts（`p2_harness.py:117–127, 178–205, 282–314`）；Store checkpoint 已 append 多个同 scope 结果与绑定，因此这一窄功能不需要新增 Store journal。

建议只做窄的 runtime 增量：只保留 previously-current 的金融 result，且新旧 operation 不同；owner/Turn、精确已验证 Activity scope 与 scope fingerprint、context version、planning generation、complete/non-simulation 状态、每项各自的 query/body/source metadata 必须与该项 immutable Store result/evidence/ref bindings 完全匹配；新旧查询指纹无需相等，但全部 financial-version map 必须一致。首个验收为同一 Turn 的 expenses→debts，答案可以分别引用两条事实，但不得求和、净额、换汇或推导余额。同 operation reread 会令旧 result 永久 stale，避免同一数据经两个 evidence 输出；旧结果即使后来重新读取到旧 FV，也不得重新激活。无 scope 的 `read.activities` 始终是 point-in-time 候选列表，不与 financial facts current，也不由本功能解决 list→select。

runtime 中的 `source_fingerprint` 是对 source、FV、Agent observation time、result id、query/scope 与 owner/Turn binding 的 **binding/provenance fingerprint**，不是 PostgREST raw DTO hash，也不能证明 raw response 未被外部重建；`ToolReadResult` body fingerprint 单独校验 durable typed body。未来 journal 若要做 source equality，必须新存/重取规范化 raw DTO 并单独核验，不能把当前字段名解读为已有 raw-source hash。

每次新 query 仍正常收费并使用当前 request-local JWT；新 query 前、模型生成后和答案/final event commit 前既有 membership/FV checks 必须保留。任何 scope/version/context/generation/query/body/source/ref metadata 不匹配、未知或缺失都会使相关旧项 stale/拒绝混合回答。Changed FV 当前可终止该 Turn 并要求新 Turn，本阶段不要求自动重读。模型 dispatch 与 final renderer 只传当前组的 supplements，并在同一 verified evidence/ref binding 集合内验证；过期 expense supplement 不得阻断新 current debt answer。Participant/ledger labels 若来自 fresh verified scope resolution且属于该 scope，可保留供 proposal；result-derived activity/expense labels必须与相应 result current绑定，不能盲目保留。FV 0 不保证显示名新鲜，缺少可信当前 label 时省略名称或使用 opaque ref，不能用 label 授权。进程重启、Auth pause、claim/generation 重建后 provenance/supplement 缺失必须 deterministic fail closed/请求新输入；本阶段不解决 durable recovery。

实现 checkpoint 与 CPU fake 验收单列于 `MULTI_RESULT_R2.md`；这是 root 批准后的窄运行时增量，不改变 frozen v1 semantic/schema/export，不改 Store/provider/backend，不构成 live Supabase 或完整 C/D 通过。

## 后续 durable recovery 候选：private journal；需 Store/P1 审查

本阶段只解决进程重启/Auth 恢复所需的 durable provenance metadata，不是上节 volatile multi-result 功能的前置条件。它不改 canonical v1 shape/operation，但**不是零侵入实现**：要改 Store API、SQLite schema/事务和 append-only validation，必须由 root 协调 Store ownership 并进行 P1 compatibility review。它不含 same-Turn list→select（当前 v1 API/Store invariant 无可行迁移路径）、跨页业务 continuation、零行权威证据或预存 operation。

### Private `P2ReadJournalEntry` 候选结构

建议在现有 Store 的 P2 专属内部表/API 增加 append-only row；不导出到 `agent/contracts/v1.0.0`，不写原始业务 body：

```text
schema_version          = 1
owner_user_id            UUID (private store key)
turn_id                  UUID (private store key)
result_id                UUID (must equal existing BoundReadResultReference)
result_ref               existing opaque v1 ReadResultRef
operation                existing v1 ReadOperation
criteria_fingerprint     SHA-256 of canonical typed ReadDecision criteria
scope_fingerprint        SHA-256 of owner + Turn + server-resolved activity/scope
typed_read_decision      exact frozen-v1 ReadDecision/criteria snapshot (opaque refs only)
source                   fixed source enum, e.g. supabase_postgrest
source_query_fingerprint SHA-256 of canonical source table/RPC + safe filters/order
observed_at              timestamp from adapter response window
financial_versions       private activity UUID -> integer map, if financial query
source_dto_sha256        SHA-256 of canonical typed raw source DTO rows, excluding Agent observed_at
projection_sha256        SHA-256 of canonical typed fact/supplement projection, excluding Agent observed_at
metadata_sha256          optional canonical display-label projection hash, separate from finance
body_sha256              SHA-256 of canonical serialized existing ToolReadResult, including its observed_at
complete                 boolean, may only be true for a full bounded result
snapshot_checkpoint_revision  checkpoint revision that atomically appended this result
origin_generation        charged generation at result commit
entry_expires_at         fixed bounded private-metadata TTL (not renewed by receipt replay)
last_validation_at       nullable; a validation observation, not a durable grant
last_validation_revision nullable current checkpoint revision used for that observation
last_validation_generation nullable current generation used for that observation
last_validation_versions nullable activity UUID -> current FV map
created_at               store timestamp
```

No `access_token`, API key, raw model text, Auth response or claim/lease secret is stored. The private typed `ReadDecision` snapshot includes only the already-validated frozen criteria and opaque typed refs; it permits a future bounded re-read and is not re-parsed as authorization. Private UUID binding columns may be stored only under owner+Turn and with expected entity kind/scope. `observed_at` is the Agent-side observation time, not a timestamp supplied by the source and not a financial source fact. It remains in the immutable v1 `body_sha256`, but is excluded from source DTO, semantic projection, and display metadata hashes; source-owned `occurred_at`/`created_at` values remain part of the exact typed source DTO. Canonicalization must be versioned and deterministic (strict typed rows, stable ordering, exact decimal strings, normalized UUIDs/timestamps). A changed label/name is tracked separately in `metadata_sha256`; because FV 0 does not guarantee metadata freshness, label hash change requires refreshing/omitting that label, not claiming finance changed. The hashes are integrity comparisons only: **they cannot reconstruct raw rows, labels, payer/split roles, base amounts or supplements**. No raw PostgREST cursor is stored in this stage; continuation state belongs to a separately reviewed v2 design. Metadata expiry never extends a Supabase Auth lease. Exact TTL and retention need root/store policy approval.

If approved, commit protocol must be one Store transaction/CAS:

1. Read the current Turn/checkpoint under owner key and active claim; verify the **current** expected checkpoint revision, state/generation, and that the Turn is nonterminal. The journal also records the historical `snapshot_checkpoint_revision` and `origin_generation` for the result being appended.
2. Build one complete frozen-v1 `ToolReadResult`, its opaque refs and evidence bindings, then append the body to the existing checkpoint.
3. In that same transaction append its journal entry whose `result_id`, resultRef, `snapshot_checkpoint_revision`, origin generation and `body_sha256` match the actual result projection. Any conflict rolls back both body append and journal append.
4. Do not store an incomplete `raw` response as an empty body. Existing v1 behavior of rejecting page/row/cap overflow remains until an approved v2 contract exists.

The journal is not an authorization grant. After a process restart or `/resume/auth`, the runtime must require fresh request Auth, exact same `principal_user_id == Turn.owner_user_id`, a fresh in-memory owner+Turn grant, and Store owner/Turn/current generation/active claim CAS verification **before it evaluates old metadata for currentness**. Revisions naturally advance as events/checkpoints are appended, so `snapshot_checkpoint_revision` is historical: require `snapshot_checkpoint_revision <= current_checkpoint_revision`, then locate the exact immutable `result_id/result_ref` in current `TurnCheckpoint.read_results` and recompute its `body_sha256`. Do not require the current revision to equal the result’s commit revision. For any new write, compare-and-swap against the current revision/generation and active claim lease inside the Store transaction; never persist the raw claim token or Supabase token in journal. `origin_generation` identifies when the result was produced; it is not by itself a perpetual equality precondition against the current generation. A pending continuation, unlike a historical complete result, is invalidated by a new planning generation unless a separately reviewed transition explicitly preserves it.

**A body hash does not restore supplements.** Current `ToolReadResult` body omits payment-vs-split roles, per-line base amounts and some display-label/source detail; `P2ExpenseSupplement`, labels and provenance live in process memory. Do not claim that validating `body_sha256` rehydrates them. `observed_at` varies per Agent read and is not source identity: exclude it from raw DTO/projection comparisons while retaining it in the immutable v1 body hash. Separate financial-source fields from display metadata; a changed participant/activity label at FV 0 requires re-resolving or omitting the label, not treating the label change itself as financial drift. Pick one explicit recovery mode:

1. **Preferred bounded re-read:** retain the validated typed criteria snapshot plus private UUID binding map; after Auth, owner, current claim and query/scope checks pass, re-execute the exact read under the fresh request bearer, recheck membership and same FV, and charge one normal read call before any GET. Map returned source DTO into new supplements/new current result, and append the new `ToolReadResult` rather than editing the old append-only body. The `source_dto_sha256` verifies the exact typed source DTO observation only; it cannot create values. A changed raw DTO hash forces a new projection from the newly authenticated response, but a label-only difference is handled by `metadata_sha256` and does not imply FV changed. If read budget is exhausted, financial source/FV differs, TTL expired, or criteria/ref no longer resolves, clarify or ask for a new query.
2. **Separately approved typed persistence:** extend the Store with a typed P2-only supplement snapshot carrying the source fields absent from v1 body (payer/split role, original/base line amounts/currencies, stable source/label version and financial version) and hashes linking it to exact result id/body. Save it atomically with the v1 body and bindings. This adds a second representation of some source facts and therefore needs explicit root approval, a consistency invariant and P1 Store compatibility review; it is not allowed by this documentation-only task. Even this option must re-authenticate, recheck membership/FV and refresh participant/activity labels before final rendering; at FV 0, metadata/name fields are not guaranteed fresh by the financial-version counter.

If Auth, owner, current claim, checkpoint CAS, body/source/projection hash, scope, membership, version, TTL or typed persistence/re-read check differs, leave saved v1 body append-only but mark it unusable as current and clarify/new read. A terminal Turn remains terminal; receipt replay must not create/extend a grant or resume it.

Final answer path repeats the version and membership check immediately before result/event commit. An earlier check does not authorize a later answer after a model-generation window. Checks consume a separate bounded GET budget, do not reset model/read counters, and use the same request-scoped bearer. No token is retained by the journal or Store.

### Multiple read results and freshness rule

Before the approved volatile increment, the runtime invalidated every earlier provenance after any successful read (`p2_runtime.py` prior baseline, recorded in `P2_REQUIREMENTS_AUDIT_R2.md`). The current implementation retains a prior complete result as current only within the same volatile process state and only if owner, Turn, exact verified Activity/scope fingerprint, typed bindings, context version, planning generation, complete status, non-simulation status, each result’s query/body/source-metadata binding against its own immutable checkpoint body and binding, and the full financial-version map still match. The runtime `source_fingerprint` is a binding/provenance fingerprint, not a raw HTTP DTO hash; the durable body has its own fingerprint. The next pre-generation, post-generation, and pre-commit membership/FV checks remain mandatory; conflicting FVs fail closed. This supports the first same-Turn expenses→debts closure because `ModelContext.read_results` and Store append-only bindings already support several complete results in one Activity scope. This stage remains volatile; after auth pause/restart state is lost and the old result cannot be restored as current. Durable currentness/rehydration remains the separate Store/P1-gated journal stage. Never merge rows or derive totals; each read remains its own immutable result/evidence body. See `MULTI_RESULT_R2.md` for current code/test hashes and CPU evidence.

If a later read finds a different `financial_version`, preserve the older row as `complete=true, current=false`; do not downgrade the body or erase audit history. It stays stale permanently, even if a later read returns an earlier version number. Any answer depending on a stale row is rejected/clarified or triggers a full new read. A different Agent `observed_at` alone does not invalidate matching financial source facts. Never combine a financial result captured at FV 8 with a later result at FV 9 as one consistent answer. The current version fence does not prove version-zero metadata/name fields are absolutely fresh; re-resolve display labels/selection on demand, and describe version-based currentness only for fields governed by that financial version.

For `read.activities`, there is no complete activity-snapshot financial-version token. Treat it as a point-in-time candidate list, not permanent scope proof. Re-resolve any candidate via current user membership + active activity GET before granting any financial operation. Never use an old activity display name as identity or authorization. Re-resolve visible labels before final rendering when metadata can change without financial version increments; otherwise omit labels and use existing opaque refs.

### Optional workflow candidate: same-Turn activity-list selection

The earlier design treated an existing opaque `ActivityRef` plus a fresh `resolve_scope` call as sufficient. That is not implementable under current contract/Store invariants and is superseded by this section. Existing typed fields are:

- New `SubmitTurnRequest.ui_context` can supply an untrusted Activity UUID hint only when creating the Turn; `TurnRecord.ui_context_snapshot` is immutable.
- `ResumeClarificationRequest` carries only user text, request id and expected state revision. It cannot carry an opaque selected ActivityRef or new UI context. `ResumeAuthRequest` carries only request id and state revision.
- `ModelNoActivityScope` grants only `READ_ACTIVITIES`. Parser/Harness rejects expenses/debts before a scope exists, even though criteria schemas contain an `ActivityRef`.
- `bind_stable_references` and `Store._validate_append_only_bindings` never allow deleting/rebinding old refs. `validate_model_context_bindings` requires the exact persisted ref whitelist and, for an activity context, requires every Turn entity binding to share that one scope. A complete activity-list read can append multiple ActivityRefs, each bound to its own Activity scope. Once listed, the other candidates cannot be removed or rebound when selecting one.

Therefore no current v1 request/resume/typed semantic path can transition from a no-scope list containing multiple candidates to a single financial Activity scope in the same Turn. This is a product-workflow limitation, not a literal unmet requirement from `TASK-P2-READONLY.md`: line 18 requires clarification for multiple candidates, and line 91 requires clarification for out-of-scope objects plus protection against old typed refs binding to a same-name/same-number entity after an Activity switch. A new Turn created with the intended UI Activity hint can satisfy that scope boundary by resolving and binding the selected Activity afresh; it does not offer a same-Turn follow-up after listing. Keep that seamless flow an optional feature candidate unless root chooses to require it. Do not implement a one-off `_resolve_scope` call that bypasses the current parser and Store invariants.

If root elects to add same-Turn selection as a convenience workflow, coordinate a separate API/Store/contract design and P1 compatibility review first. Candidate design needs (a) a typed selection action that accepts only an ActivityRef already bound to the complete current-Turn activity list, (b) fresh current-user Auth/RLS GET of membership and active activity, and (c) a new explicit scope epoch/subcontext or isolated reference namespace so old no-scope candidate refs remain append-only but cannot violate the selected Activity context invariant or appear as financial refs. It may require an additive request/semantic/context schema version. If that redesign is not approved, retain the safe new-Turn/UI-scope flow; this does not change the explicit old-reference isolation requirement.

The volatile multi-result rule above adds no model operation/schema because it only retains already-verified reads inside one existing activity scope. It does not add this optional selection workflow. Test any future scope-selection design with the existing `ModelNoActivityScope` path, typed `ActivityRef` mapping, membership cross-check and read permission transition together.

## 第二阶段：additive v2 页状态与安全 continuation

跨请求 continuation、page/current completeness semantics 超出 v1 body schema。需要新版本 contract/registry/export，而不是修改 v1 definition 或把 partial pages 伪装成 v1 complete read。若一个 query 在现有 bounded backend request 中能全部收齐且最终事实不超过 16，v1 可继续返回一个完整结果；若超过事实/预算限制，v1 就 fail closed。这个内部收页能力不满足“可恢复的跨调用 continuation”。

建议 v2 新增独立 typed result/read envelope（旧 `v1.0.0` 行为不动）：

```text
ReadQueryResultV2 {
  query_ref: opaque QueryRef (server minted, Turn-bound semantic alias; never DB UUID/cursor)
  operation: versioned read operation
  criteria_fingerprint: SHA-256
  scope_ref: existing opaque typed activity reference
  source: fixed source enum
  observed_at: timezone-aware timestamp
  financial_versions: list[{activity_ref: opaque typed ref, financial_version: int}]
  page_index: bounded integer
  page_complete: bool
  query_complete: bool
  has_more: bool
  exact_total: int | null (only if provider verified exact Content-Range)
  page_body: bounded typed facts, with source and page evidence refs
}
```

`QueryRef` is a semantic label for a server-held query group, not a PostgREST cursor, UUID, bearer or client-chosen continuation token. Keep the actual next offset/keyset, exact total and ordering data only in private runtime/journal state. Model cannot supply raw `offset`, cursor, table/URL, Activity UUID, Expense UUID, or arbitrary query ID. Allow at most one active incomplete query per Turn in the first implementation: continuation is a typed `next_page` intent plus the same operation and exactly matching criteria fingerprint. Harness requires an active pending record for the owner+Turn+scope+query; otherwise it rejects. That avoids ambiguous selection among pending cursors. If multiple unfinished query groups are later required, that needs a separate reviewed state machine, not a free-form handle.

Private continuation entry extends the same CAS journal, still without body duplication or credentials:

```text
query_ref, owner_user_id, turn_id, scope_fingerprint, operation,
criteria_fingerprint, source, activity_id, required_financial_version,
page_index, next_offset_or_sort_key, exact_total, deterministic_order,
last_page_body_sha256, snapshot_checkpoint_revision, origin_generation,
entry_expires_at, last_validation_checkpoint_revision, last_validation_generation, state
```

Each page transition transaction atomically appends its actual typed page body to the existing Store checkpoint, adds the body-hash binding and increments continuation state under owner/Turn/current-generation/current-checkpoint-revision/active-claim CAS. `snapshot_checkpoint_revision` and `origin_generation` are historical page metadata; require the snapshot revision to be no later than current and validate the immutable page result/hash, not equality with the current checkpoint revision. Resume after process restart must reauthenticate first, verify owner and current CAS, recheck current member/activity/FV, recompute prior body hash, and use the private next offset only if exact total and version remain stable. Never persist Supabase token. On missing continuation, lease expiry, owner change, body mismatch, claim loss, cancellation, stale FV, membership loss, changed total, duplicate row, or capacity exhaustion: mark query incomplete/stale and require a new narrowed query; never answer from pages seen so far.

Wire protocol rules:

- Every read page uses the same fixed GET table/RPC allowlist, request-local current-user bearer and per-page expiry check. `Prefer: count=exact`, deterministic unique order, explicit `limit`+`offset` (never ambiguous Range/limit mixing), bounded requests/bytes/time. Validate HTTP status, exact range start/end, total, row count and duplicate IDs. A server may cap response below requested page size: advance by actual verified count, not requested count. Short page does not imply completion. Unknown `*/` count, missing/wrong range, total drift, repeated/omitted range or budget exhaustion is an explicit incomplete error.
- For a financial group every page rechecks member RLS/source Activity and expected financial version before and after fetch; a new FV invalidates the full group. Continuation never spans Activities, owners, Turns, operation, criteria or scope.
- `page_complete` means the page/range itself passed all bounds. `query_complete` is true only after verified exact total has been consumed and all page bodies are committed. A query group with `has_more=true` cannot support a final answer that implies the full matching set/balance. Each answer citation must identify the exact page/evidence and the v2 validator must ensure group completeness when the answer states an exhaustive total or absence.
- Bound the v2 group by existing reviewed runtime/Store capacities first (e.g. no more than 16 committed page results until capacity changes are separately approved). Over capacity returns explicit incomplete; never drop older pages from context while claiming the query complete. Any larger capacity is an additive contract change and new hash/T1 synchronization.

### Empty-result evidence

Frozen v1 has no fact/evidence type for “this complete authorized query returned zero matching rows”; empty list with no citation cannot satisfy the grounded-answer validator. v2 should add a server-created `ReadOutcomeEvidenceV2`, not a fake expense/debt row or model-authored citation:

```text
ReadOutcomeEvidenceV2 {
  evidence_ref: opaque typed outcome ref
  outcome: "no_matching_rows_visible_to_current_member"
  query_ref: QueryRef
  operation: versioned read operation
  criteria_fingerprint: SHA-256
  scope_ref: typed opaque ActivityRef or scope-none
  source: fixed source enum
  observed_at: timestamp
  exact_total: 0
  query_complete: true
  financial_versions: [] or versioned activity map
}
```

Create it only after GET/RPC returned a verified exact `Content-Range` total of 0, the entire query is complete, current membership/scope checks pass, and financial-version fence is stable for financial operations. If exact count/range is unavailable, permissions filter rows, request is partial, or budget ends before complete, return unknown/incomplete—not “zero.” User-facing claim must be precisely limited to “当前成员身份下、此 scope 与这些筛选条件，在 observed_at 没有匹配记录”; it must not imply global absence or that every debt/balance is zero. The new outcome evidence is citeable in a new v2 answer contract only; v1 remains unable to give authoritative zero-row answers.

## 第三阶段：明确的预存/偿债/退款 read contracts

There is no v1 `prepayment` operation. Do not call prepayment data a `DebtFact` or return it as `read.debts`. Main confirms a large-Activity account dimension and per-Usage multi-currency snapshots; it does not permit normal Activity prepayment. The main Android DTO supports these exact source fields, but Agent needs a separately reviewed v2 operation and schema.

### `read.prepayment` candidate (v2 only)

Criteria: one already verified `ActivityRef`; no model UUIDs. Backend resolves the private UUID from the current Turn binding, GETs the active Activity and rechecks membership, then requires the Activity type be `large`. Normal Activity is a stable `unsupported_scope`; it does not appear as an empty account result. No account is attached to a `LedgerUnit`. Current user JWT RLS and explicit authenticated SELECT grants must both permit reads of `prepayment_accounts`, `prepayment_usages`, and any related rows. Query is bounded and uses deterministic ordering.

Typed account fact, carrying only source-returned data:

```text
PrepaymentAccountFactV2 {
  account_ref: opaque typed ref
  activity_ref: opaque ActivityRef
  owner_ref: opaque ParticipantRef
  custodian_ref: opaque ParticipantRef
  currency: CurrencyCode
  stored_balance: exact DecimalString
  updated_at: source timestamp
  observed_at: response timestamp
  financial_version: int
}
```

Typed usage fact:

```text
PrepaymentUsageFactV2 {
  usage_ref: opaque typed ref
  account_ref: opaque account ref
  expense_debt_ref: opaque debt ref
  expense_ref: opaque expense ref, resolved via authenticated in-scope source rows
  prepayment_currency: CurrencyCode
  prepayment_amount: exact DecimalString
  debt_currency: CurrencyCode
  debt_amount: exact DecimalString
  base_amount: exact DecimalString
  bill_fx_rate: exact DecimalString
  bill_occurred_at: source timestamp
  observed_at: response timestamp
  financial_version: int
}
```

`account.balance` belongs to account currency. `prepayment_amount`, `debt_amount`, and `base_amount` are distinct source values; never compare/add them without business rules. Do not calculate “available balance,” reverse offsets, refund capacity, current net debt, FX conversion, or account usage aggregation in P2. Report only fields whose exact authority and version come from a row or approved RPC. If balance must be derived from usage rows, first add an authoritative main read DTO/function; an Agent-side sum is out of scope.

Main migration fact: `prepayment_accounts` adds a currency and becomes unique by Activity+Owner+Custodian+currency; `prepayment_usages` adds `prepayment_currency/amount`, `debt_currency/amount`, `base_amount`, historical bill FX and timestamp (`20260920142845...:21–48`). Existing member RLS/authenticated SELECT is in `20260831055425_backend_prepayment.sql:15–34`. This is static migration evidence only. The P2 adapter must still explicitly allow only needed GET tables and recheck all participant/activity relationships. `preview_prepayment` is a preview contract, excluded even if it is stable/invoker and technically callable through GET. No create/return/transfer RPC is allowed.

### Repayment progress and refund boundary

If a user asks a per-expense “settled / prepayment / reverse offset / remaining” question, candidate operation is a new typed `read.expense_repayment` (or separately versioned detail read), implemented by GET of main’s `get_expense_repayment_progress(p_activity_id,p_expense_id)` only after approval. The current main migration defines a stable, security-invoker, membership-checking function and grants authenticated execute; its DTO explicitly returns debtor→creditor, debt currency, original/base debt, settled original/base, prepayment original/base, offset original/base, remaining original/base, and `financial_version` (`20260921051720...:952–1065`; Android DTO `ExpenseDtos.kt:69–96`). The exposed P2 operation must resolve both IDs from same Turn's typed bindings and send GET only. Do not use this function under the current v1 allowlist, and never substitute `preview_prepayment`.

Refund facts require signed amount and linkage; v1 `ExpenseFact` is positive-only and current mapper rejects negative raw Expense rather than taking absolute value. New v2 may add a `RefundFactV2` with signed negative original amount, `original_expense_ref`, preserved currency/FX snapshot, and separate negative Payment recipient and Split beneficiary facts, all sourced from authenticated GET. It must distinguish linked refund, unlinked negative adjustment, and prepayment Return. Main business rules: linked refunds are capped against a same-Activity valid positive source, same currency and identical FX snapshot; aggregate active linked refunds may not exceed source; refund payer/recipient and split beneficiary need not mirror original; refund after real transfer leaves that transfer in place and may create reverse debt. P2 cannot infer remaining refundable amount from one refund row or compute it. Until main exposes an authoritative remaining-refund DTO in an approved read method, P2 must clarify/refuse refund-capacity questions. No actual refund creation, prepayment return, transfer, confirmation, or business write is enabled.

## 分阶段实施/同步/回滚与验收

| 阶段 | 允许的实现 | 同步门 | 必须通过的独立测试 |
|---|---|---|---|
| 0. 文档决策 | 本文、R2 audit 和 source path/hash review only。 | root 逐项接受/驳回；确认 v1 冻结，确认工作树 ownership；不改 T1。 | 审计路径/hash复核，main/Agent HEAD与初始状态记录。 |
| 1. Volatile multi-result | 仅在 `p2_runtime.py` 同一Turn内保留 scope/context/generation/FV 完全匹配的 previously-current、不同 operation、complete/non-sim financial results；不改 Store/canonical v1/provider/backend。 | root审阅 runtime owner 的 implementation checkpoint；无 live Supabase。 | expenses→debts→双citation；不同FV/不同scope/同operation reread/metadata不匹配时旧项永久stale；旧supplement隔离；missing provenance、restart/auth loss fail closed；late cancellation/claim loss不覆盖；read/model budget不重置。 |
| 1b. Durable private journal/recovery | **只作为 root 审批后的 Store 改动提案**：新增 Store 内部 metadata API/table、SQLite DDL、事务/CAS与 append-only validation；不改 canonical v1 shape/operation。Same-Turn scope selection排除在本阶段。 | root协调 `agent/app/store.py` ownership，审阅 SQLite migration/version/checksum 和 `transition_turn`/`save_checkpoint` 原子性；P1 compatibility review 必须完成后才实现。本文不授权直接改 Store。 | restart/Auth resume需 fresh Auth、owner/current claim验证、精确重读并按read budget收费或单独批准typed supplement persistence；FV变化时旧项complete但stale；历史snapshot rev不要求等于current rev；hash mismatch失败；TTL/replay不续期；terminal不可复活。 |
| 1c. Optional same-Turn scope-selection workflow | 这是从无 scope 的候选列表继续查询的可选体验设计，不是 TASK-P2-READONLY.md 的逐字验收项；目前安全的新 Turn + UI hint 路径满足旧 ref 隔离要求。 | 仅在 root 决定增加该体验后，协调新 request/semantic/context version、Store invariant升级与P1 review；可能触发T1同步。 | 多Activity候选 append-only历史不被删改；选中的ActivityRef来自当前Turn列表；非成员/被删/旧ref/跨scope拒绝；scope epoch隔离旧候选的模型可见性；用户输入无UUID能力；normal resume不隐式切scope。 |
| 2. Additive v2 pages/outcomes | 单独 `2.0.0` read/result/context/parser/export（不改 v1）；private page continuation；`ReadOutcomeEvidenceV2`。 | root+T1 审查新 operation/schema、registry、export hash、T1 manifest/prereg影响和独立 fixtures；新的 sealed one-shot依然单独授权。 | exact Content-Range多页；server cap smaller than request仍按实际count推进；unknown/wrong range、drifting total、duplicate/omission、FV drift、RLS/auth failure、grant expiry、cancel/CAS、restart/reauth、too many pages均明确 incomplete；精确 0 才有 empty proof；零行用户文案严格 scoped；模型没有 cursor/UUID/token。 |
| 3. Additive prepayment/repayment/refund reads | v2 `read.prepayment` + typed account/usage；单独 `read.expense_repayment` RPC DTO；signed refund fact若 main DTO允许。纯 GET。 | root+T1批准 operation/schema；root确认 main SQL已有接口/ACL满足，或另行协调 main owner新增只读源后再做；审计不得触发 migration。 | `large`允许/`normal`拒绝；Activity+owner+custodian+currency隔离；same member/nonmember/removed member真实范围待B；payer/split role、原币/base、debt方向 exact；usage三种金额/币种不同也不混；没有绝对值/求和/FX重算；refund linking/negative adjustment/return区分；不出现 preview/write route。 |
| 4. C质量与 B/D live | 独立运行 provider 与用户账户验收；版本化 DTO 上的闭环测试；保护当前 quality failures。 | 用户解除 B/D 延期、可用两账号和已登记受控 runner、root 明确安排仅只读 endpoint 与 log 范围。T1质量样本需按当前批准 prereg独立冻结。 | C 四语义和 answer citations按冻结指标报告；B 两身份/Auth/RLS+DTO对账；D真实读→body→后续模型→引用、分页/empty/recovery；全程只 GET/current-user bearer，无写。 |

**Store 变更触点与回滚：**private journal 不是只添文档即可接入。Store 当前把 `TurnRecord`/`TurnCheckpoint` 编码在 SQLite `turns.record_json/checkpoint_json`，并在 `Store.transition_turn`、`Store.save_checkpoint` 一个事务里检查 revision/claim、append-only refs/body 和 checkpoint CAS。若加 `p2_read_journal` 表，需新增 Store schema migration/checksum、读写 API、事务参数、同事务插入/验证，以及错误回滚测试；还要更新/评审 `TurnCheckpoint` 或独立 private table 的 lifecycle、`_validate_append_only_bindings`、`validate_model_context_bindings` 和 P1 Store compatibility tests。**root 当前只授权文档，不授权这些 Store 改动。** SQLite migration 必须只增量向前兼容，不改 main/cloud SQL；禁用 journal 功能时读取旧 v1路径，hash/CAS不匹配视作 stale、不造 body。保留历史 metadata；清理另需 root 决策。

**回滚协议语义：**v1 默认路径/导出始终保留；若 v2 功能或新 endpoint 有问题，禁用 v2 feature flag并停止继续页/新 operation，v1 仍按原合同 fail closed。不得以回滚为由执行 main/cloud migration、清库或重置共享数据。

## 仍须 root/T1 作出的决定

1. 已按 root 批准实现仅进程内的 volatile multi-result currentness（无 Store 改动），首阶段限定同一已验证 Activity、同 FV 的不同 financial operations（expenses+debts）与双引用回答；是否接受该实现与 `MULTI_RESULT_R2.md` 的 focused CPU 证据作为此窄增量的交付？restart/Auth pause 后继续 fail closed。
2. 是否另行接受 v1 semantic-compatible private journal 改现 Store API/本地SQLite schema/事务，并指定 owner；P1 Store compatibility review覆盖哪些 `TurnRecord/Checkpoint` invariant和 migration回滚检查？Auth resume/重启后优先采用重新 authenticated GET、正常收费、append new result；预算不足就 clarification。若持久化缺失 supplement，需单独批准 typed P2 Store payload/hash/一致性规则；仅 `ToolReadResult.body_sha256` 永远不能恢复 supplement。
3. `snapshot_checkpoint_revision`/`origin_generation` 与未来 checkpoint/generation的关联规则、metadata TTL/retention 应由 Store owner定稿；本提案要求只将当前 revision/generation用于当前写CAS，不要求和历史 result commit revision永久相等。source FVs和label版本在FV 0时的freshness限度是否接受？
4. 是否要把 same-Turn list→select 作为额外工作流体验加入后续计划？TASK-P2-READONLY.md 明确要求多候选时澄清、scope 外对象澄清和 Activity 切换时旧 ref 隔离；它没有逐字要求列表后在同一 Turn 选择。当前 new-Turn/UI-scope 流程可满足旧 ref 隔离。若仍要 seamless same-Turn selection，是否批准独立的 additive selection action + scope epoch/subcontext + Store invariant redesign？
5. v2 设计中的 `QueryRef`/`next_page`是否符合“模型看不到任何 raw cursor/token/UUID”的边界；第一版限定单个 active pending continuation 与现有 16-result capacity是否足以达到真实需求？
6. v2 zero rows 使用新型 `ReadOutcomeEvidenceV2` 的 citation/answer grammar；准确“无匹配记录”含义及 exact count如何证明。
7. 是否批准新增独立 `read.prepayment` 与 `read.expense_repayment`，以及 refund typed fact。`get_expense_repayment_progress`虽已在 main migration授权 authenticated execute，但不得因“数据库函数存在”而默认成为 Agent operation；preview仍排除。
8. 若 main 没有可直接读取的 authoritative refundable limit 或需要额外 return history DTO，应由 main owner决策新增只读事实源；Agent 不计算、不迁移、不推导。
9. root 与 T1 确认 additive v2 canonical/operation/hash/prereg步骤和隔离的新开发 fixtures。冻结 v1/T1历史文件不改写。
