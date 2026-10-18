# P1-03 持久化交接（主会话终审通过）

日期：2026-10-08（Asia/Shanghai）
状态：P1-03 持久化已于 2026-10-08 经主会话终审通过。此结论仅覆盖 P1-03 持久化范围，不改变其他 P1 验收状态；下一批 P1-04 尚未开始。

## 交付范围

实现集中在 [`store.py`](../../app/store.py)、[`ports.py`](../../app/ports.py) 与 [`001_initial.sql`](../../migrations/001_initial.sql)。默认组件装配创建 `SQLiteAgentStore`；lifespan 启动时执行迁移和完整性检查，关闭时只释放资源并保留数据库。`GET /health/ready` 只有真实 schema 通过检查且存储探测成功时返回 ready；health 明确 `schema_initialized=true`、`business_api_available=false`、`runtime_available=false`、`inference_available=false`。HTTP 仍只有 health 路由，服务只使用一个 worker，Provider/Runtime/Backend 均未启用。

SQLite 有恰好四张业务表和一张技术迁移记录表：

| 表 | 持久内容与约束 |
|---|---|
| `sessions` | owner、标题、时间、创建请求规范正文/hash、原创建响应，以及私有 `SessionPrivate` 类型化 JSON。创建请求键在同 owner 下唯一；session owner 和身份不可更新。 |
| `turns` | owner/session、首次提交正文/hash、state 与 state revision、step、execution identity/resolution、队列顺序与 claim lease、`TurnRecord` 和 `TurnCheckpoint` JSON。`UNIQUE(owner_user_id, client_request_id)` 令首次 Turn 请求键跨同 actor 的全部 Session 唯一。 |
| `events` | Turn 范围单调 seq、owner/session、类型化有限 payload；外键同时校验 Turn、Session 和 owner。更新与删除由触发器拒绝。Proposal 事件只存 Proposal ID/revision/operation，不存卡片正文或 nonce。 |
| `proposals` | owner/session/Turn、revision、status 和完整冻结 ProposalRecord；nonce 仅存当前提案行，原确认不可用回执随记录追加。部分唯一索引保证每个 Session 至多一个 pending Proposal；身份列不可更新。 |
| `schema_migrations` | 仅作迁移技术账本，保存 version、迁移名称（当前为 `initial`）、SHA-256 checksum 和 applied_at；SQLite `user_version` 与其版本同步。 |

`TurnCheckpoint` 是封闭的类型化私有 envelope，保存完整首次/恢复输入（含 UIContext）、accepted-at 和规范 payload hash、`ModelContext`、最近语义 decision / clarification、完整 typed read results、可信 policy evidence、推进 generation 和 model/read/repair counters。它不接受任意 `dict[str, Any]`，也没有 access/refresh token 或 proposal nonce 字段。`RequestReceipt` 继续使用冻结协议，仅保存 action/resource/key、payload hash、原响应、HTTP status 和时间；恢复输入单独保存在私有 checkpoint，因此原回执可用于重放而不丢用户输入。

## Store 原语和不变量

`AgentStore` 在 ports 中为后续 Runtime/API 定义了 typed 创建、提交、读取、状态迁移、checkpoint、动作回执、提案调整、不可用确认回执、恢复扫描、恢复中断任务和队列 claim/release 签名。SQLite Store 的公开方法包括 `create_session`、`submit_turn`、`get_session/get_turn/get_proposal`、`read_turn_view`、`transition_turn`、`save_checkpoint`、`accept_turn_action`、`adjust_proposal`、`record_confirmation_unavailable`、`list_recovery_candidates`、`recover_interrupted_turns`、`claim_next` 和 `release_claim`。

每个动作先用 owner、action scope、resource、client request id 和 NFC 规范 JSON payload hash 查找已有回执。完全一致时先返回原响应，不再按当前 state 验证或重复写；同键资源、正文或 UIContext 不同即冲突。session 创建、首次 Turn 提交、resume clarification/auth、proposal adjust、cancel 和冻结的 confirmation-unavailable 响应均持久原始响应。首次提交的 SQL 唯一键跨同 owner 的 Session；恢复动作的回执写在 Turn JSON，确认不可用回执写在 Proposal JSON。未来 AuthVerifier 必须把可信 owner 作为方法参数传入；Store 不从客户端 request 推导身份。

所有写操作采用 SQLite 参数绑定和独立 connection，connection 启用 foreign keys；数据库使用 WAL 与 `synchronous=FULL`。短写事务使用 `BEGIN IMMEDIATE`，由数据库锁、唯一约束和 CAS 协调多个 Store 实例，不依赖进程内锁。一个事务中分配事件 seq、追加事件、更新状态/私有数据和回执，提交前故障统一回滚。首次提交的队列顺序及 pending Proposal 限制由数据库约束原子竞争。Turn 状态迁移始终调用冻结 `validate_state_transition` 等 helper，并 CAS `state_revision` 与 `checkpoint_revision`。

同态 checkpoint 使用独立的 `checkpoint_revision` CAS，同时匹配当前冻结 snapshot 的 state/state revision；不伪造冻结状态表没有的 self-edge，也不递增 `state_revision`。因此同状态保存 ModelContext、clarification、read result、references、证据、输入历史及调用计数可被后续 Runtime 恢复，并和同批 events 原子提交。推进 generation 仅由 clarification 或 proposal adjustment 输入增加；auth、restart、cancel 不清预算或生成新 generation。提案调整按同一事务验证并提交 `WAIT_CONFIRM → RUNNING → WAIT_CONFIRM` 两条冻结合法边（revision +2），保存两条 status event、替换 Proposal event、proposal revision/新 nonce、request receipt 和完整调整输入。已有 execution identity 的 Proposal 不可调整。

引用和 read result append-only，绑定来源 Turn、actor/resource、类型、scope、source result、context version 和事实映射；event 中的证据引用在提交时必须指向当前 Turn 已持久数据。Proposal 事件引用必须对应同一事务持久的 pending Proposal。进入 `WAIT_CONFIRM` 必须存在同 owner/Turn 的 pending Proposal；允许 auth-required 状态精确暂停到 `WAIT_INPUT(resume_state=WAIT_CONFIRM)` 并保留同一个 Proposal/nonce，认证恢复时回到原等待点。终态取消会在同一事务关闭 pending Proposal 并清 nonce。普通查询或其他 Turn 不覆盖待确认提案。

初始化按单条 SQL 语句解析迁移文件，不使用会隐式提交的 `executescript`。迁移 version/checksum、schema_migrations、`user_version` 和与安装迁移构造出的 `sqlite_master` schema fingerprint 必须完全相符；启动另做 SQLite integrity、foreign key 和全行 typed JSON / SQL projection / owner / status event 校验。未来 schema、迁移不完整、checksum 漂移、表/索引/触发器缺失或 JSON 与 SQL 投影不一致均 fail closed，不自动修复或删除旧数据。启动验证在一致读事务中完成。

恢复扫描返回 typed disposition，不自行推进用户等待或确认：`QUEUED` 是 queued，未分配 execution 的 `RUNNING` 是 resume_planning，`WAIT_INPUT`（包括 assigned execution 的认证暂停）是 await_input，`WAIT_CONFIRM` 是 await_confirmation，`EXECUTING/RECOVERING` 是 reconcile_execution。只有显式 `recover_interrupted_turns` 会把崩溃留下的 `RUNNING→QUEUED` 或 `EXECUTING→RECOVERING` 与 status event 一起提交。`claim_next` 通过数据库 CAS 领取最旧 QUEUED Turn，并发 Store 只有一个当前 claim；该队列原语目前不实施 P1 指南中的 per-user/global 配额。`UNKNOWN` 执行结果保持 `RECOVERING` 和原 execution key，不设为 FAILED、不回模型、不自动确认或真实执行。普通 Store transition 不可分配 execution identity；只有隔离测试 fixture 可注入。

## 验证证据

从仓库根目录使用已有 `agent/.venv` Python 3.12：

```powershell
& .\agent\.venv\Scripts\python.exe -m pytest -q agent\tests
& .\agent\.venv\Scripts\python.exe -m compileall -q agent\app agent\tests
& .\agent\.venv\Scripts\python.exe -m agent.app.export_contracts --check
```

本次实测：`39 passed`；compileall 成功；协议导出器输出 `contract snapshot matches manifest: ...\agent\contracts\v1.0.0`。主会话执行 `D:/computer/Hermes/uv/bin/uv.exe lock --check --project agent`，解析 32 packages 并通过；P1-01 export `--check` 也通过，冻结 contracts、fixtures、snapshots、requirements 与 toolchain 均未变更。

新增/更新的测试覆盖不同 Store connection 并发首次请求唯一键、跨 Session 同 owner 冲突、body/context hash 冲突、跨 owner 隔离、CAS/claim 单赢家、resume 输入与精确原响应跨重启、Proposal nonce/references/read results 持久化、pending Proposal 与 cancel/adjust 的原子竞争、auth pause/resume 后预算与 execution identity 保留、UNKNOWN outcome 恢复、迟到输出被 cancel 的 CAS 阻断、migration/checksum/schema drift/future version/SQL projection fail-closed、故障注入回滚和进程退出前后状态/events 一致。P1-02 原有 health/service tests 保留；P1-01 离线协议测试也继续运行，没有删除既有重要验证。

主会话 2026-10-08 独立复核当前版本：全套 39 项通过、compileall 与 export/lock check 通过；额外用双 Store 做 8 轮 adjust/cancel 竞争，每轮单赢家且状态、事件、proposal/nonce 原子并跨重启一致；外部 `Popen.terminate` 提交前恢复为 0 条、提交后恢复为 1 条并可 replay 原回执；独立 auth 场景覆盖 pending Proposal auth 暂停、重启、回到精确 WAIT_CONFIRM、原回执重试、pending nonce 不变且 generation/counters 不重置。破坏 `schema_migrations` checksum 后启动拒绝，且脱敏错误没有损坏或删除已有数据库。真实 Uvicorn smoke 显示 `schema_initialized=true`、business/runtime/inference 均 false；外部数据库写锁下 live 约 15 ms 返回 200、ready 返回 503，解锁后 ready 恢复 200。此类局部数据库/服务测试不代表全套 P1-A01–A10 或产品验收通过。

## 限制与下一批

当前没有 FastAPI 业务路由或 AuthVerifier；Store 方法参数的 owner 是未来认证边界的输入，不能单独证明 API 鉴权。没有 Harness、运行时循环、真实模型/只读业务 adapter、云端写入、确认执行、部署镜像、备份/恢复演练、限流或队列配额；恢复扫描与 claim 是供后续 Runtime 使用的存储原语，不能自行运行等待任务。确认能力在服务边界仍不可用。下一批 P1-04 身份与 API 尚未开始；P1-05 Runtime 和 P1-06 部署验收保持未开始/未测。
