# T1 同步交接 R2：独立 v2 只读候选

**状态：**供用户手动交给 T1 会话的审查包。root 已完成设计层审查，并同意继续准备 additive v2 候选；这不是 canonical schema/operation 批准、T1 接收记录或实现授权。此文档没有同步到其他会话。

## 输入基线与 SHA-256

当前 v2 审查输入是 `agent/docs/p2/V2_CONTRACT_REVIEW_PACKAGE_R2.md`，实算 SHA-256 `A89F6B604685E53DA2E8A5195385A1A9ACA6D2B9DD01BEDC23CB5955F36BCE55`。对应 D 盘 revision manifest：`D:\AI\runs\shared-ledger\p2\v2-contract-review-r2-20261012T004752Z-e6977d16d9d545adb1de78caa1d5a21a\v2-contract-review-r2-manifest.json`，实算 SHA-256 `9EE985CDBC96F1A60D928B67C8245674C5B8F4DB3D3AFE187FAE717209A2D331`，状态 `DRAFT_NO_CANONICAL_APPROVAL_NO_T1_SYNC`。它固定 review-package 文档的新旧版本关系，不含当前 audit/proposal 的正文副本，也不证明远端部署、T1 接受或数据库状态。

为避免版本混用，本次交接的六份当前正文另存为完整输入包：`D:\AI\runs\shared-ledger\p2\t1-sync-handoff-r2-20261012-final\`。请以该目录内 `manifest.json` 列出的逐文件 SHA-256 与 checkout HEADs 作为本次唯一 T1 输入；`manifest.sha256` 校验 manifest 自身。此前基于旧 package SHA 的 `t1-sync-handoff-r2-20261012-5c760bec` 和在本轮请求文本更新前生成的 `t1-sync-handoff-r2-20261012-a89f6b60` 快照均只保留为历史，不是本次输入。

当前输入文档及磁盘实算 SHA-256：

| 输入 | 路径（agent checkout 内） | SHA-256 |
|---|---|---|
| V2 字段/权限/兼容审查包 R2 | `agent/docs/p2/V2_CONTRACT_REVIEW_PACKAGE_R2.md` | `A89F6B604685E53DA2E8A5195385A1A9ACA6D2B9DD01BEDC23CB5955F36BCE55` |
| 原任务逐项审计 | `agent/docs/p2/P2_REQUIREMENTS_AUDIT_R2.md` | `667109720035D58018341D2044551DD56EBE212AF9E32A54626EF337EB8128EF` |
| 协议/continuation 提案 | `agent/docs/p2/READ_PROTOCOL_NEXT_PROPOSAL.md` | `82EB113C787E6C639366967A5AA941FF92274B511C090E33C09A72985359C341` |
| 原始任务 | `agent/docs/p2/TASK-P2-READONLY.md` | `D2FFAEF49E9479CF61D2E29BF3BC664B80A97EDC867E8A3E6BAD5CFD4E072ED7` |
| 当前 Turn volatile multi-result 记录 | `agent/docs/p2/MULTI_RESULT_R2.md` | `171CF662EA91F108A8B56FE7CEBB7CA786561F5011EE3F52F86C927B3C01C02F` |

初次 review manifest `D:\AI\runs\shared-ledger\p2\v2-contract-review-package-20261012003134Z-a26e2fddf96d48cdba902cd89a577dca\v2-contract-review-manifest.json` SHA-256 `9644314E15B7EEE6FA042CD8177B5729B6322D1FD6E460B596B4420C508EA1A1` 及旧 `V2_CONTRACT_REVIEW_PACKAGE.md` SHA-256 `0CC23A74DF1C9385174A2F5964B7017FCB5D7D9447A4CB74F22EF22456C2A68F` 均为历史。初次 manifest 中的 audit/proposal hashes `2C1583BF6FCC2816E5EBD2D837F13B2A0F209163E5B8C9B1AFACD715F3E5DE9E` 与 `B3B850DF55D80D7B7AA30AF5E2AAC2D5BDA38DCBA954139803ACB0E692B3AE0D` 不对应当前正文；R2 revision manifest 只记录审查包自身版本关系。本次 D 输入包把当前六份正文和 checkout HEAD 固定在同一 manifest，避免拼接历史 hash 与当前文件。

main 的业务 authority 仍是 `D:\project\Android\shared-ledger`；核心业务文档 `docs/backend/BUSINESS_LOGIC.md` 当前 SHA-256 为 `91C5907CCDA95C118BD4B4B89A7C7F5B012E73664076CF01EFD6DE18291B25D9`。本交接不读取 sealed/evaluation 正文，不调用 Teacher，不执行 live Auth/Supabase/DB 请求。

## 原任务明确要求与当前缺口

以下项目来自原任务 `TASK-P2-READONLY.md` 的明确范围，不应降格为可选 v2 体验：

- **跨页 continuation 和恢复。** 原文第 20、89 行要求大于单页时提供可恢复 continuation，并将结果绑定原用户、活动、查询条件、Turn、类型和版本；第 93 行要求 Auth 过期后经 `/v1/turns/{id}/resume/auth` 沿原 Turn/查询身份继续，且可审计、不重复执行副作用。当前后端只在一次有界请求中收齐最多 16 个事实；超过上限即拒绝，尚无跨请求/进程 continuation journal。当前 Turn 的多 operation 同版本保留只是 volatile CPU 增量，不等同于可恢复 continuation。
- **来源可信的业务事实。** 原文第 18、89、91 行要求读结果带类型化引用、来源、时间、版本，后续模型消费真实正文并以其为依据作答/继续读取；方向、原币/base、付款人/分摊人角色、活动范围和过期版本不能被模型补算或混用。现有 frozen v1 `ExpenseFact` / `DebtFact` 无法承载完整付款/分摊角色、全部原币/base/source/version provenance；v1 结果不是完整源 DTO。
- **大型活动预存及其使用/退回事实。** 原文 B 阶段第 75 行点名核对大型活动账户与已使用/退回的 prepayment facts，并要求金额、币种、版本和观察时间来自真实权威 DTO/RPC。普通 Activity 不支持预存；P2 不得从债务计算余额、净额或 FX。v1 registry 没有 prepayment operation，且不能把预存伪装成 `read.debts`。
- **偿债/退款所需的后端权威事实与边界。** 原文要求事实来自业务后端，且明确禁止 Agent 计算替代业务后端；main authoritative DTO/RPC 对偿债进度、方向、原币/base、退款/预存 Return 有更丰富字段。当前只读 allowlist 没有 repayment-progress/prepayment/refund 读取，负 Expense 在 v1 被拒绝；没有已批准的 P2 refund DTO/operation。原任务明确要求读取已用/退回预存事实；对一般 linked expense refund 的完整独立查询是否属于单独 operation，应由 root/T1 针对用户任务表述确认。若候选支持退款事实，必须保留 signed negative amount、parent linkage 和独立的 refund recipient / beneficiary 角色；不得取绝对值、推算剩余可退款金额或声称真实 Transfer 已被撤销。`read.expense_repayment`、`read.prepayment`、`read.refund` 都只是候选名，不能作为已批准 API/RPC。
- **恢复时重新授权并验证当前性。** continuation 重启后必须先重新 Auth，核对 owner、当前 claim/CAS、membership/scope、完整 source/query/body/projection hash、版本和 TTL，再继续原查询身份；原 token 不落盘。旧 checkpoint revision 是历史锚点，不应要求随着 checkpoint 推进永远相等；须验证对应 body 是 append-only 历史、generation/claim 仍持有当前 CAS。缺失/过期 journal、body 不可重验或版本改变时明确 stale/incomplete 并 fail closed。body hash 不能复原 v1 未保存的 payment/split/base/label 字段：恢复要么重新 authenticated exact GET 并计入 bounded read budget、核 FV 与 source projection，要么另行审批与 checkpoint 原子绑定的 typed P2 durable body；不能凭 hash“rehydrate”不存在的事实。

静态 main migrations/ACL 与 Android DTO 只证明仓库中存在对应 source contract，不证明 hosted project 已部署或 live RLS/DTO 返回一致。新增操作仍需先列出固定 GET/read-only RPC method、grants 和 RLS 前置证据；Supabase publishable/anon public `apikey` 仅用于项目/API 路由，不代表用户身份；经 Auth 验证的当前用户 access-token bearer 才是用户身份并用于请求。禁止 service-role、SQL、preview/write RPC。

## 明确不属于原任务逐字必达的增强

- **同 Turn `read.activities` 后选择 Activity。** 原文第 18 行要求多候选时澄清，第 91 行要求 scope 外对象澄清及 Activity 切换后旧 typed refs 不得错误重绑；它没有要求“先列多个 Activity，再在同一 Turn 选一个”。当前无 scope 只允许 `READ_ACTIVITIES`，resume request 没有 typed `ActivityRef`，候选 refs append-only 且 Store 要求 financial context 只有同一 Activity 的 refs。当前安全 fallback 是新 Turn 用 untrusted UI hint 重新 Auth/RLS resolve。免开新 Turn 的 `select_activity` + `scope_epoch` 是可选产品流程候选，若推进须新增 typed transition 和 Store/P1 兼容审查。
- **零行权威回答。** 原文要求真实 evidence-grounded answer，但没有逐字要求“空查询必须能以 citation 断言无匹配”。现行为 deterministic clarify/fail closed；`ReadOutcomeEvidenceV2`（仅在 exact count=0、完整查询、当前 membership/FV 均验证后由 server 创建）是有用可选增强，不是原任务独立验收项，也不得把未知/过滤/不完整解释为零。

## 独立 v2 候选边界（尚未 canonical/T1 批准）

候选目标是新建一个 additive、独立指纹的 v2 contract/schema/export；保留既有 answer/clarify/read/propose 四种语义。`next_page`、可能的 `select_activity` 是候选 typed control action，不新增第五语义。`ReadQueryResultV2`/page status、private continuation record、typed prepayment/repayment/refund facts 和可选 `ReadOutcomeEvidenceV2` 是审查草案，不是已注册 operation 或可调用 API。任何新增 operation 的精确名称、source table/function、GET method、ACL/RLS、DTO、criteria、scope 与权限都须 root/T1 明确决定；main 中存在 function 不自动授权 Agent 调用。

Continuation 候选的模型面只允许 server-minted opaque `QueryRef` 与匹配的 operation/criteria；模型不能提交 UUID、PostgREST offset/cursor/keyset、URL/table、token 或任意 query ID。私有 entry 绑定 owner、Turn、scope epoch/fingerprint、operation、criteria fingerprint、source、current FV、排序、next page、last body hash、历史 checkpoint revision、generation/claim、TTL/expiry 与状态。每页校验 exact `Content-Range`/total、range、行数、唯一排序和 duplicate，按实际 verified row count 推进；短页不代表 complete。total/FV/membership/claim 变化、预算/容量耗尽或状态无法恢复都使整组 incomplete/stale，不能从 partial pages 作 exhaustive/zero/balance 结论。最多一个 active pending query 与候选 16 页只是待审容量，不是批准上限。

任何同事务保存 query journal/body-hash binding 的实现会触及 Store API、SQLite 表/迁移和 P1 append-only invariant；此交接不授权改 Store。T1 与 root 应先审 durable P2 body 的唯一事实来源、CAS 原子性和恢复时 exact GET 重读策略。禁止把第二份事实副本与 v1 body 混成一个无法核验的 truth，也禁止仅存 token/cursor。

## T1 同步需要的独立版本材料与回滚

T1 如果同意继续，需要为 v2 建立全新的、与 v1 隔离的 candidate identity/version、schema 与 generated export、source/request/prompt/config fingerprint、read-operation registry、contract manifest 和独立 model prereg；不复用或覆盖 `agent/dataset_contracts/t1/protocol-fingerprint.json`、冻结 v1 manifest、`MODEL_PREREG-T1-v1.json`、旧 source hashes、exports 或旧 run bundles。manifest 应记录精确 main DTO/migration/RPC source lineage hashes、每项 GET/method/ACL/RLS mapping、字段到 DTO projection 的映射、schema/export/prompt/provider/model fingerprints、capacity/token budget、validation fixture lineage 与所有 acceptance denominator。任何 unknown-vs-zero、current-vs-complete、scope/query binding、方向/币种/付款和 refund-role fixture 都需纳入新增候选验证计划；不得访问 sealed 或调用 Teacher。

需要 T1 独立决定四语义下的 control action 所在 API/resume schema、候选 operations、evidence/citation grammar、source freshness/recovery 规则、fixture/split/denominator 与 prereg 指标。已冻结 v1 指标不能自动给 v2 提供覆盖；v2 必须独立报每 operation 指标与 `INSUFFICIENT_SAMPLE`。

回滚只能关闭 v2 capability/version negotiation 并回到未变的 v1 行为；保留 v2 审计历史，将未完成的 v2 continuation 标 stale/incomplete 并要求新查询/新 Turn。不得重写 v1 body、删除/重绑旧 refs、把 v2 pages 塞入 v1 DTO、把缺字段当零，也不应通过重新导出改变 frozen v1 bytes。恢复 v2 前必须重新通过该候选的 manifest/prereg/兼容与安全门。

## 可直接复制给 T1 会话的同步请求

> 请以 `D:\AI\runs\shared-ledger\p2\t1-sync-handoff-r2-20261012-final\` 中六份只读正文为本次完整输入，先核验 `manifest.json` 与 `manifest.sha256`。当前 V2 review package 是 `V2_CONTRACT_REVIEW_PACKAGE_R2.md`，SHA-256 `A89F6B604685E53DA2E8A5195385A1A9ACA6D2B9DD01BEDC23CB5955F36BCE55`；其 D revision manifest `D:\AI\runs\shared-ledger\p2\v2-contract-review-r2-20261012T004752Z-e6977d16d9d545adb1de78caa1d5a21a\v2-contract-review-r2-manifest.json` SHA-256 `9EE985CDBC96F1A60D928B67C8245674C5B8F4DB3D3AFE187FAE717209A2D331`。六份正文的确切 SHA 与 main/agent HEAD 在该新输入包 manifest 中；初次 review manifest 和旧 package hash 仅是历史记录。
>
> 请先决定原任务明确要求的可恢复跨页 continuation、Auth/runtime 恢复、source-versioned facts 与大型活动 prepayment usage/return 的 v2 contract/registry/prereg 如何独立同步；明确哪些偿债进度/一般 refund typed read 属于已批准范围、权威 source/method/ACL 与未知字段，且不得把预存塞入 `read.debts`、对退款取绝对值或自行计算。请把 `select_activity` same-Turn 工作流与 `ReadOutcomeEvidenceV2` 零行答案分别评为可选增强，不将它们误记为原 TASK 明文验收项。若接受候选，请指定新的 candidate/version identity、manifest/source lineage、schema/export/prompt hashes、四语义下控制动作、独立 prereg 与 fixtures/denominators、P1 Store/CAS 所需审查，以及关闭 v2 并保持 v1 bytes 不变的回滚条件。当前均是设计候选：canonical 与 operations 尚未批准、T1 sync 尚未发生；此次请求不授权修改冻结文件、调用 live Supabase、访问 sealed/evaluation 正文或调用 Teacher。

此次只生成了此交接文档；没有联系 T1、修改源码/Store/exports 或进行同步。