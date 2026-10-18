# V2 Contract Review Package

**状态：DRAFT_NO_CANONICAL_APPROVAL**  
**范围：**仅为 root/T1 审阅准备的 additive v2 差异包。不授权 canonical v2 代码、contract export、T1 修改、Supabase/数据库访问或写入、模型生成、Teacher、sealed、evaluation 或 training。

## 审阅决定

显式跨页 continuation 是本任务既定的 v2 功能要求。Activity same-Turn selection 是为 read.activities 后进行有 scope 读取提出的可用性扩展候选；原任务未明确要求该路径，需 root/T1 单独确认，不作为本轮必达验收条件。建议 v2 保持四个既有语义：answer、clarify、read、propose。分页 continuation 与可能获批的 Activity 选择作为这些语义旁的 typed control action，不增加第五语义，也不删除、重绑或重写既有 reference binding。

建议 control action 为闭合 tagged union：

- none：没有 scope 转换或 continuation。
- select_activity：仅能选择当前 Turn 的 complete read.activities 结果中已绑定的 opaque ActivityRef。服务端重新认证、重查 membership/activity 状态及所需 scope，然后递增 server-owned scope_epoch。
- next_page：仅继续 owner、Turn、scope_epoch、operation、criteria_fingerprint 完全一致的唯一 active incomplete query，传递服务端生成的 QueryRef。

QueryRef 仅是私有 server-held query state 的不授权 opaque alias，不是数据库 cursor、credential 或权限。模型不能提交 UUID、PostgREST cursor/offset/keyset、table、URL、bearer 或任意 query identifier。第一版每个 Turn 最多一个未完成 query。私有 continuation state 缺失或无法精确恢复时，fail closed 并要求更窄的新读。

v1 snapshots 与已生成的 v1 exports 必须保持字节不变。任何批准都要单独固定 v2 source、schema、export version、request/prompt fingerprints、容量、token admission 和 T1 同步记录。

## 审查基线与权威来源

只读 main checkout：D:\project\Android\shared-ledger，HEAD 3f938ee6114b763e6cd3dbd10792a78c691eb526，审查时 clean。Agent checkout：D:\project\Android\shared-ledger-agent，branch agent，HEAD 1a80a0f29e1ea432a60b95e7437af23d51182938，已有共享工作区改动。本审查未执行 Git mutation。

| main source | 用作何种 authority | SHA-256 |
|---|---|---|
| docs/backend/BUSINESS_LOGIC.md | Activity/账本、预存和退款规则，第12–13节 | 91C5907CCDA95C118BD4B4B89A7C7F5B012E73664076CF01EFD6DE18291B25D9 |
| app/src/main/java/com/ffocalors/sharedledger/data/financial/FinancialDtos.kt | Prepayment account/usage、refund/party DTO 字段 | 260EB9D1DED7BFCDE32A942C14C7E520D0E9A80B67769F7091B08E6CF7CA3364 |
| app/src/main/java/com/ffocalors/sharedledger/data/financial/FinancialRemoteDataSource.kt | app 当前账户/usage 查询 | AA201E29CCC01AA7BAEBBDADE245DAAB8817A8C8CD95D9A3F00C409BE615597B |
| app/src/main/java/com/ffocalors/sharedledger/data/expense/ExpenseDtos.kt | repayment authoritative DTO | 5E5068F45995AC66AF1680C168EA4BC8986AB6C6F65603C37E1088246DF3EF93 |
| app/src/main/java/com/ffocalors/sharedledger/data/expense/ExpenseRepository.kt | 当前 app 将 repayment progress RPC 作为明细唯一来源 | 433A477889C381E8B3EB8699213F8E0AF73102F9ADA4C86BC095E771ECEDDAAF |
| supabase/migrations/20260831055425_backend_prepayment.sql | prepayment tables、member RLS、authenticated SELECT grants | 6496A004E6CAA032D52634C7E5E80251A3D01AE63D892A3C6EA8D285D5780C0C |
| supabase/migrations/20260920142845_multi_currency_prepayment_final_settlement_core.sql | 账户 currency uniqueness 和多币种 usage snapshots | 2E41D6CDF18ACD1DE97BF095C3C5255BFDB48ECEA634F3902C8ACDB8D38CFAD0 |
| supabase/migrations/20260921051720_targeted_expense_repayment_contract.sql | get_expense_repayment_progress RPC 输出契约 | D7D198CE22395E512D4049A92C3AF22F728914D8DA8B36E52F509A404BE4BE34 |
| supabase/migrations/20260923032928_refund_limits_and_legacy_rpc_permissions.sql | linked refund lineage / immutability | DB76ECFAEB258E0398D36E8779CB89D21E1F1C289C302E114CD7701CE6A9F7AF |
| supabase/migrations/20261006142507_sub_activity_participant_scopes.sql | sub-activity participant scope | 77F11F989A044ABAE93D29B921C878C2FB1357E18FD506769BA629351BC877ED |

已读取 Supabase skill：C:\Users\zhy20\.codex\plugins\cache\openai-curated-remote\supabase\1.0.0\skills\supabase\SKILL.md。本审查只看静态来源，不证明任何 hosted project 已部署当前 migrations/grants/RLS 或返回相同 DTO；没有 Auth、数据库、RPC、PostgREST 调用。

P2 输入：agent/docs/p2/READ_PROTOCOL_NEXT_PROPOSAL.md，SHA-256 B3B850DF55D80D7B7AA30AF5E2AAC2D5BDA38DCBA954139803ACB0E692B3AE0D；agent/docs/p2/P2_REQUIREMENTS_AUDIT_R2.md，SHA-256 2C1583BF6FCC2816E5EBD2D837F13B2A0F209163E5B8C9B1AFACD715F3E5DE9E。二者都是提案/审计输入，不是授权或 canonical approval。

## 通用 envelope 字段提案

字段存在不代表它权威；来源验证、scope 检查、version fence 和 typed reference binding 仍是必须条件。

| 字段 | Authority / 允许值 | Unknown 与零值 | Current 与 complete | 引用绑定 | 容量 | 敏感边界 |
|---|---|---|---|---|---|---|
| semantic | 闭合值 answer/clarify/read/propose | 缺失或未知即 invalid | 不表达 freshness/completeness | 通过 v2 semantic schema | 每个 decision 恰一个现有语义 | 不加第五语义 |
| resume_action.kind | none/select_activity/next_page | 默认 none 仅能由明确 schema 规定；未知 tag reject | action 本身不证明 current，执行前 server 重查 | select_activity 绑定 current complete 活动列表；next_page 绑定 active QueryRef | 每次 transition 一个 action；Turn 单 active continuation | 无 UUID/cursor/token/客户端 query key |
| scope_epoch | server-minted 单调非负整数；0 表示未选 financial scope，接受转换时递增 | 不从缺省推断 0；旧 epoch reject | 标识 scope generation，不表示 source current | owner+Turn+epoch 绑定 financial facts/refs/query/citations | 有界整数；溢出 fail closed / 新 Turn | owner/activity UUID 留 server private |
| query_ref | server-minted opaque query-group alias | 缺失表示无 pending query；未知/过期不表示空结果 | current 需 owner、Turn、epoch、criteria、source、页状态、membership、FV 全匹配；complete 需完整读完 | 每页、outcome evidence 绑定 exact alias 和 criteria hash | Turn 最多一个 pending query；最多16个 page commit 为候选上限 | 非 credential、DB id、cursor、bearer |
| operation | 现有 reads；新 ID 要 v2 registry 批准。候选 read.prepayment、read.expense_repayment、单独的 refund read | 未知 operation reject，非 empty | 必须由当前 scope/available_permissions 允许 | 纳入 query fingerprint 和全部 citations | 闭合 registry；模型不能定义 endpoint/table | 模型不传 SQL/RPC 名 |
| criteria_fingerprint | 规范化、已验证 typed criteria 的 SHA-256，小写64 hex | 缺失/格式错则不可 resume | 只证明 criteria identity，不证明 current 或 complete | 必须与 private pending query 和每页值相同 | 定长 | 日志不含原始 private ID/credential |
| scope_ref | 已有 opaque typed scope 或明确 scope-none | unknown 不等于 scope-none | 必须重新解析 current membership/scope | 绑定 owner/Turn/activity private ID 和 epoch | 现有 ref cap 保持，待 review | raw UUID 不进模型 |
| source | 闭合 source enum，首候选 supabase_postgrest | 未知 source reject | 每页分别重新验证 | 绑定 query/page/DTO projection/evidence | 固定 enum | 不输出 credential/response headers |
| observed_at | server read window 的 UTC 时间 | 缺失为 unknown，不用源时间或零替代 | 时间戳本身不证明 current/complete | 绑定该页/result provenance；源时间独立 | 每 read page/RPC result 一份 | 不含 Auth/session metadata |
| financial_versions | 权威 Activity source/RPC 的 activity→version 映射，非负整数 | 缺/null 为 unknown；0 仅在源明确返回时为零 | 同 query 所有页必须一致；不一致使整组 stale/incomplete | Activity UUID private，模型只见 typed opaque ref | 首版一 Activity | 不暴露 UUID map |
| page_index | server state，首候选 0–15 | 缺失 invalid | 本身不证明 complete | 等于 private state 的 expected next index | query 最多16页 | 不暴露 offset/sort key |
| page_complete | 完成 exact range/count、row-count、order 检查后设 true | false/unknown 不是空结果 | 只描述该页 | 绑定 page body hash/source evidence | 有界 page body，不截断 | 不暴露 raw cursor |
| query_complete | 全部精确页消费且 membership/FV 稳定后才可 true | false/unknown 禁止 exhaustive/zero claim | query group 属性，独立于 page/current | exhaustive claim 引用 QueryRef 下全部页 | 不得超现 Store/result/ref/evidence limits | 不暴露内部 DB 状态 |
| has_more / exact_total | 未验证时 has_more nullable；exact_total 仅接受已验证非负 exact count/range | null=unknown；0 仅 exact source proof 后才是零；缺 count 不转0 | 仅对同一 source snapshot/FV current；total drift 使 query 失败 | 绑定 query/scope/criteria/time/source/all pages | count/page 必须受上限约束 | prompt 不传原始 Content-Range/header |
| page_body | authenticated GET/read-only RPC 的严格 DTO projection | 缺字段保持 unknown；仅源明确返回数值0才是0 | 可 current+incomplete，也可 complete+stale；二者独立 | 每条 fact 绑定 exact result/evidence ref 和 source/projection hash | 不得丢行或截断后标 complete | prompt 去除 raw UUID/无关 private labels |
| ReadOutcomeEvidenceV2 | server 仅在 current member/scope 已验证、exact source total=0、query complete、FV稳定后创建 no_matching_rows_visible_to_current_member | verified member+scope 下 exact zero 且 FV稳定可证明该筛选/time的可见匹配行数为0。授权/成员未知或失败、unsupported scope、count unknown、单纯空数组或读取中断均是 unknown | 必须 query_complete 且引用时 current | outcome ref 绑定 query/scope/criteria/source/pages/time | 每 completed query 最多一条 | 文案仅限该 current member/scope/filter/time 下的可见行，不宣称全局不存在 |

### 完整性与零行规则

complete 表示精确来源查询所需每一页均收到、校验并在 caps 内提交；current 表示重新认证后，membership/scope 与版本检查仍允许使用该结果。两者互相独立：读完结果可以后来 stale；当前第一页也可能 incomplete。

短页不是结束证明。无法验证 exact count/range、排序、membership 或版本时，状态为 incomplete/unknown。final answer 不可根据 pending query 声称完整列表、余额或无匹配。唯一零值证明是 server-created ReadOutcomeEvidenceV2，包含 exact zero 和 current+complete query binding。“当前成员在此 scope/filter/time 下看不到匹配行”不得扩展成“没有债务”或“余额为零”。

## 预存账户和 usage

main 规定 prepayment 是 large Activity 级设施，维度为 Activity、Owner、Custodian、币种；不属于 LedgerUnit。普通 Activity 不支持预存，应返回 unsupported_scope，不能伪装成空账户。app DTO 含账户 balance/currency/可选 base_balance；usage DTO 含 prepayment/debt currency 与 amount、base_amount、bill_fx_rate、bill_occurred_at。nullable DTO 字段保持 unknown，除非经批准来源契约明确有默认语义。

| 字段 | Authority / 允许值 | Unknown 与零值 | Current 与 complete | 引用绑定 | 容量 | 敏感边界 |
|---|---|---|---|---|---|---|
| account_ref/activity_ref | account row 连接 current verified Activity 和 large scope | 缺失/删除/无法连接为 error/unknown，不是0余额 | 重验 membership、Activity type 和 FV 后 current | typed ref 绑定 account row、Activity、owner+Turn、scope_epoch、query/evidence | 首版只一个 Activity，账户行有界 | 原始 UUID private |
| owner_ref/custodian_ref | account.owner_participant_id/custodian_participant_id，经当前 scope participant resolution | participant 缺失为关系无效/unknown | 名称可在FV不变时更新；刷新或隐藏名称 | 绑定 account row 与 Activity scope | 仅返回 bounded rows | 不传 user id、Auth claim、跨 Activity ref |
| currency/stored_balance | account.currency 与 balance；三字母币种+精确 decimal | source 返回0则保留0；null/missing 仍 unknown 并阻断数额结论 | account query complete 且 Activity FV current | citation 指向账户行；不换算 | 精确 decimal、row/byte cap | 不从名称推 owner，不暴露 service id |
| base_balance/base_currency | 仅当选用 authoritative source 明确返回这两个值 | 缺值 unknown，不从 balance 推导 | 同来源 FV | 绑定显式 base-currency 元数据 | optional source field，无合成填充 | 模型不换汇 |
| usage_ref/account_ref/expense_debt_ref/expense_ref | prepayment_usages 与 account/debt/expense/Activity 的授权 join | join 缺失 invalid/unknown，不生成游离 usage | 所有链接在同Activity FV下且完整 | 各自 opaque ref；服务端保留精确 join/result refs | 有界，partial join fail closed | raw source UUID 不进 prompt |
| prepayment_amount/prepayment_currency | usage snapshot 同名字段 | 显式0保留；null/missing unknown | source snapshot current；全部 matching pages 后才 complete | 引用单个 usage 及 account/debt link | 不由 client 跨 usage 求和 | 不跨币种相加 |
| debt_amount/debt_currency/base_amount/base_currency | usage snapshot 中的 debt 值/base_amount；base currency 来自已验证 Activity metadata | 各 nullable 字段分开标 unknown；不互相填零/替代 | FV一致；bill snapshot 是历史事实 | 每项绑定同一 usage 和 Activity base currency | 只呈现源值 | P2不计算 debt/FX/usage总和/current balance |
| bill_fx_rate/bill_occurred_at/observed_at/financial_version | bill FX/time 来自 usage；observed_at来自adapter；FV来自权威Activity读取 | missing unknown；不默认汇率1或生成时间 | 历史bill time不代表current；FV fence与complete独立 | 源时间、观察时间分别引用 | 定长 timestamp/decimal | 不泄露 request token/Auth |

不计算 available balance、剩余 usage、reverse offset、净债、币种转换或聚合。如果来源没有 authoritative field/coherent current version，只可回答单项已知事实或澄清。

## Expense repayment progress

main migration 定义 get_expense_repayment_progress(activity_id, expense_id)：stable、security-invoker，并检查 Activity member。Android ExpenseRepaymentProgressRowDto 保存 debtor/creditor、debt currency、original/base debt、settled original/base、prepayment original/base、offset original/base、remaining original/base 和 financial_version；ExpenseRepository 当前把该 RPC 当作 detail screen source of truth。源存在不等于授权 P2 使用，仍需单独 allowlist、typed read 和 T1 approval。

| 字段 | Authority / 允许值 | Unknown 与零值 | Current 与 complete | 引用绑定 | 容量 | 敏感边界 |
|---|---|---|---|---|---|---|
| expense_ref/debtor_ref/creditor_ref | RPC row expense 与 directed debtor→creditor participant | 缺字段或跨Activity端点使行invalid | 重新验证Activity membership/participant scope | exact RPC row + FV | 首个候选一 expense；RPC rows有界 | 模型不见 UUID |
| debt_currency/debt_original_amount/debt_base_amount | RPC exact fields，base currency来自Activity metadata | nullable DTO unknown；显式0保留 | 同RPC Activity FV current | 每一 directed debt 独立citation | 保留所有返回精度，不合并方向/币种 | 不归一币种、不求和 |
| settled_*/prepayment_*/offset_*/remaining_* | RPC服务端算好的原币/base字段，含reverse-offset规则 | null/missing unknown；0仅源明确给出；禁止用其它字段重算 | 同 RPC result/FV | exact expense/debt row 和 version | body不得丢行后声称complete | 不凭行缺失推定清偿 |
| financial_version | RPC给出的Activity版本 | missing unknown，不视作0 | 读间不一致使财务结论stale | private Activity绑定+opaque evidence | 一 Activity | UUID map private |

read.expense_repayment 仅为候选；不得塞进 read.debts，不调用 preview_prepayment/write RPC，不从债务汇总重算每笔进度。

## Signed refund 与 linkage

main 将 refund 表示为负 Expense。linked refund 必须关联同 Activity 的有效正 Expense，保留原币与完整 FX snapshot，当前有效关联退款的绝对额合计不能超过原额。Payment recipient 与 Split beneficiary 不必跟原 Expense相同。还款后产生 refund 时真实 transfer 保留；方向依真实负 Payment/Split rows 而定。Prepayment Return 是独立 Transfer 概念。

Android FinancialRefundExpenseRowDto 当前含 original_expense_id、signed original_amount、original_currency、timestamps/deletion；party DTO 是单独 participant/amount row。它不是完整 P2 refund contract：选定授权source未返回的role/FX/base字段必须保持unknown，直到typed source读被批准。

| 字段 | Authority / 允许值 | Unknown 与零值 | Current 与 complete | 引用绑定 | 容量 | 敏感边界 |
|---|---|---|---|---|---|---|
| refund_ref/original_expense_ref | expenses.original_expense_id显式link；同Activity解析两行。状态区分linked_refund、unlinked_negative_adjustment、prepayment_return | null link仅在源行完整验证后表示unlinked；缺link/source为unknown | 两行、scope/FV都current后才可用 | explicit edge citation；不能从title推断 | bounded parent-child rows | expense UUID private |
| original_amount/original_currency | signed expense source amount/currency；linked refund为负，币种按main必须匹配parent | 源0保留；null unknown；不abs、不从payments推算 | 源行current；exhaustive claim需query complete | 精确signed row+parent evidence | decimal精确，禁截断/汇总 | 不推可退款余额 |
| fx snapshot/base fields | 只有所选source明确返回refund snapshot和parent对照时才填；main要求继承snapshot，但当前Kotlin refund DTO不含完整FX | missing unknown；模型层不复制parent FX、不算base | refund与parent均current，否则关系不完整 | 每个字段各自 source row/evidence | 精确decimal/timestamp | 不造FX |
| negative Payment / negative Split rows | 分别从authorized payments/splits读取，角色标记 refund_recipient / refund_beneficiary，即使同Participant也不合并 | 缺侧/金额unknown；仅显式源0是零；不推同角色 | 同一refund/scope/FV绑定才current | 每行独立evidence保留payer/recipient与split/beneficiary区别 | 行有界，不collapse/不sum | Participant名仅display；ID private |
| linkage_status/deletion/transfer boundary | 显式linked id和权威status；transfer为另一来源 | unknown/deleted/missing不等于no refund或transfer reversed | current status需fresh rows；历史link即使refund later deleted仍可能相关 | link evidence；如提transfer另引transfer evidence | history超cap即incomplete | 无授权remaining-refund DTO不得声称可退额度 |

在权威read source未提供 remaining-refundable amount 前，P2必须对退款额度问题澄清/拒答。RefundFactV2保留负号及逐条角色行；不abs、不在模型里相减、不声称已发生transfer被退款撤销。

## Scope epoch、continuation与bindings

当前v1 resume无 typed selected Activity；P2 proposal指出 Store append-only bindings 和 common-scope 约束阻止简单 same-Turn list→select。建议以下 additive 方案，待 root/P1/T1批准：

1. select_activity 只能指向当前Turn complete read.activities中已绑定的opaque ActivityRef。
2. 切scope前重新校验当前user、membership、activity active、child participant scope和所需permission。permission属于server available_permissions；模型不索要内部permission或虚构missing slot。
3. server递增scope_epoch。旧candidate refs保留append-only history，但不再是新epoch下可见facts。禁止删除、重绑或重新解释旧refs。
4. 新scope context只含新epoch验证的refs；旧epoch citation/continuation拒绝。未批准scope transition时新Turn可作安全fallback，但不满足same-Turn acceptance。
5. next_page只恢复exact pending query。private record绑定owner、Turn、epoch、source、operation、criteria hash、精确排序、current FV、next page、prior page hash、checkpoint revision、有界expiry；不存credential。resume先re-auth和重验版本/member。
6. 各页body和refs原子追加。total变动、重复/遗漏行、range错位、FV变化、grant过期、claim/CAS丢失、cancel、capacity满或private state缺失都使整组incomplete/stale；不能将已见页当成完整答案。

## 容量与prompt/token预算

v2增加page状态、query-level evidence、零行证明、scope epoch、repayment progress、prepayment account/usage、signed refund/role/linkage字段，schema与prompt都显著扩张。

当前R2模型配置为context window 8192、input admission ceiling 6144、output cap 768、另留512-token安全余量。**此完整v2 schema/body没有实际tokenizer计数；未证明能装入8192 context。** v1先前计数不能沿用；字符或byte数不是token数。

任何v2 live prompt前，须用批准SDK对精确序列化request计数，且绑定exact model artifact/loaded key/context/provider instance。计入完整typed schema、全部trusted fact body、system/user文字和structured-output开销，并保留既定余量。计数unverified/超限即拒绝，无truncate、无静默升cap。页/结果必须能在runtime/store caps内保存，不可丢facts。

若考虑分阶段schema projection，需独立批准、source/schema/prompt version、准确projection规则、独立fingerprint与call budget。投影不能省当前问题需要的源事实、原币/base currency、payer/split/refund role、linkage、provenance、页完整性或cap导致不完整信号。较小schema属于另一个candidate，不等于full v2 acceptance。

仅供评审的暂定上限：每Turn一个pending query、每query最多16页；同时不超过现有read-result/ref/evidence容量（R2 proposal引用16个read results、64 refs、48 evidence refs）。root/T1需在核实当前Store/API约束和SDK实测token count后批准确切v2 row/body/ref上限。超限fail closed为incomplete。不得丢旧页/事实仍标query_complete=true。

## T1 fingerprint 与 prereg 冲突

T1 protocol fingerprint 为 agent/dataset_contracts/t1/protocol-fingerprint.json，SHA-256 089FC318D503CFF7995EA8FEAD876C99B97351E334E270C3DE17E3D1EE452F50。其冻结值包括 API/semantic/operations/trajectory 1.0.0、execution_key 1、v1 contract manifest、generated OpenAPI/schema hashes 与源指纹。冻结模型 prereg agent/docs/t1/MODEL_PREREG-T1-v1.json，SHA-256 E5699FE99BF9B97F4C52E8AC188EE35256B6F1588C13761BAA3013204E3EAD08，status FROZEN_BEFORE_MODEL_OUTPUTS，绑定旧 model/prompt/schema/config/source/bundle metadata。它不能代替新P2 v2 candidate，也不能作为v2质量证据。

此处的 app/contracts.py 指纹差别是换行规范化，不是语义源码漂移。冻结 source_fingerprint 按 manifest normalization 将 CRLF 与单独 CR 规范为 LF 后计算；当前 raw-file Get-FileHash 为 9fd214d9d8eb43c6f5b03b1d7e95b2bef274dbf9e8be495f536f495b48a5bf2d，而对同一当前文件只做 CRLF/CR→LF 后计算为 4da745eeb218cbd75cff2d30b62b0d895ceb8920c54f463cfa7dce35a1ef5130，与 frozen fingerprint 相同。两种算法均为 64 位 SHA-256，规范化匹配；不据此声称存在语义漂移。该 v1 fingerprint/prereg 仍保持历史冻结，不为 v2 review 重导出或改写。新 candidate 仍须建立自己的 source/fingerprint。

T1文档冻结的六个operation ID为 read.activities、read.expenses、read.debts、expense.create、expense.update、expense.presentation.update。T1 release-v2 business review 也记录了empty/post-filter结果缺少typed-query citation的继承问题。因此：

- v1 schema、generated exports、manifest、fingerprint、prereg、bundles及旧结果全部字节保持不变。
- 新candidate独立登记v2 contract/schema/export/operation hash，并独立T1 sync；不得声称v2已被v1 fingerprint/prereg覆盖。
- read.prepayment、read.expense_repayment和refund read仅能在root/T1批准确切read source及GET/RPC method后加入v2 registry。main存在RPC不自动授权Agent调用。
- 新 citation grammar/score strata必须有新的冻结candidate、request/prompt hashes和fixture后才允许generation；旧P2失败或旧T1 fixtures不是新的独立质量证据。
- canonicalization之前先处理source fingerprint与expected generated files差异，且不触碰旧snapshot。
- 本审查未读sealed正文或evaluation代码。

## Rollback 与分阶段验收

Rollback是关闭v2 capability/version negotiation，回到未变的v1路径。v2历史单独保留审计；pending continuation标stale/incomplete并要求新读/新Turn。不得重写v1 body、删除/重绑v1 ref、把v2 page塞进v1 body、把缺失v2字段解释成v1零值、凭hash恢复过期cursor。所有v1 snapshots保持原字节。

| Gate | 批准后工作 | 下一Gate前证据 |
|---|---|---|
| 0. 合同决议 | root/T1决定四语义/control action、scope epoch、page/query/outcome、operation registry和容量 | 书面决议；确认v1 frozen bytes保持 |
| 1. authority mapping | 对照main DTO/RPC和authenticated GET allowlist，核实refund base/FX与role-specific行是否权威返回 | main hash、精确source projection；不假设远端 |
| 2. additive schema/export | 批准后仅在v2 namespace实现 | 单独v2 schema/export hash manifest和compat tests |
| 3. CPU safety | fake page boundary/total drift/scope switch/owner-turn-query binding/unknown-vs-zero/current-vs-complete/role/currency/linkage/cap/cancel-CAS/credential-cursor leakage tests | tied to v2 source 的 deterministic evidence；这只是engineering |
| 4. Token admission | exact full v2 prompt/schema/body、approved SDK、exact loaded artifact/model/context/provider绑定及fail-closed | 所有冻结fixture的真实count；timeout/oversize拒绝；无truncate；生成前冻结source/request |
| 5. T1 sync | 审查新operations/citations/fixtures/denominators/prereg和fingerprint reconcile | 新独立candidate/prereg；不复用v1 prereg |
| 6. Live read | 仅在用户明确授权资源、root批准计划后；current-user bearer、authenticated GET/read-only RPC | 独立非sealed测试账户、DTO对账、grants/RLS/只读证据；本任务未做 |
| 7. Model diagnostic | exact source/schema/prompt/fixture/call budget freeze且root批准后 | 新evidence；model行为与Harness reject/rewrite分别计数；本任务未做 |
| 8. Rollback/compatibility | 关闭v2，验证v1 bytes/hash和v1 request行为不变 | 与冻结v1 snapshot比hash；拒绝stale v2 continuation且不修改旧refs |

## Root/T1 同步清单

实现或任何live test前需决定：

- 四语义是否固定，resume_action与select_activity/next_page所在的API/resume schema版本。
- scope_epoch的递增、旧candidate refs保留但不进入新scope、所需Store/P1 invariant变化。
- QueryRef格式/私有binding/TTL、单pending query、每页事务/CAS、restart/auth恢复。
- 精确page/row/result/ref/evidence/byte/time/query/token caps；何种exact count/range可证明complete与zero；incomplete row是否禁止进入最终答案。
- main DTO/RPC是否提供所有所需prepayment/repayment/refund字段，尤其refund base/FX与负Payment/Split角色行；其余哪些必须标unknown。
- fact与ReadOutcomeEvidenceV2 citation grammar以及current-member visible zero的准确用语。
- exact model/provider identity下完整v2 request token count和output预算；任何approved projection属于独立candidate，不截断trusted facts。
- 新v2 registry、export/schema/fingerprint、candidate fixtures、model prereg、T1 receipt；保存未解决的v1 source-hash drift。
- Supabase live状态与静态源码证据分开；operation注册不授权远端调用、preview或写路径。
- rollback保留v1 snapshots和old bindings原样，只stale/expire新的v2 continuation。

## 本次审查结论

本文只提出additive contract与source-backed field map。未授予或推断canonical approval；未改代码或exports；未调用Supabase/数据库或模型；未打开任何T1 sealed正文或evaluation。

