# P0 工程审计目录

状态：**P0 工程核查通过（2026-10-07）；T0步骤1–5运行、对照与资产适用性审核完成，步骤6文档同步、D盘日志归档和C原hold清理完成，T0六步部署链验收通过（2026-10-08）；日志归档、静态适用性审核与根主审完成。** P0通过不代表 CAP 全角色端到端或 Agent 产品功能通过。CAP表逐项对照当前迁移链中的有效定义和Android实际请求；“源码存在”不代表迁移已在当前数据库生效。4B部署链进度见[T0清单](../t0/README.md)；步骤5服务和日志生命周期复核已完成，正式报告已归档。旧资产适用性审核覆盖266行/145轨迹：0直接复用、187待重标、73证据不足、6排除。T1重标/数据冻结及Teacher实际availability是独立后续事项；兼容chat/completions空content归P2。

## 文件

| 文件 | 内容 |
|---|---|
| [工程审计](engineering-audit.md) | 仓库、工作树、接口规范漂移、版本/幂等事实与本轮边界 |
| [CAP01–CAP17 能力映射](capability-map.md) | 当前 RPC、请求参数、ACL、实体范围、预览、版本、回执及拒绝边界 |
| [环境核验](environment.md) | 本机与容器连通性、9B 原生合成 chat、兼容 API 结果和资源状态 |
| [T0 资产与教训](t0-assets-and-lessons.md) | 指定旧 run 的产物清单、哈希、评估结果和复用限制 |
| [差异与验收任务](follow-up-tasks.md) | P0 核查记录、P1–P6 工程工作和 T0–T4 训练工作 |

## 状态口径

- CAP 矩阵以仓库当前迁移定义和 App payload 为静态基线；本次主线另完成了 fresh isolated DB 全套回归（32 个 SQL 文件、237 个 pgTAP assertions）及 Android 268 项测试、`assembleDebug`，不把这些本地证据扩大为所有线上角色/部署已验证。
- 普通活动预存限制的既有云端应用和早期 31 SQL / 235 pgTAP 等数字属于前序记录；本次隔离回归另有 32 SQL / 237 pgTAP 与 Android 构建验证，范围见 [工程审计](engineering-audit.md)。
- 子活动 Participant scope 与跨账本 Expense 修复已在本地完整回归；主线仅应用了该新 migration，远端 catalog/RPC ACL 的只读复核也已通过。此项不代表 CAP01–CAP17 全部真实角色端到端验收。
- 9B Q4_K_M 原生 LM Studio host/Docker chat 与本轮4B smoke为不同验证。4B步骤3/4三例HF/F16/Q4固定输入对照完成；步骤5 Q4_K_M 4B（model key t0-cp36-20261007）host/Docker各两case通过HTTP 200、client exit 0、instance匹配与严格JSON检查，不能据此宣称业务语义质量、CAP端到端或数值等价。模型已定向卸载，remaining=0；LM Studio server运行前后均为stopped，D日志稳定SHA-256 E15741505DF01B53438A75EAFDD2B68BB24EB4C78298AFC66AA387F1086BB597。运行后C日志目录快照33 files/19,214,214 bytes的逐文件SHA已与D历史归档匹配，位于 `D:\AI\runtime\lmstudio\server-log-history\pre-t0-20261007-200705`；C原plain hold已清理，C junction保留并指向D active。清理证明SHA-256 25e315f94c53414c57cafa0a493f5a6335a37e4f446616a40beabc90b0e92146。详见[T0清单](../t0/README.md)及[步骤5正式报告](../t0/runs/20261008-lmstudio-q4-smoke.md)。
- 旧协议、旧数据、旧 checkpoint 和旧报告保留为失败分析材料。不能覆盖冻结文件，也不能据旧指标宣称新版四类语义或 Agent 质量通过。

继续 T0 时先核对 [T0 执行清单](../t0/README.md)与最新资源门；P1 并行进展以 `../p1/` 记录和实际文件为准。不要把 P1/P3 实现状态与 CAP 后端映射混为一谈，也不要把后端能力存在误记成 Agent 已交付。
