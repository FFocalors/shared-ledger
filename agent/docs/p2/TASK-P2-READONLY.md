# P2：真实只读链路交接任务

状态：交接说明，供用户复制到独立开发会话。本文只定义任务和验收，不表示 P2 已实现或已通过。

## 可复制的任务指令

```text
在 D:\project\Android\shared-ledger-agent 的 agent 分支完成 P2「真实只读」工程增量：接入可配置的 LM Studio ModelProvider 和按当前登录用户身份访问 Supabase 的只读 BackendAdapter，让 Agent 通过真实四类语义完成有界的读取闭环；保留业务写入关闭状态。业务事实以 D:\project\Android\shared-ledger 的 main 分支和当前 Supabase migrations/RLS/RPC ACL 为准。

先读本文件、agent/docs/shared-ledger-agent-development-guide-v0.4.html 全文、agent/docs/dev-status.md、agent/docs/p1/FINAL_REVIEW.md、agent/docs/t1/README.md、COVERAGE-T1.md、MODEL_PREPARATION-T1-v1.md、BUSINESS_ACCEPTANCE.md，以及 agent/app 的 ports.py、backend.py、model_provider.py、runtime.py、harness.py、gateway.py、settings.py、contracts.py、components.py、api.py；再核对当前 main 的业务文档、Android repositories、SQL/RLS/RPC 与真实接口。不要从 Agent checkout 根目录旧 app/supabase/docs/backend 推导当前业务事实。

开工时记录分支、HEAD、工作区状态和本任务文件清单。共享 Agent checkout 已有未提交 P1/T1 工作，禁止 git checkout、reset、clean、stash、commit、push；不要覆盖或重置其他会话的文件。所有新增产物、模型运行、日志、临时文件放 D 盘；不创建 C 盘 worktree，不自行创建或联系其他 Codex 会话。用户会自行把本文件交给并行会话。遇到同文件冲突时保留双方工作，记录冲突路径并交 root 协调。

只实现读取和模型规划。Supabase 必须通过 Supabase Auth 校验后的当前用户 access token 调用 REST/RPC，并由 RLS 限行；绝不使用 service_role、管理员凭证、直连数据库或任意 SQL 代替用户鉴权。请求 token 只在内存中短暂传递，不写 SQLite、模型上下文、普通日志或评估产物。后端只允许经过审查的 GET /rest/v1/<table> 与已核实的只读 /rest/v1/rpc/<name>；RPC 的 HTTP method 需按当前 PostgREST contract 记录，允许的只读 RPC 才能调用。拒绝任何写 RPC、业务 DML 或其他写请求。

LM Studio 首选并首先修复/验证指南指定的 OpenAI 兼容 POST /v1/chat/completions；当前已知旧探针曾 HTTP 200 但返回空 content，并以 finish_reason=length 结束，须复现并解释，不能把 HTTP 200 当成推理成功。T0 的 Qwen3.5-4B Q4_K_M /api/v1/chat smoke 只证明当时原生路径连通，是可评估的候选适配，不是已批准替换首选接口的决定。若兼容接口仍有问题，可实现原生适配作为候选并记录行为/格式差异；若要正式改变接口策略，先在 docs/p2 新增版本差异说明并交 root 评审、同步 T1，再更新 canonical contract 或共享指南。不要启动、加载、卸载或强行终止用户的 LM Studio / 游戏进程。CPU 与离线开发先完成；模型实测待用户已选择的资源释放后再做。

完整实现四种语义 answer / clarify / read / propose 的解析与受限运行；read 必须把真实类型化工具结果正文、来源、时间和版本返回模型，并支持下一步读取或基于结果回答。answer 引用必须绑定到真实证据，model 输出不能创建 UUID、权限或业务事实。多候选、旧引用、scope 冲突、金额缺失时澄清。proposal 只允许安全识别/标注意图；P2 不实现 live preview、确认、提交、P3 Gateway 或任何业务写入。

固定并记录每轮模型调用数、读取工具数、上下文大小、模型并发、单用户排队、全局排队、超时、输出 token 与重试预算。保留有界行为：调用或上下文预算耗尽就明确停下；timeout/busy/离线可恢复且不得丢失任务、无限重试或重复执行；迟到输出不得覆盖已取消/更新的 Turn。多页结果、截断和分页状态须绑定原用户、活动、查询条件、Turn、类型与版本，显式告知不完整；不得把截断结果说成完整余额。

按阶段交付：A CPU-only 实现与 fake transport 测试；B 两个独立真实用户 token 的只读 Auth/RLS/scope 验收（资源允许时使用隔离数据与已登记 runner，不重置共享或 cloud DB）；C 兼容接口和 LM Studio 实测（待资源释放，保存 D 盘证据）；D 完整闭环诊断和失败分类。每一阶段单独报告工程通过、模型质量和未测项。按 T1 已冻结指标报告确切分子/分母和 per-operation 结果；样本不足明确记 INSUFFICIENT_SAMPLE。只可使用 validation 或全新、独立的开发 fixtures；sealed 不打开、不解析、不用于调参，单次正式 sealed 评测必须等待候选合格并另有 root 明确授权。不得调用 Teacher、训练模型或改 T1/evaluation/data_*。

所有改动限于 agent/app 的 P2 adapter/runtime/settings 装配、agent/tests 的新增 P2 测试、agent/docs/p2 新文档和 D:\AI\runs\shared-ledger\p2 下的独立运行产物。不得覆盖 agent/docs/p1、agent/docs/t1、agent/evaluation、agent/dataset_contracts/t1、T1 冻结 v1 manifest/prereg/source hashes、T0、现有 data/evaluation 脚本或 review artifacts。共享 README、dev-status、统一指南及导出的 canonical contracts 属 root 协调点。若要改 semantic、operation、schema、registry 或导出快照，先在 docs/p2 写版本差异文件，指出兼容性、hash、T1 影响和回滚办法，等待 root 评审并同步 T1；独立工作不覆盖冻结 v1 文件。

完成时仅报告实际改动文件、命令和结果、真实 Auth/RLS 与模型阶段分别的状态、预算配置、失败项、D 盘证据路径与 hash、契约差异和待 root 决策。不要提交或推送，不要把 P2 baseline 通过写成 CAP01–CAP17 完成；真实 Agent CAP 当前基线为 0/17。
```

## 交接时已核实的当前基线

- P1 已由主会话限定批准为 `PASSED_LIMITED_P1_ENGINEERING`：可恢复骨架、Mock Runtime、身份隔离、本地 Auth smoke、Docker 部署及备份恢复。证据不覆盖真实业务工具或模型质量。
- 真实 Agent CAP01–CAP17 当前 **0/17 可验收**。默认装配仍为 `DisabledModelProvider`、`UnimplementedBackendAdapter`、`UnimplementedRuntime` 和 `UnimplementedGateway`；只有显式 mock mode 才提供固定模拟数据和模拟 Runtime。
- 当前 v1 registry 一共有六个启用 operation：`read.activities`、`read.expenses`、`read.debts`、`expense.create`、`expense.update`、`expense.presentation.update`。其中只有前三个是读语义，后三个只允许模拟 proposal；**没有 prepayment operation，也没有业务写执行能力**。CAP13 大型活动预存仍未实现。若只读预存不能由现有三项语义清楚、类型安全地承载，需提出新增版本化 read operation，不得说它已在 v1 六项中。
- T0 的 Qwen3.5-4B Q4_K_M 候选文件为 `D:\computer\LM_Models\shared-ledger\t0-cp36-20261007\qwen3.5-4b-q4_k_m.gguf`，SHA-256 `acfd01df6cbd3c8e1fa4dbe144f5852290689851c4f92d4ab892707d08724b34`。T0 已记录 `/api/v1/chat` host/Docker smoke；权重的精确 base snapshot lineage 未证明。不得将该候选描述成已证实训练基模或模型质量通过。
- T1 `t1-synth-1.0.1` 有 111 条合成诊断样本，train/validation/sealed 各 37，manifest SHA-256 `f87eae34f7d77632701ed3fcf1090e1e6a5adedcbe5e39342241a44448f0dddf`，root 诊断审批 SHA-256 `8b5f94329a3c2e7f1c008152ebc440fcb2434c6af32d05da8775307583ae7188`。正式发布状态仍 `INSUFFICIENT_SAMPLE`，15 组潜在 prompt 近重复，`human_review_pending=true`、`training_eligible=false`。模型评估 `NOT_TESTED_USER_DEFERRED`，Teacher `NOT_TESTED`，sealed one-shot 授权为 false；这些冻结结果不可覆盖。
- **最新 T1 release-v2 注记（2026-10-11）：**独立 v2 一次请求、三例合成短文本，root 对三例作 3/3 限定语义复核；Teacher 数据质量仍 `NOT_ASSESSED`，Student 评估因用户延期及资源限制未运行，P2 仍未验收。此项有界结果不改写上面的历史 v1 冻结状态，也不代表训练数据或整体模型质量通过；见 [Teacher availability](../t1/release-v2/TEACHER-AVAILABILITY.md)、[Teacher readiness](../t1/release-v2/TEACHER-READINESS.md) 与 [release-v2 candidate preparation](../t1/release-v2/README.md)。
- 现有 `agent/evaluation` runner 是 teacher-forced 诊断回放：工具结果和后续上下文来自冻结轨迹，不能证明模型驱动读取闭环或真实 Backend Agent。P2 必须让 Runtime 把刚取得的实际读结果交回模型，并记录真实下一步。
- 业务事实以 `D:\project\Android\shared-ledger` 的 main 为准，指南 v0.4.2 和当前后端一致：普通活动无预存入口，FUND/use/RETURN 整笔拒绝且不能降级为普通 Transfer；大型活动预存账户按 Activity + Owner + Custodian + currency，跨有效子活动使用。新增预存只先清偿 Owner→Custodian 当前可按付款币种结清的债务；预存 Usage 投影按后端先扣真实 Settlement/Final allocation，再抵销同币反向 ExpenseDebt，之后应用 Usage；相反方向未结债务不能提前消费另一方向预存。退款只恢复实际预存 Usage，不改真实 Transfer。这些预存方向规则不能与不冲销已发生 Transfer 或不做跨币种抵销混为一谈；P2 只读取后端结果，不自行重算。子活动 Expense 的付款人和每个 Split 承担人都只能选已保存的 scope 成员，二者可以不同；AA、币种、历史锁和 Final 规则均由后端决定。

## 已核对的接口路径

| 目的 | 已核对路径 / 事实 | P2 使用边界 |
|---|---|---|
| Agent 会话与 Turn | `agent/app/api.py` 提供 `POST/GET /v1/sessions`、`GET /v1/sessions/{session_id}`、`POST /v1/sessions/{session_id}/turns`、`GET /v1/turns/{turn_id}/events`，以及 `/v1/turns/{turn_id}/resume/auth`、`/resume/clarification`、`/resume/proposal-adjust`、`/cancel` 和 `/v1/proposals/{proposal_id}/confirm`。 | 延用当前持久化与事件 API；模型/读适配是内部依赖，不另开写接口。确认路由目前故意返回 execution unavailable，P2 不得接通写入。 |
| Supabase 身份 | Agent `SupabaseAuthVerifier` 将已配置的项目 Auth endpoint 规范为 `GET /auth/v1/user`，并核验返回身份与已验证 access token 的 `sub`。 | 真实数据库请求继续携带这名用户的 bearer token。只用公开 client `apikey` 作项目路由，不把它误作用户身份；不得用 `service_role` 替代。 |
| App 活动事实 | main 的 `ActivityRepository` 从 PostgREST 读取 `activities`、`participants`、`activity_members`、`participant_claims`、`ledger_units`、`sub_activity_participants`、`activity_financial_status` 等。PostgREST 路径为 `/rest/v1/<table>`。 | Agent 需按具体查询再次校验用户成员身份、活动/对象关系及 RLS；UI context 只能作为待验证线索。 |
| App 消费事实 | main 的 `ExpenseRepository` 读取 `ledger_units`、`expenses`、`activities`、`payments`、`splits`、`participants`，并调用 `/rest/v1/rpc/get_expense_repayment_progress` 对应的只读 RPC。 | 只接实现查询所必需的实体；分页、关联和 financial lock 来源都需保留，不能只用列表缓存推余额。 |
| App 债务 / 结算事实 | main 的 `TransferRepository` 读取 `activities`、`participants`、claims，并优先调用 `/rest/v1/rpc/list_settlement_options`；仅在 RPC 缺失时才读 `bilateral_debts` 做旧 base-only 回退。`FinancialRemoteDataSource` 另有 `expense_debts` 读取。 | 核实当前 main 的接口版本、ACL、返回 DTO 和多币种语义。不要把 fallback 的 base-only projection 当成完整多币种事实；Agent 不自行净额、换算或计算欠款。 |
| App 大型活动预存事实 | main 的 `FinancialRemoteDataSource` 读取 `/rest/v1/prepayment_accounts`、`/rest/v1/prepayment_usages`，关联 `expense_debts`、`expenses`、`participants`、`activities`；新增预存预览走 `preview_prepayment`，但 P2 不调用任何写入 RPC。 | 这些表读取是否可由当前用户 RLS 安全承载须单独核实。若语义/API 无法表达，先提交 operation/schema 版本差异供 root 与 T1 同步；不以 `read.debts` 静默塞入未定义 prepayment DTO。 |
| LM Studio · 首选 | 统一指南 v0.4.2 规定 OpenAI 兼容 `POST /v1/chat/completions`，宿主可达地址以本机配置为准；Docker Desktop 常用 `http://host.docker.internal:<port>/v1/chat/completions`。 | 先复现兼容 endpoint 空 content 问题，分清 content、finish_reason、格式参数和服务端忙/超时；不能把 HTTP 200 当作成功。不得向 OpenAI 云端转发。 |
| LM Studio · 候选 | T0 的原生 `POST /api/v1/chat` 曾对 4B Q4_K_M 在 host/Docker 成功返回非空响应，之后定向卸载。 | 仅为已测候选路径。若采用，列明与首选 OpenAI 兼容格式的映射、差异、版本和回退；正式接口策略改变须 root 评审并同步指南/T1。 |

## P2 任务范围与文件边界

本阶段把 CAP01 的只读路径做成真实、可溯源的工程基线：当前身份的活动列表与 scope、消费详情、债务/资金/预存权威事实。现有六项 v1 operation 和已导出 `agent/contracts/v1.0.0` 是冻结基线。若新 operation 或 schema 是预存读取或分页/截断安全所必需，先在 `agent/docs/p2/CONTRACT-VERSION-DIFF.md` 写清旧/新字段、兼容策略、T1 manifest/prereg 影响、hash 变化和回退，再交 root 审查；root 与 T1 同步前不得悄悄改写 v1 frozen sources 或重新导出覆盖快照。

工程实现可涉及 `agent/app/model_provider.py`、`backend.py`、`ports.py`、`runtime.py`、`harness.py`、`components.py`、`settings.py` 和必要的 API 注入点。P2 测试新增到 `agent/tests/test_p2_*.py` 或专属只读夹具目录。实际任务报告与独立验收文档建议保存在 `agent/docs/p2/`；模型运行记录、数据库临时目录、日志及摘要放 `D:\AI\runs\shared-ledger\p2\`。不修改 main、不新增云端写权限或业务迁移。

此 Agent checkout 当前共享 P1/T1 未提交修改。T1 会话拥有 `agent/evaluation/`、`agent/dataset_contracts/t1/`、`agent/docs/t1/`、`D:\AI\runs\shared-ledger\t1*` 和相关 review artifacts；P2 不得覆盖它们，也不得更改冻结 T1 v1 manifest、prereg、source hashes、T0 证据、现有 evaluation/data 脚本。`agent/contracts/` 导出、`agent/README.md`、`agent/docs/dev-status.md` 与统一指南由 root 协调。若并行会话已改 app 或 contract 源，先记录新引用；需要基线时创建只读副本或版本化指纹，绝不把变化文件冒充现有 prereg hash。

## 分阶段交付与验收

### A · 基线复核和 CPU-only 实现

确认两个 checkout：Agent 为 `D:\project\Android\shared-ledger-agent` / `agent`，业务事实工作区为 `D:\project\Android\shared-ledger` / `main`。保留共享工作树现状。实现按 request/turn 的 identity context 安全传递 access token，backend 每次对 activity scope、实体关系和当前 RLS 结果重新校验；Token 不落盘、不共享到并发账号。生产配置默认关闭或显式启用，启动与 health 要分别表达 provider disabled/unavailable/ready 和 backend not-ready。

CPU/fake transport 覆盖 Auth user A/B 交叉、无 token/过期 token、伪造 Activity/Expense/Participant UUID、同一 ID 跨 Activity、业务拒绝、PostgREST schema/DTO、多个页面、RLS 返回空与拒绝。固定只读 HTTP/RPC allowlist，并用 transport 断言没有任何写入请求或写 RPC，允许的只读 RPC 必须单独列名与方法。测试不调用真实云端，不读 T1 sealed。

**阶段 A 通过：**调用链和 token 生命周期可审查；A/B 或 scope 不匹配绝不泄露账目；坏 token 与 RLS 拒绝明确失败关闭；读适配没有业务写路径；本地任务持久状态能在 provider/backend 离线时恢复；现有 P1 行为与持久化边界未被回归破坏。记录实际执行的定向检查，不重跑无关 T0/T1 测试。

### B · 真实 Auth 与 Supabase RLS 只读回放

资源允许时使用两个独立登录用户和隔离/既有受控数据。核对用户 A 可查自己的成员活动、B 不可通过伪造 ID/页面上下文查 A 的账本；同一用户跨活动 scope、非成员、被移除成员、非法或过期 token 均按真实 Auth/RLS 拒绝。所有业务请求显示当前用户 bearer，不带 service role。运行前确认环境、只读 SQL/RPC 名单、数据范围和 request log 过滤方式；禁止 reset、push/apply migration、写业务行或共享 cloud DB 重置。资源不足则完整保留 CPU 证据并明确标 `NOT_RUN_RESOURCE`，不宣称 CAP01 通过。

读取核对：活动/活动成员与 child scope；消费连同付款人、分摊、币种与必要关联；债务方向和币种；大型活动账户与已使用/退回的 prepayment facts。普通活动没有预存入口，任何普通活动请求不得读出/伪装预存能力。每笔金额、债务 `debtor → creditor`、币种、financial version、observed_at 和来源来自真实 DTO/RPC。Mock 或模型自己算出的结果不可标为真实后端证据。

**阶段 B 通过：**两身份 RLS 与跨 scope 负例通过；真实 request 日志仅有已 allowlist 的 authenticated GET/只读 RPC；真实结果逐项与 App/backend source DTO 一致；无任何后端写副作用。若 prepayment 当前用户只读 ACL 或权威 DTO 不足，记录确切缺口，不用更高权限绕过。

### C · LM Studio Provider 与限额

首先通过 `/v1/chat/completions` 完成兼容接口连通、空 content 根因记录、响应解析、reasoning/structured output 参数兼容和业务语义解析。适配器必须对空 content、`finish_reason=length`、无效 JSON、HTTP busy、连接离线、timeout、取消、响应过大给出区分状态；transport timeout 不自动重试同一生成，至多一次有界语法修正沿用已有 Parser repair 约束。提示/结果不落普通日志。Native route 可平行成为备选，但不能静默取代首选路径。

将生产 ModelProvider 配入 Runtime，覆盖 answer / clarify / read / propose，输入只由 Harness 构造。核实并外置每轮模型调用数、读取次数、修正次数、模型输出限制、输入/上下文 token 限额、并发数、超时、每用户 queue、全局 queue 和 busy 策略。统一指南给出的参考初值是单模型并发 1、最多 6 次模型调用、4 次读工具、格式修正最多 1 次、每用户 1 个运行和 1 个排队、全局队列 16；这些是工程初值，不是 P1 现成能力、模型 SLA 或质量保证。P2 应在首个模型输出前冻结实测配置，并在本地记录模型 key、实际模型/量化、上下文、prompt/provider 版本、温度、max output、endpoint 和时间。

**阶段 C 工程通过：**正在执行的 provider 请求有并发门；timeout/busy/取消不可泄漏 semaphore、重复请求或丢失 Turn；provider 离线后可恢复；超过任何预算都可解释停止；真实输出非空且能通过四语义 Parser。没有真实模型执行时只记 provider adapter/mock HTTP 测试通过，不写模型通过。

### D · 真实闭环诊断和质量报告

真实闭环必须至少包含：模型选择 read → Harness 用当前用户 token 执行真实只读调用 → 返回带 typed refs/来源/时间/版本的真实正文 → 后续模型调用消费正文 → 引用其事实给出 answer、必要时继续 read 或 clarify。数据大于单页时显式提供可恢复 continuation；context/truncation 必须绑定同一用户、活动、查询和 Turn。事实卡由 Harness 从 DTO 渲染，不允许模型自己补金额、债务方向、币种或求和替代业务后端。

业务事实卡验收至少覆盖：债务方向不反转；相同参与人多笔账不虚构合并金额；原币和 base currency 不混；过期 context/source version 失效并重读/澄清；真实 Activity/Expense UUID 不由模型输出决定。多候选或对象不在当前 activity/child scope 时必须澄清。活动切换后旧 typed reference 不能指向同号/同名的新实体。`propose` 可识别写意图但应明确告知当前阶段没有 live preview/confirmation/execution，不产生确认卡或写 RPC。

故障回放覆盖模型 busy/timeout/离线、读端 timeout/401/403/429、队列满、用户取消、容器/Runtime 中断、Token 过期后使用 `/v1/turns/{id}/resume/auth`、恢复后沿原 Turn/查询身份继续且不重复执行读副作用。恢复首先不能回模型重做任何已终态流程；此 P2 仍无业务 execution key、确认或写工具。

**阶段 D 工程通过：**有至少一条真实 Supabase 读闭环及其原始脱敏证据，所有判定基于真实 Backend output；分页/截断状态可辨且对象绑定稳定；所有异常恢复可审计；后端调用 allowlist 无写路径。模型质量单独报告，不因为链路工作便自动通过。

## 质量口径、资源门与禁止事项

T1 已预登记的参考指标（使用前核对当前获 root 认可的 prereg 版本）：schema validity ≥0.95、operation choice exact ≥0.90、required parameters exact ≥0.90、typed reference binding exact ≥0.90、supported complete task success ≥0.90 且 per-operation ≥0.90、false refusal ≤0.05、critical errors =0、单并发 P95 ≤60 秒、timeout rate ≤0.05。按 split/semantic/operation 分层，报告确切分子分母、macro 与 per-operation、Wilson 95% interval；不以合并均值遮住某项失败。P2 的模型诊断只代表所测模型/协议/provider 路径；样本门槛不够时为 `INSUFFICIENT_SAMPLE`。Harness 拦下虚构引用不是模型答对；对受支持合法请求的一律拒绝也不是安全通过。

T1 正式样本门槛仍为 validation/sealed 每操作每 split 至少 20 个独立状态族；现候选未达到正式发布门槛且尚有人审。P2 开发只能使用 validation（按现有 T1 授权仅诊断）或另建独立、非 sealed development fixtures。任何看过输出并用于 prompt/schema 调整的 fixture 不再作为独立评估证据。不得读取 sealed 正文或通过 runner 解析；sealed 一次性正式测评须等候选满足门槛并由 root 明确授权且先写 D 盘消费 ledger。不得调用 Teacher，不得训练或暗示已训练模型。

模型验证和真实业务验证是两道独立门槛：P2 工程/真实 Auth+RLS 通过可以作为进入 T2 的工程 baseline；模型质量差就进入 T2/T3 改进，不能伪称当前模型会可靠查询。真实 Backend 接口不可用或资源不足时，按阶段停在已证实的工程状态，明确未验收项。

**绝不可做：**调用写 RPC；service_role、管理员 token 或直连 SQL 绕过用户身份；对 main 作业务修改；新增或应用云端 migration；访问/消费 sealed 正文；请求 Teacher；替换或重写 T0/T1/P1 冻结资料；覆盖共享 `dev-status.md` / README / guide / canonical contract exports；kill game 或其他用户 LM Studio 进程；创建/消息发送到其他用户会话；提交或推送。

## 完成交接报告模板

```text
状态：P2 工程 / 真实 Auth-RLS / LM Studio provider / 真实闭环 / 模型质量（逐项 PASS、FAIL、NOT_RUN_RESOURCE、INSUFFICIENT_SAMPLE）
Agent checkout：branch / HEAD / 开始与结束 git status；没有对共享工作树执行 checkout/reset/clean/stash/commit/push
产物路径：实际改动源码、P2 tests、docs/p2、D:\AI\runs\shared-ledger\p2 下证据和 SHA-256
Auth/RLS：用户身份组合、实际 endpoint/只读请求 allowlist、scope 结果、无写请求证据
LM Studio：兼容/原生 endpoint、model key/格式/量化、prompt/语义版本、资源与限额；若 deferred，明确未运行原因
闭环：实际查询步骤、正文/引用绑定、分页/截断/金额事实卡结果、失败恢复和是否存在真实后端读证据
质量：按 T1 当前批准 prereg 的指标列 numerator/denominator、CI、每操作结果和样本不足项；sealed/Teacher 未触碰
契约差异：无则写无；有则列 docs/p2 差异文件与待 root/T1 同步的决定，不覆盖 v1 frozen files
剩余风险/下一步：只列真实未测项与明确阻塞，不把 CAP01–CAP17 写成通过
```
