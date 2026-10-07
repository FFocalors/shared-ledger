# Agent 开发状态

日期：2026-10-07  
当前阶段：**P0 工程核查进行中，尚未验收**  
Agent 项目路径：agent/  
本次指南源文件 SHA-256（下载的 v0.3 HTML；源文件未修改）：40e2c2b017c71a3081e3e7460dd964a34af7484f0ae6be17d896a28c11d39a09

P0 核查记录：[工程审计目录](p0/README.md)，含仓库/RPC 能力映射、环境、T0 资产与未决任务。P0 仍未验收：9B 原生 host/Docker chat 的最终统计已由主审核对通过；4B adapter 导出、转换、加载链仍待完成。OpenAI 兼容接口的空 content 证据已由 P0 执行员复核，见 P0 环境记录。

## P0 原始核查工作区快照（历史记录）

- 分支：feature/ai-training-pipeline
- HEAD：dcdb033b9cc245f355f61b5a303007b7d7571e18
- 当前工作树保留前序普通活动预存限制及相关 Android、数据库夹具、业务文档和 verifier 未提交修改；本轮另有子活动 Participant 范围、Expense 跨账本投影修复、对应测试与文档未提交变更。未覆盖既有修改，没有提交。
- 新项目路径创建前，仓库没有根 README.md 或 agent/；既有 AI 资料在 docs/ai/，冻结协议与训练资产未改。

## 当前 Agent 与业务工作区（2026-10-07 拆分后）

- Agent 文档/开发工作区：D:/project/Android/shared-ledger-agent；分支 agent，起点 HEAD dcdb033b9cc245f355f61b5a303007b7d7571e18。agent/ 下 10 份 Agent 文档为本次授权的提交范围；用户最新授权覆盖此前“先不要提交”，仅限 agent 分支，不扩展到 main 或云端操作，提交结果以 Git/远端状态为准。Codex attach 对该 D 盘外部路径返回 “The checkout exists but is not a managed worktree.”，旧附件尚未同步；以 D:/project/Android/shared-ledger-agent 的实际目录与 Git worktree 状态为准。C 盘的 654 个原文件已完整移至 D:/computer/Hermes/backups/agent-worktree-relocation-20261007/retained-source，654 项 hash/size 均通过主审核验；同级 retained-source.codex-worktree-name.marker 文件为 0 字节并已核验。本轮最新只读观察（2026-10-07）显示原 C 盘 Agent worktree 与 relocation-hold 路径均不存在，文件/目录枚举为 0；清理主体和方式未核实，不作推断。较早的 [relocation-final-status.md](D:/computer/Hermes/backups/agent-worktree-relocation-20261007/relocation-final-status.md) 在 13:08 记录当时 hold 有 174 个空目录且清理请求被拒，仅属历史快照。
- 当前业务源码工作区：D:/project/Android/shared-ledger；分支 main，HEAD 3f938ee6114b763e6cd3dbd10792a78c691eb526。最新提交包含 35 个业务相关文件，origin/main 已同步且工作区 clean；当前业务实现、迁移与测试核对以此工作区为准。
- Agent checkout 中的 app/、supabase/、docs/backend/ 是 feature HEAD 上的旧提交基线，不能用来替代当前 main 业务实现。下文当前业务文件链接使用 main 工作区绝对路径；P0 原始审计的 branch/HEAD 记录仍是历史快照。

## 已核对的业务与实现状态

- 当前业务基线为 [docs/backend/BUSINESS_LOGIC.md](D:/project/Android/shared-ledger/docs/backend/BUSINESS_LOGIC.md)，并结合已应用迁移、RPC ACL 和确定性数据库测试。指南按用户批准口径与这些实现事实统一。
- 普通活动无预存入口，preview/create/return 均拒绝。[20261006025641_normal_activity_prepayment_restrictions.sql](D:/project/Android/shared-ledger/supabase/migrations/20261006025641_normal_activity_prepayment_restrictions.sql) 与 [normal_prepayment_restrictions.sql](D:/project/Android/shared-ledger/supabase/tests/database/normal_prepayment_restrictions.sql) 已存在；该限制已本地和云端落地。Android 预存入口修改仍未发布。
- 大型子活动 Participant scope 与 Expense 跨账本投影修复见 [20261006142507_sub_activity_participant_scopes.sql](D:/project/Android/shared-ledger/supabase/migrations/20261006142507_sub_activity_participant_scopes.sql)。三参数 RPC 保存有效 Participant ID 子集；兼容两参数 RPC 为新 child 保存当前全部有效 Participant；迁移前 child 保持 `participant_scope_configured=false` 的 legacy-unscoped，不回填历史选择。付款人与 Split 承担人均须在已配置 scope 内，付款人与承担人可不同；root 维持 Activity 全名单。该迁移已应用至 linked 项目 `zecjkgvwpcvwheyflbyi`，并完成远端目录、RLS/ACL、trigger 与 projection wrapper 只读核验。
- 本轮 fresh isolated DB 回归：32 个 SQL 文件、237 个 pgTAP assertions 全通过；Android `:app:testDebugUnitTest` 为 268 tests、0 failures/errors/skips，`:app:assembleDebug` 成功。`lintDebug` 未重跑；既有 `SharedLedgerHaptics.kt:81` NewApi 问题未修。脱敏摘要位于 `D:\computer\Hermes\temp\shared-ledger-dbtests-04074edf63\validation-evidence\`；Android XML 报告位于 `D:/project/Android/shared-ledger/app/build/test-results/testDebugUnitTest/`。
- AA base 尾差沿用当前后端按 participant_order, id 稳定分配 0.1 最小单位：100.0 / 3 为 33.4、33.3、33.3；10.0 / 6 为 1.7 × 4、1.6 × 2。原币/base 精度及 FX snapshot 均遵循当前后端。
- Expense 的财务锁、删除/恢复权限遵循现后端：financial_locked 禁止财务字段与 Payment/Split 修改，只允许 presentation 更新；当前没有可调用 Expense restore RPC（旧函数对 API roles 已撤销 EXECUTE）。Transfer 不可编辑或恢复，只能走受支持的作废生命周期。
- 普通与大型 Final 沿用当前后端 optimizer 和 base_unified / original_currency 模式；只有大型活动 Final 可带预存返还。普通预存没有历史兼容需求。
- D4 的旧 AI 全局 execution_allowed=false 是历史策略。新 Agent 可在后端允许时先产生可信预览，用户确认后执行；Agent 自身版本保护不改变原 App LWW。现 Expense 财务 update RPC 无 `expected_version`/CAS；P3 需设计 Agent 自己的确认版本保护。
- 冻结 AI Contract/Scope 和训练资产保持原样。旧六类协议、三档 Scope 和旧标签不等于新版 Agent 协议、范围或验收证据；新数据须版本化并标明适用性后才可使用。

## 验证记录

- 本轮数据库回归：从 fresh isolated reset 应用完整仓库 migration 后，32 个 SQL 文件、237 个 assertions 全部通过。Windows Supabase CLI bind mount 失败后，测试 runner 在同一隔离网络用 `pg_prove` 跑完整套件；测试栈已停止。
- 本轮 Android：`:app:testDebugUnitTest` 268 项通过，`:app:assembleDebug` 成功；`:app:lintDebug` 未重跑，既有 Haptics `NewApi` 限制仍记录在案。
- 本轮云端：push 前确认仅 scope migration 一项待应用；`--skip-vault` 应用成功。只读 catalog 检查通过，未写生产业务行。
- 2026-10-07 9B 原生接口合成探针：临时加载 `qwen/qwen3.5-9b@q4_k_m`（context 512、GPU 0.5），host 与 Docker 均 `POST /api/v1/chat`、`reasoning=off`、`max_output=64`、`store=false` 并返回 HTTP 200/非空 content。Host：content 长度 6、input 19、output 3、reasoning 0；Docker：长度 26、input 19、output 9、reasoning 0。该原生探针的最终统计已由主审复核；结果仅证明 9B 原生接口连通，不代表新版 Agent 质量或 4B adapter 链。模型卸载 exit 0，`lms ps=[]`；最终快照 RAM 可用 9.14 GiB、GPU 可用 6058 MiB，LM Studio 服务仍监听 1234。

## P0 尚需调查、映射与环境/资产核验

- 已盘点当前分支、提交、未提交变更、AGENTS/项目说明及真实 App/后端入口，记录在[工程审计](p0/engineering-audit.md)；续接时核对基线是否变化。
- 按 [CAP01—CAP17 能力表](p0/capability-map.md) 补齐仍未覆盖的真实客户端/全部角色端到端实测；当前已静态映射有效迁移定义、App payload 与 ACL，并只读核验 scope migration 的远端 catalog/ACL，不代表 Agent 能力完成。
- Teacher 配置中的 provider `opencode`、model `deepseek-v4.1-flash`、endpoint 与公开路由已核对；未发 Teacher 请求，凭证有效性、权限/额度、实际 completion 与响应契约仍未验证。T0 指定 run 的 checkpoint/adapter/数据划分和失败轨迹处置见 [资产记录](p0/t0-assets-and-lessons.md)。
- 9B 原生 host/Docker 合成请求及其统计已由主审复核通过。OpenAI 兼容 `/v1/chat/completions` 在默认 thinking/short budget 64 与 host 128 设置下虽 HTTP 200，但无可见 content 且 `finish_reason=length`；这是独立 P2 跟进项，其统计来源已由 P0 执行员复核，见 P0 环境记录，不与原生端点结果混同。Qwen3.5-4B adapter merge/export/conversion/load 链未验证：本次有界检查在 `D:\AI\tools\llama.cpp` 与 `D:\AI\LlamaFactory\llama.cpp` 未找到 checkout，`llama-quantize`/converter 不在 PATH；D 盘剩余 128.39 GiB。此前 RAM 快照 9.92 GiB 对 8.68 GiB base 权重仅留约 1.24 GiB，未计 merge 峰值开销，未启动 merge；不要把下载/探针用的 9B GGUF 当成 4B 训练产物。
- P0 的交付是有证据的工程/能力映射/环境与资产记录，以及有明确归属的缺口清单；不要求在 P0 内实现 Agent 骨架或所有功能。

## 已定位的后续实现缺口（不作为 P0 完成前提）

- P1：Agent 运行骨架、持久化、认证会话隔离、新语义协议、提案状态和可恢复运行机制尚未实现/验收。
- P3：真实后端 preview、确认后执行、执行回执、重复确认与未知结果恢复的端到端集成尚未验证。
- P1/T1：新版 Agent 协议、CAP 范围与历史数据适用性需独立版本化；旧协议/冻结训练资产不原地改写、不无标记混训。
- P3：为 Agent 确认执行设计可验证的版本失效与重复/未知结果恢复；现有 Expense 财务更新无 `expected_version`/CAS，不能改变原 App LWW。
- P0 状态仍为进行中、未验收；本轮未调用 Teacher、未启动训练或实现 Agent，也没有发布 Android 客户端。9B 原生 host/Docker 合成请求按上文记录执行并在结束后卸载；云端只应用已审查 scope migration，没有写入生产业务数据。
