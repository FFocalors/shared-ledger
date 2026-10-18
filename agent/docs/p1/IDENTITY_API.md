# P1-04 身份与 API 交接

日期：2026-10-08（Asia/Shanghai）  
状态：2026-10-08 主会话终审确认 P1-04 代码与本地模拟授权范围通过。本文件只记录 P1-04 范围证据；正向真实用户 Auth smoke 未测，P1 整体及其他阶段验收不由此推定通过。

## 实现范围

`app/api.py` 提供冻结的 `/v1` 路由：

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/v1/sessions` | owner-scoped 分页列表 |
| POST | `/v1/sessions` | 持久创建会话 |
| GET | `/v1/sessions/{session_id}` | owner-scoped 状态详情；仅返回当前 scope 可见的卡片 |
| POST | `/v1/sessions/{session_id}/turns` | 原子持久化输入并返回 `QUEUED`，不调度 Runtime |
| GET | `/v1/turns/{turn_id}/events` | 单一 SQLite 视图中的事件分页、状态和当前可见提案卡片 |
| POST | `/v1/turns/{turn_id}/resume/auth` | 按冻结 checkpoint 恢复原阶段；已有 execution 保持原 key 并进入对账 |
| POST | `/v1/turns/{turn_id}/resume/clarification` | 原样持久化澄清文本和原响应回执 |
| POST | `/v1/turns/{turn_id}/resume/proposal-adjust` | 通过注入的 preparation port 准备新 revision；默认不可用时返回 typed 503 |
| POST | `/v1/turns/{turn_id}/cancel` | 持久取消本地未执行任务；已有 execution 只保留同 key 对账 |
| POST | `/v1/proposals/{proposal_id}/confirm` | 执行能力关闭；经当前身份、owner、scope 和回执检查后持久记录原响应并返回 501 |

请求 body 先用严格 JSON 解析（拒绝重复键、NaN/Infinity 和非对象），再通过缓存的 `TypeAdapter(RequestType).validate_python(parsed_dict, from_attributes=True)` 验证冻结类型。分页 query 先检查重复/未知字段并显式转换整数，再用相同 TypeAdapter 路径验证。`/v1` 的未知路由和不允许的方法也返回 `ApiErrorResponse`，不暴露框架默认 `detail`。请求限制为配置字节上限，API 使用进程内 IP/actor 固定窗口限流；列表游标含 owner 和 HMAC，事件使用冻结的 `next_after_seq` 语义。同步 Store、scope 和 proposal preparer 均在线程池执行，因此 SQLite busy 不阻塞 `/health/live`。

`POST /turns` 只提交持久 `QUEUED` 任务。Auth resume 按已存 `ResumeState` 精确恢复，包括 `QUEUED`、`RUNNING`、`WAIT_CONFIRM`；已分配 execution 时保持原 `execution_id`、未知结果和检查点预算，恢复到 `RECOVERING`。取消通过 SQLite CAS 屏蔽迟到输出。调度与模型运行不属于本批。

`POST /proposals/{id}/confirm` 永远不触发业务写入。Fresh Auth、owner 和 activity scope 校验后，先检查 request receipt，再应用当前 gate/revision/nonce/expiry 条件；记录请求 hash 和冻结原响应，不保存请求 nonce。重复请求返回原 501。后端 proposal 的 `agent_disable_revision` 必须匹配服务端控制版本；simulation proposal 没有该 precondition/nonce，生命周期策略版本绑定留给 P1-05 Runtime。

## 身份、权限与配置

`SupabaseAuthVerifier` 将 Bearer token 通过固定配置的 Supabase `/auth/v1/user` 远端验证；只在远端成功后读取经验证的 JWT claims。支持签名算法由 Auth 服务决定，服务端不把任意解码的 JWT 当身份。校验用户 UUID、JWT subject/role/aud、`is_anonymous`、`deleted_at` 和封禁时间，并拒绝非有限 exp/iat/nbf。HTTP 请求禁用环境代理且不跟随 redirect，避免把 token 发送到环境代理或重定向目标。Auth 连接/超时与无效身份分别映射为 503 和 401。Access token 不写入 SQLite、事件、检查点、日志或模型上下文；不保存 refresh token。

默认 ScopeAuthorizer 是 fail-closed 的未配置适配器。创建/加入和本人状态元数据不要求 activity membership；读取已存事实、preview/card/nonce、clarification、proposal adjust、confirm 前重新按当前 scope 授权。Scope 暂不可用时，非活动事实的 owner 状态、认证恢复和取消仍可用；事实事件和卡片不会因撤权泄漏。API 用例中的双用户 Auth、Scope 和 Agent control 均通过显式依赖注入，属于模拟授权证据，不是生产真实业务授权。UIContext/activity ID/客户端 role 均不提供授权。

`.env.example` 说明以下变量：

| 变量 | 作用 |
|---|---|
| `AGENT_SUPABASE_AUTH_BASE_URL` | 固定 Auth 项目 URL；留空时业务 API fail-closed |
| `AGENT_SUPABASE_API_KEY` | 项目 publishable/anon API key；不能用作用户 Bearer，也不接受 secret/service-role key |
| `AGENT_ALLOW_INSECURE_LOOPBACK_AUTH_HTTP` | 默认 false；仅本地 loopback 明确 opt-in 后允许 HTTP |
| `AGENT_AGENT_ENABLED` / `AGENT_DISABLE_REVISION` | 服务端 Agent 规划开关及关闭修订；独立于 `AGENT_PROVIDER_MODE=disabled` |
| `AGENT_CURSOR_SIGNING_SECRET` | 至少 32 UTF-8 字节；未配置时游标签名密钥仅在本进程有效 |
| `AGENT_MAX_REQUEST_BYTES` / `AGENT_API_REQUESTS_PER_MINUTE` | JSON payload 上限与 IP/actor 基础限流 |

密钥采用 `SecretStr`，配置错误只显示变量名，不打印值。Uvicorn access log 显式关闭，避免默认记录原始 path/query 中意外携带的 access token；异常响应和 lifespan 错误均使用脱敏消息。健康端点不调用 Supabase Auth 或 LM Studio；未配置 Auth 不影响本地 health。配置版 AgentControl 是服务端静态配置：操作方每次关闭 Agent 时必须递增 `AGENT_DISABLE_REVISION`，重新开启时保留该值、不能回退；仅切换 `AGENT_AGENT_ENABLED` 不足以使旧 backend proposal 失效。运行进程不提供偏好持久化，后续持久控制适配器仍需遵守单调版本规则。

## 验证证据

本地命令（Python 3.12，`agent/.venv`）：

```powershell
& 'D:\project\Android\shared-ledger-agent\agent\.venv\Scripts\python.exe' -m pytest -q agent\tests\test_identity_api.py agent\tests\test_auth_verifier.py
# 45 passed

& 'D:\project\Android\shared-ledger-agent\agent\.venv\Scripts\python.exe' -m pytest -q agent\tests
# 84 passed
```

覆盖包括 A/B owner 隔离、Auth 错误映射、严格请求验证、确认 501/hash-only 回执、认证恢复各 checkpoint、澄清原文/幂等重放、preparer 注入后的调整与 nonce 轮换、调整默认不可用、取消与迟到输出 CAS、scope 撤权、游标 owner 绑定/包含点字节的 MAC、分页边界、限流、SQLite busy 时 live 可响应。Auth/API 定向 45 项通过（含 env example 启动边界）；API 与启动配置增量定向 12 项通过。主会话最新全量为 84 passed，包含最终访问日志关闭与单调 `disable_revision` 改动。测试不触碰业务数据库写路径。

**远端 Auth 证据与模拟验证分开：**主会话只读检查的本地 Supabase `127.0.0.1:54321` `/auth/v1/health` 返回 200（GoTrue v2.195.0），`/auth/v1/.well-known/jwks.json` 返回 200，包含一个 EC/ES256 公钥。现有 seed 用户的 password login 返回上游 HTTP 500；Auth 容器日志显示 NULL `confirmation_token` 转字符串扫描错误。没有获得真实用户 token，因此正向 `/user` 身份 smoke 未测。未修复或重置共享 Auth 数据库，也未创建用户；publishable/anon API key 不能作为用户 Bearer。健康/JWKS 连通不能替代正向 Auth 身份验证。

## 真实本地 Auth 补充验收（2026-10-10）

上面的 2026-10-08 观察和未测结论保留为历史记录。随后用本地 Auth API 新建的两个唯一测试用户完成真实 signup、password login 和 `/auth/v1/user` 验证（均 HTTP 200，用户 ID 匹配）。隔离 Agent 使用临时 SQLite、`AGENT_AGENT_ENABLED=false` 和 `AGENT_PROVIDER_MODE=disabled`：A 创建/list/get session 为 201/200/200；B list 返回空、跨 owner get 返回 404；缺失/无效 token 均 401；规划被 409 `agent_disabled` 拒绝且没有 turn 写入。两个测试用户已 logout（204）并按精确 ID 删除（200），临时进程和目录已清理。完整状态、边界和复跑命令见[真实 Auth 报告](REAL_AUTH_SMOKE.md)，脱敏 29-check JSON 见[真实 Auth 证据](evidence/P1-04-RealAuthSmoke-20261010-013323.json)。

真实 Auth-issued expired token 未测（`NOT_TESTED`）；[`test_untrusted_or_ineligible_user_claims_are_rejected`](../../tests/test_auth_verifier.py) 的 `exp=1` 是使用不可信测试签名的模拟 claim 覆盖，不是 Auth 服务签发的过期 token。原 seed 登录 `confirmation_token` NULL / HTTP 500 仍是未修复的历史上游问题。Smoke 进程 stdout/stderr 被丢弃，因此不声称扫描该次运行日志。

## 主会话独立复核证据（2026-10-08）

以下是主会话独立运行和检查的结果，与上面的本地自动化用例分开记录：

- 主会话最新全量测试：84 passed，包含 `access_log=False` 和单调 `disable_revision` 最终改动。
- `export_contracts --check` 通过；`uv lock --check --offline --project agent` 通过（32 packages resolved），没有锁文件漂移。
- 78 个保护文件哈希对照通过：冻结 sources/contracts、SQLite migration 001、历史 P1/P0/shared 文件均匹配；仅并行 T0 README 有外部变化，本任务未修改或回退该变化。
- 独立真实 TCP HTTP 检查使用显式注入的模拟身份 fixture：A/B 的 session list/get、turn poll 和 cancel 隔离；并发 submit 相同键返回同一原回执、相同键不同正文返回 409；无效 token 返回 401 且不丢任务；cancel 重放返回原回执。
- 停服重开后，在 Agent 关闭状态下，create/submit/cancel 原回执仍可重放，新 submit 返回 409；SQLite 写锁期间 `/health/live` 小于 500 ms 返回，阻塞写请求返回 503。
- 独立凭据扫描通过：SQLite 四表 JSON 列未发现 access token、Bearer 或 refresh token；检查数据为 1 Turn、2 events。

TCP HTTP 与凭据扫描均使用测试数据，不是生产 Supabase 身份或业务 scope 的认证证据。

## 留给后续阶段的边界

- P1-04 代码与本地模拟授权范围已由主会话通过；正向真实本地用户 Auth smoke 后续于 2026-10-10 通过限定范围补验收（见上方报告），真实 Auth-issued expired token 和生产 Scope 仍未验证。
- 实际活动授权适配器和业务事实读取仍未交付；生产 Scope 当前 fail-closed。测试中的 scope fixture 只验证路由边界。
- 默认 proposal-adjust preparer 返回 dependency unavailable；只有显式注入的测试 preparer 走成功准备路径，没有调用模型，也没有生成业务写入。
- Runtime queue scheduling、MockModelProvider 推进、simulation lifecycle policy version binding 属 P1-05；Docker/恢复验收属 P1-06。
- Confirm、云端 receipt/close_execution 和真实业务写路径仍关闭，后续须按 P3 单独验收。
