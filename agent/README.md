# Shared Ledger Agent

这是未来文本 Agent 的工程入口。当前目录包含开发指南、开发状态与 P0 审计记录，尚无 Agent 源代码、依赖或服务。

先阅读[统一开发指南](docs/shared-ledger-agent-development-guide-v0.4.html)，再查看[当前开发状态](docs/dev-status.md)和[P0 工程审计目录](docs/p0/README.md)。指南以下载的 v0.3 完整 HTML 为底稿，保留架构、P0—P6/T0—T4、附录以及确认和恢复设计，并统一用户批准的业务口径。

实现业务时以[当前后端业务规则](D:/project/Android/shared-ledger/docs/backend/BUSINESS_LOGIC.md)及实际 RPC/ACL 为依据。[大型活动预存补充规则](D:/project/Android/shared-ledger/docs/ai/PREPAYMENT_LARGE_ACTIVITY_RULE_2026-10-06.md)记录普通与大型活动的预存边界。当前 Agent 工作区为 D:/project/Android/shared-ledger-agent（agent@dcdb033b9cc245f355f61b5a303007b7d7571e18）；本项目后续新增 Agent 工作区及迁移备份优先放在 D 盘，不采用默认 C 盘 worktree 位置。当前业务源码与迁移以 main 工作区 D:/project/Android/shared-ledger（main@d305011b02e6105e2fe3e5b40460de4218d466ba）为准，35 个业务文件未提交。Agent checkout 中的 app/supabase/docs/backend 是旧提交基线。冻结的[旧 AI Model Contract](../docs/ai/AI_MODEL_CONTRACT.md)和[旧 AI Scope Freeze](../docs/ai/AI_SCOPE_FREEZE_V0.1.md)仅供历史参考；新 Agent 协议、CAP 范围和语义版本独立演进。

普通活动预存已由本地及云端后端限制。大型子活动参与人范围与消费跨账本投影修复已本地完整回归，数据库迁移已应用到 linked 云端并只读核验；Android 修改仅本地构建，未发布。9B 原生 LM Studio host/Docker 合成请求已通过且统计经主审复核，模型随后卸载；OpenAI 兼容 chat 空 content 作为 P2 跟进，其证据已由 P0 执行员复核，见 P0 环境记录；4B adapter 导出、转换、加载链仍未验证，P0 尚未验收；Agent 功能未实现。
