# P1-05 Mock Runtime 交接

日期：实施记录 2026-10-08；主会话终审 2026-10-09（Asia/Shanghai）  
状态：P1-05 限定 Mock Runtime 范围于 2026-10-09 经主会话终审通过。此结论不代表 P1 整体验收通过，也不启动 P1-06。

## 运行边界

服务默认 `AGENT_PROVIDER_MODE=disabled`、`AGENT_AGENT_ENABLED=false`。这保持 health/readiness 和身份/API 服务启动，但不调度新规划。只有显式设置 `AGENT_PROVIDER_MODE=mock` 并启用 `AGENT_AGENT_ENABLED=true` 后，才使用确定性本地 Runtime。单应用 worker 固定为 1；Runtime 同时跟踪 turn task 的默认上限为 4，可配置为 1–8；模型 semaphore 固定为 1。

Mock 模式仍要求请求经过配置的 Supabase Auth verifier。MockScopeAuthorizer、固定活动与账本数据均为本地模拟范围，不能代表真实业务权限。`MockModelProvider.health()` 报告 `inference_available=false`；MockBackendAdapter 只读夹具，不连接真实业务后端；确认 proposal 返回 `execution_capability_unavailable`（HTTP 501），不生成 execution identity、nonce、digest、业务命令或成功业务回执。Health 里 simulation/runtime 可用只说明此本地流程已装配，不表示推理或账本访问可用。

`create_app()`/`build_components()` 只构造依赖，不打开文件、网络或模型。lifespan 依次启动 Store、Provider、Backend、Runtime，并反向关闭；默认禁用 Provider 使用 UnimplementedRuntime。Mock Runtime 重启后从 SQLite 恢复阶段和预算，但内存 bearer grant 清空，涉及身份的任务需重新认证。

## 本地配置

在 `agent/` 下复制 `.env.example` 为 `.env`。要明确启用模拟规划时，配置：

```dotenv
AGENT_PROVIDER_MODE=mock
AGENT_AGENT_ENABLED=true
AGENT_DISABLE_REVISION=1
```

仍需提供正确的 `AGENT_SUPABASE_AUTH_BASE_URL` 和 publishable/anon `AGENT_SUPABASE_API_KEY`。访问 API 时使用真实有效的用户 Bearer token；不得把项目 API key 当成用户 token。每次关闭 Agent 时递增 `AGENT_DISABLE_REVISION`，再次开启时保留该值。

可调整 `AGENT_RUNTIME_TASK_CONCURRENCY`（1–8）、`AGENT_MOCK_MODEL_TIMEOUT_SECONDS`（0.05–10）和 `AGENT_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS`（0.1–10）。`AGENT_MODEL_CONCURRENCY` 只接受 1。默认模板仍禁用 Provider 与 Agent。

## Runtime 行为

- Harness 把原始 JSON 决策先通过重复键、非标准数、对象形状和大小检查，再按冻结四语义 adapter 验证；unknown field、未绑定引用、写 RPC、自报确认和不符合当前上下文的 decision fail closed。
- Mock Provider 对对话、活动、消费、债务查询以及有限 proposal 输入给出确定性输出。MockBackendAdapter 从冻结 fixtures 返回明确 simulation 的只读结果。读取预算为每代最多 4 次；模型调用最多 6 次，其中一次修正调用也计数；最多一次结构修正。预算在实际 provider 调用前持久化，澄清/调参新 generation 才重置。
- Entity、evidence 和 read-result token 绑定到源 Turn 并 append-only 保存。每代最多读取 4 次；跨代历史引用持续追加。新结果按序使用尚未占用的 `Rxx`，首代已有 token 会保留原绑定，不会因后续结果顺序变化重新指向另一个 fixture。每次读前后都重新检查 Auth、Scope、关闭修订及 charged checkpoint。
- 多个 turn task 可并行等待只读工具；模型 gate 在单次生成调用期间独占。取消或超时后，如果底层 provider 仍未结束，迟到结果不会提交，模型 gate 也要等底层调用真实结束后才释放。
- 每个 owner 至多一个 RUNNING 与一个 QUEUED turn，全局至多 16 个 QUEUED。等待澄清、认证或确认不占这两个运行名额；proposal 调整在短期私有 lease 下占用 owner 的运行容量。过期 RUNNING lease 先重领原 turn，不能让同 owner 的第二个 RUNNING 抢占。
- 普通规划重启可从持久 `resume_step`、semantic decision、完整 context、引用与预算继续；已分配 execution 的 `RECOVERING/UNKNOWN` 始终保留原 key，不回模型、不标成 FAILED。没有 P1 execution adapter 时该任务被 park；认证恢复可触发重新核验，但 UNKNOWN 不会伪装为已解决。
- simulation proposal 使用 `mock-policy-v1;disable_revision=<decimal>`、10 分钟有效期，不包含 live nonce/digest/command。调整通过持久 reservation、原请求键和 generation 预算形成新 revision；同键重放返回同一 receipt。过期 proposal 原子标记 expired 并释放同 Session pending 位。

## 验证记录

本次最终验证包含 21 项 Runtime 核心测试、10 项 API 专项测试和 84 项历史测试；checkout 全量结果为 **115 passed in 23.52s**。覆盖四语义原始 JSON、模拟提案预览和调整、auth 暂停/澄清恢复、重启 stage/budget/reference、1/4/6 次资源边界、迟到与超时结果、工具等待时跨 actor 进展、UNKNOWN recovery 不饿死普通任务、全局 16 队列跨 Store 连接并发竞争、过期 RUNNING claim 和活跃 adjustment lease 容量互斥。另有确定性并发回归验证 Runtime.close 取消等待中的 `to_thread` claim 后，迟到事务不会留下阻塞新 Runtime 的 lease；Store.close 等待该 claim 收尾并清除 lease，重开数据库仍可立即恢复 QUEUED turn。API 专项覆盖 owner/scope/gate、resume、expiry、501 原回执和 429 exact retry。主会话实际执行的全量测试、contract export 与 lock 检查命令及结果如下：

以下命令须在 checkout 根目录 `D:/project/Android/shared-ledger-agent`（不是 `agent/` 子目录）运行，环境为 Windows、Python 3.12：

```powershell
& '.\agent\.venv\Scripts\python.exe' -m pytest agent\tests\test_mock_runtime.py -q -p no:cacheprovider
& '.\agent\.venv\Scripts\python.exe' -m pytest agent\tests\test_mock_runtime_api.py -q -p no:cacheprovider
& '.\agent\.venv\Scripts\python.exe' -m pytest agent\tests -q -p no:cacheprovider
& '.\agent\.venv\Scripts\python.exe' -m agent.app.export_contracts --check
& 'D:\computer\Hermes\uv\bin\uv.exe' lock --check --offline --project agent
```

以上命令在 checkout 根目录 `D:/project/Android/shared-ledger-agent` 执行。pytest 全量结果为 `115 passed in 23.52s`；`export_contracts --check` 通过且 manifest matches；`uv lock --check --offline --project agent` 检查 32 packages 并以 exit 0 结束。本次终审对比 88 项文件基线，仅有经授权的 `ports.py`、`runtime.py`、`store.py` 生命周期修复差异；冻结协议快照、依赖锁、迁移和历史交接无变更。最终 `test_mock_runtime.py` SHA-256 为 `a4dbe82ea817cf009e8625c8fb8841a22a6e0a64456a84e027f324d9f951e5c7`。

主会话另行报告的 loopback Uvicorn physical TCP smoke 使用明确注入的模拟身份，验证了 health、建 session、提交/轮询 simulation proposal、确认返回 501 的完整 HTTP 路径。真实 Supabase 正向用户 Auth 联调尚未完成：本地 seed 登录在上游返回 500（`confirmation_token` 为 NULL），这不是本服务 Auth 验证失败的证据，也不能记为真实身份通过。该 smoke 不证明真实 activity membership、模型推理或业务写能力通过。

P1-06 部署镜像/Compose、备份恢复演练和重新创建容器验收未开始。P1-05 结果不得外推为 P1、P2、P3 或产品验收通过。
