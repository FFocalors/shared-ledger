# P1-01 协议冻结交接

日期：2026-10-07（Asia/Shanghai）  
协议版本：API `1.0.0` / semantic `1.0.0` / operations `1.0.0` / trajectory `1.0.0` / execution-key `1`  
状态：P1-01 离线协议源、快照、轨迹与静态约束检查已实现，并经主会话独立终审通过。P1 其他批次及运行验收仍未测。

## 范围与可作出的结论

本批冻结独立、版本化的 Pydantic 协议源、确定性 JSON Schema/OpenAPI 快照、CAP 注册表、状态转移表、离线轨迹和静态验证。验收结论只适用于这些离线输入：模型语义、结构化 API 请求、类型化绑定、状态/版本/digest helper，以及 mock 轨迹能够通过所述验证。

当前没有 Agent 服务、FastAPI 路由、Authorization 校验器、SQLite 四表、运行中的 Harness、模型 provider 或业务 adapter。因此这不是 API 安全验收、服务恢复验收、数据库唯一约束/CAS 验收、真实权限验收、业务执行验收或 T1 全部完成结论。运行依赖与测试仅在本协议工具链中固定；未进入服务骨架、训练环境或系统 Python 配置。

## 源文件与版本层次

协议源位于 [`contracts.py`](../../app/contracts.py)，最小包入口为 [`app/__init__.py`](../../app/__init__.py)。确定性导出器和四个轨迹构造器分别是 [`export_contracts.py`](../../app/export_contracts.py) 与 [`mock_fixtures.py`](../../app/mock_fixtures.py)。API、semantic、operations 和轨迹版本目前分别是 `1.0.0`；执行键规则单独标为版本 `1`。移动端请求携带 API/semantic/operations 三个版本，轨迹版本只用于离线 fixture，不要求客户端协商。

旧 `docs/ai` 六类模型协议未导入，也未修改。模型 semantic 根类型封闭为 `answer`、`clarify`、`read`、`propose` 四类。未知字段、未知分支和未注册操作拒绝。回答文本不允许 URL 或 credential-like JWT；账务/政策事实用当前 ModelContext 内的 typed citation，纯对话回答使用 `basis=conversation` 且不携带事实 citation。模型没有 actor、confirmed、任意写工具、SQL/RPC/URL 参数或原始业务 UUID 字段；模型提出的写意图只是提议。

## Schema、跨字段校验与请求适配

导出的每个 JSON Schema 声明 Draft 2020-12，负责线上的结构约束：类型、必填、长度/范围、枚举、discriminator、有限字符串格式及 `extra=forbid`。JSON Schema 不表达金额 Decimal 求和、字段间操作匹配、状态迁移的身份不可变性、当前用户授权、条件事务或后端 CAS。

Pydantic 源模型负责确定性的局部跨字段不变量，例如支付/分摊金额守恒、语义操作与参数 schema 对应、当前 context 内 citation/ref 类型、preview 变化与前后快照相等、Proposal 与 command/precondition/policy 版本绑定、状态字段组合和回执类型。Harness helper 还需在认证和权限检查之后，针对当次数据库读取验证语义、权限、锁、持久引用、请求重放、revision 条件和稳定执行身份。[`validation-layers.json`](../../contracts/v1.0.0/validation-layers.json) 按这三层列出责任。

JSON Schema 与 Pydantic 结构校验本批共用同一 Pydantic 源。API body 由框架解析成 Python dict 的路径单独使用 `TypeAdapter(RequestType).validate_python(parsed_dict, from_attributes=True)` 验证；Wire UUID、枚举、日期和时间只接受明确的 JSON 字符串格式。该路径与 `validate_json` 对所有 API request 正例等价，仍拒绝 float/int 混用、字段额外、actor 自报等输入。P1-02 负责服务装配、配置/lifespan 和健康检查；P1-04 实现 API 路由与认证/owner scope 时必须集成这一 parsed-dict 适配契约。仅修改模型的 `model_validate` 不够。

## API 与去重契约

OpenAPI 快照描述以下接口：

| 方法与路径 | 请求/响应契约 |
|---|---|
| `POST /v1/sessions` | 创建会话，201 |
| `GET /v1/sessions`、`GET /v1/sessions/{session_id}` | 列表与读取，200 |
| `POST /v1/sessions/{session_id}/turns` | 提交文本及非可信 UI hints，202 |
| `GET /v1/turns/{turn_id}/events?after_seq=…` | 按单调 seq 轮询，200 |
| `POST /v1/turns/{turn_id}/resume/clarification` | 原样提交澄清文本，Harness 之后再解释 |
| `POST /v1/turns/{turn_id}/resume/auth` | 用新的 Authorization 继续精确保存点 |
| `POST /v1/turns/{turn_id}/resume/proposal-adjust` | 原样提交提案调整文本，之后重新理解和生成预览 |
| `POST /v1/turns/{turn_id}/cancel` | 返回 `CancelTurnResponse`，不是 mutation-accepted 回执 |
| `POST /v1/proposals/{proposal_id}/confirm` | P1-01 固定返回 501 能力关闭；不描述 202 成功 |

除成功响应外，契约包含请求错误/冲突、未认证、无权限、资源缺失、限流和依赖不可用响应。`Authorization` 是身份唯一来源；session/turn/proposal owner 必须由 verifier 得到，不能由 UIContext 或模型语义决定。UI page、选中实体、过滤器是提示，服务端按当前 owner 权限重新核实。访问令牌只短暂存在验证边界，不得进入请求快照、四表 payload、事件、模型上下文或日志。

每个可重试动作有 `client_request_id`。规范 hash 是 UTF-8 NFC 规范化 JSON：递归排序键、紧凑分隔符、保留 null，并覆盖 API 版本、动作 scope、resource id 和完整请求正文（包括 UI context）；Authorization 不在正文 hash 中。同 owner/action/resource/request id 且 hash 相同，返回首次保存的原响应快照；同 key 正文/context 不同，返回冲突。首个创建/提交分别以 owner+create request id、owner+turn submit request id 唯一；resume/adjust/cancel 回执放在 turns 记录并按 owner、action、turn、request id 唯一；confirm 回执放在 proposals 记录并按 owner、proposal、request id 唯一。四表与唯一索引是 P1-03 实现约束，本批只有类型和纯函数，没有数据库。

## 状态、重启和执行身份

私有 Turn 状态为 `QUEUED/RUNNING/WAIT_INPUT/WAIT_CONFIRM/EXECUTING/RECOVERING` 及终态 `COMPLETED/CANCELLED/FAILED`。`WAIT_INPUT` 要有明确的 `missing_fields` 或 `auth_required`、step 和 resume checkpoint；待确认是 `WAIT_CONFIRM + confirm_required`，不借用澄清槽。`STATE_TRANSITIONS` 导出允许的状态边，Pydantic snapshot 与 transition helper 进一步约束 revision 和身份。

无 execution identity 的普通规划可在重启后回到原 `QUEUED/RUNNING` 检查点；澄清文本恢复原规划路径。auth 等待保存精确 checkpoint，允许 `WAIT_CONFIRM → WAIT_INPUT(auth_required, resume=WAIT_CONFIRM) → WAIT_CONFIRM`，不能清掉待确认提案。新的 execution identity 只能从 `WAIT_CONFIRM` 确认边界分配。一旦存在 identity，actor、proposal/revision 与 execution id 不变，不得回到 `QUEUED/RUNNING/WAIT_CONFIRM` 或交模型重规划。`EXECUTING/RECOVERING → WAIT_INPUT(auth_required, resume=RECOVERING) → RECOVERING` 保留原 identity 和结果状态。结果 `unknown` 只留在 `RECOVERING` 或其 auth 暂停状态，不得伪装 `FAILED`。

`execution_id` 固定为 UUIDv5：固定 namespace `7fd9a109-cad5-5a6a-a6ee-4b2f0c8f4b8d`，name 编码 execution-key 版本、operations 版本、认证 actor UUID、proposal UUID 和 proposal revision。它是稳定标识，不是秘密；相同输入可在重启和旧备份恢复后重建。确认/调整/取消均要求 expected state/proposal revision；参数调整只产生一个新 revision，旧 nonce 失效；同一 Session 同时最多一个 pending Proposal。普通查询不覆盖 pending proposal。已执行任务取消须先等待原执行对账/关闭；未分配执行 id 的取消可终止规划，迟到模型结果必须被忽略。DB CAS、真实 close_execution 与云端幂等仍留 P1-03/P3；纯函数不证明跨进程原子性。

财务字段用规范十进制字符串。Decimal 金额不接受 float；Activity `financial_version` 是十进制字符串 `0..9223372036854775807`，Expense `version` 是 `1..9223372036854775807`，以免 JS 客户端丢失 bigint 精度。preview 用完整 typed before/after 快照以及按字段类型化 changes；validator 比较 changes 与快照的差异，检查必要快照、付款/分摊来源、金额守恒和版本递增。canonical command 的 participant/ledger/expense 是解析后 UUID，不留模型 ref。确定性 digest 编码为含 digest 格式版本、API/semantic/operations 版本、policy version、规范化 command 与完整 preconditions 的 NFC JSON（排序键、紧凑分隔、UTF-8），再取 SHA-256；digest 不授予执行能力。

业务规则依据 main 工作区 [`BUSINESS_LOGIC.md`](D:/project/Android/shared-ledger/docs/backend/BUSINESS_LOGIC.md)、[大型活动预存规则](D:/project/Android/shared-ledger/docs/ai/PREPAYMENT_LARGE_ACTIVITY_RULE_2026-10-06.md) 与 Agent 工作区 [development-workflow.md](../development-workflow.md)：普通活动没有预存；预存仅限大型活动，子活动付款/分摊需在其 participant scope 内；Expense 财务锁禁止财务修改，且没有 restore 操作；D4 不作全局禁用，但 Member/Creator、锁、确认和后端权限仍须通过。业务 Expense RPC 没有调用方 `expected_version` CAS，因此这里的 expected version 只是 Agent 前提快照，不能声称后端具备并发保护。

## 事件、引用与提案卡

事件 discriminator 固定为 `status/message/clarification/proposal/execution_result/error`，seq 在 Turn 内单调且 poll 使用 `after_seq`。持久 Proposal event 只含 proposal id、revision、operation，不含卡片正文或 nonce。当前授权和 scope 检查通过后，API 才从现有 Proposal hydrate 对应 revision 的卡片；过期/失效/终态卡片没有 nonce。确认 nonce 的 response-card schema 标为敏感且禁止模型/event/log；confirm request 字段才是 `writeOnly`。P1-01 mock 卡只有 `simulation=true`、没有 live nonce，confirm 明确能力关闭。

`ToolReadResult` 包含完整 typed facts、`observed_at`、context version、operation、内部 result id/ref 与 simulation 标志；模型只能见 typed result ref 和安全 model reference。类型化实体、事实 evidence、read-result token 在 Turn 范围内绑定到 UUID、来源 result、scope、观察时间与 context version。重排、resume、重启复用同一 ref；不同 Turn 不复用旧 binding。`validate_model_context_bindings` 检查可见 token 是否精确属于持久白名单，以及 fact citation 是否仍指向相同类型、同一 source result/version/scope 和实体映射。它必须由后续 Harness 在组装模型输入时调用；offline helper 不是实际存储保证。

模型 context 的权限集严格来自 Harness scope。可信 `PolicyEvidence` 给不依赖账务记录的规则解释提供 citation；纯会话/闲聊使用 `basis=conversation`，不伪造账务 fact citation。`simulation` 是 fixture/tool adapter 的可信标注，不是模型可输出的字段。模拟证据不能声称真实读或真实写。

## CAP 注册表

CAP01–CAP17 均在固定注册表出现。`availability` 描述此协议阶段当前能否作为 mock 语义读取/提议；`target_stage` 是未来交付阶段，两者分开。当前 semantic read 只开放活动/消费/债务三种读取；expense create、允许的 expense financial update 和 presentation update 只允许模拟提议；所有 CAP 的 `execution_enabled=false`。CAP01 目标 P2；CAP07/08 目标 P3b+T3；CAP02–06 和 CAP09–17 目标 P5/T4。未实现能力显式 unavailable，底层 RPC 名称不作为模型操作。普通活动预存、restore、退款、结算等均不在首批操作表中。

## 导出快照和可复现性

[`contracts/v1.0.0/`](../../contracts/v1.0.0/) 包含各根 JSON Schema、OpenAPI 3.1、CAP 注册表、状态转移表、校验层次和 4 个 Mock 轨迹。导出器会把 `$defs` 和 discriminator mapping 转成有效 OpenAPI components pointer，并对 `$ref` 与 mapping 递归解析；GET 轮询返回 200，confirm 只声明 501。JSON 输出为 UTF-8、键排序、两空格缩进、末尾一个 LF。manifest 对每个生成文件计算实际输出字节 SHA-256；对协议源、导出器、fixture 和依赖/运行时版本文件先将 CRLF 或孤立 CR 规范成 LF，再算 SHA-256。manifest 的 `self_hash` 为 null，避免自哈希循环；`--check` 同时比较快照、manifest、每个实际 hash 和意外文件。

最小隔离依赖见 [`requirements-contracts.txt`](../../requirements-contracts.txt) 和 [`toolchain-contracts.json`](../../toolchain-contracts.json)：Python `3.9.13` 执行，Pydantic `2.13.4`、jsonschema `4.25.1`、pytest `8.4.2`。这些文件不代表 FastAPI 服务锁文件。

## 离线验收证据

在 `D:\project\Android\shared-ledger-agent` 执行：

```powershell
python -m py_compile agent/app/contracts.py agent/app/mock_fixtures.py agent/app/export_contracts.py agent/tests/test_protocol_contracts.py
python -m pytest agent/tests/test_protocol_contracts.py -q -p no:cacheprovider
python -m agent.app.export_contracts --write
python -m agent.app.export_contracts --check
```

本批执行结果：`py_compile` 成功；pytest 为 `11 passed`；快照导出成功；`--check` 输出 `contract snapshot matches manifest: D:\project\Android\shared-ledger-agent\agent\contracts\v1.0.0`。manifest 含 55 个生成文件与 5 个源 fingerprint，实际重算无 hash mismatch。主会话独立复跑 pytest 得到 `11 passed`，`--check` 通过；独立解析 OpenAPI 的 387 个内部引用均成功，也验证源 fingerprint 漂移会被 `--check` 拒绝。actor/direct write/raw RPC 及 bool、float、string revision 负例均拒绝。轨迹先经 JSON Schema，再经同一个 `MockTrajectory` Pydantic 模型验证；反向 read→answer 顺序、未来事实注入、错误 request 类型、未知字段/操作、不守恒金额、绑定漂移、unknown→FAILED、错误 preview changes、revision 链断裂均有拒绝用例。

这些结果不能替代运行时验收。P1-02 实现服务配置、装配、lifespan 和健康检查；P1-03 实现四表事务、唯一索引、持久事件与 CAS；P1-04 集成 FastAPI 路由、AuthVerifier、owner scope 和 parsed-dict 请求验证；P1-05 接入 Harness/模型与 read adapter、取消迟到输出和恢复；P1-06 才能做运行部署与进程重启验收。P2/P3 再分别验证真实只读、可信 preview/业务写保护、业务 RPC 与云端 receipt/close_execution。

## 本批来源

- Agent [P1 开发计划](P1_DEVELOPMENT_PLAN.md)、[开发指南 v0.4.2](../shared-ledger-agent-development-guide-v0.4.html) 的 P1、components/state/protocol、R01–R21。
- Agent [CAP 能力映射](../p0/capability-map.md) 与 [总体开发流程](../development-workflow.md)。
- Main 工作区的业务规则 [`BUSINESS_LOGIC.md`](D:/project/Android/shared-ledger/docs/backend/BUSINESS_LOGIC.md)、[大型活动预存规则](D:/project/Android/shared-ledger/docs/ai/PREPAYMENT_LARGE_ACTIVITY_RULE_2026-10-06.md) 和 Expense RPC/version 迁移源码。

此交接只记录 P1-01 协议离线证据。P1-02 到 P1-06 与上述所有真实 API/数据库/权限/恢复验收仍保持“未测”；协议快照完成不代表 T1 全部完成或训练验收通过。
