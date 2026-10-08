# Shared Ledger Agent

这是文本 Agent 的工程入口。当前包含开发指南、P0/T0记录与并行推进的P1协议/工程文件；P1服务、依赖和完整验收仍在开发中，进度以本地并行P1计划 `docs/p1/P1_DEVELOPMENT_PLAN.md`（该文件尚未纳入本次T0提交）和实际文件为准。

先阅读[统一开发指南](docs/shared-ledger-agent-development-guide-v0.4.html)，再查看[当前开发状态](docs/dev-status.md)、[P0工程审计目录](docs/p0/README.md)和[T0执行清单](docs/t0/README.md)。T0步骤1–5实测索引见清单、[HF报告](docs/t0/runs/20261008-hf-loader-preparation.md)、[F16/Q4/HF对照报告](docs/t0/runs/20261008-f16-cpu-comparison.md)及[4B LM Studio smoke报告](docs/t0/runs/20261008-lmstudio-q4-smoke.md)。指南保留P0—P6/T0—T4架构并统一业务口径；P0工程核查已通过；T0六步部署链验收通过（2026-10-08），共享文档同步、D盘日志归档、C原hold清理和根主审完成。

实现业务时以[当前后端业务规则](D:/project/Android/shared-ledger/docs/backend/BUSINESS_LOGIC.md)及实际 RPC/ACL 为依据。[大型活动预存补充规则](D:/project/Android/shared-ledger/docs/ai/PREPAYMENT_LARGE_ACTIVITY_RULE_2026-10-06.md)记录普通与大型活动的预存边界。当前Agent工作区为D:/project/Android/shared-ledger-agent（分支agent，本次T0核查起点@82ad2994084ff964746aa43476a923d30cf26d09）；业务源码与迁移以D:/project/Android/shared-ledger（main@3f938ee6114b763e6cd3dbd10792a78c691eb526，origin/main同步、工作区clean）为准。P1并行进行协议冻结，当前可见`agent/app/contracts.py`等工程文件；Agent工作区根目录的`app/`、`supabase/`、`docs/backend/`是旧业务基线。新增Agent工作及迁移备份优先放D盘，不使用默认C盘worktree。冻结的[旧 AI Model Contract](../docs/ai/AI_MODEL_CONTRACT.md)和[旧 AI Scope Freeze](../docs/ai/AI_SCOPE_FREEZE_V0.1.md)仅供历史参考；新Agent协议、CAP范围和语义版本独立演进。

普通活动预存限制与大型子活动参与人范围/跨账本投影修复已按既有记录本地验证并应用云端；Android修改尚未发布。9B原生LM Studio host/Docker合成请求是前序独立验证。P0工程核查按指南证据条件已通过；T0步骤3/4固定输入对照、步骤5的4B Q4_K_M host/Docker smoke及服务/日志生命周期复核均已完成，报告见[T0清单](docs/t0/README.md)和[LM Studio smoke报告](docs/t0/runs/20261008-lmstudio-q4-smoke.md)。步骤6共享文档同步、D盘日志归档和C原hold清理完成；T0六步部署链验收通过（2026-10-08），根主审已完成。旧资产静态适用性审核已完成，266行/145轨迹中0行直接复用、187待重标、73证据不足、6排除；T1重标/数据冻结和Teacher实际availability独立后续，不是本次T0关闭门。OpenAI兼容chat空content归P2。P1协议冻结与工程文件正在并行推进；P3可信预览、确认与执行尚未验收。
