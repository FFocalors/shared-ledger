# P0 工程审计目录

状态：**进行中，未通过。** 本目录记录仓库静态映射、环境与历史训练资产核对，以及仍需取得证据的调查任务。CAP 表逐项对照当前迁移链中的有效定义和 Android 实际请求；“源码存在”不代表迁移已在当前数据库生效，更不代表 Agent 能力已实现或通过验收。

## 文件

| 文件 | 内容 |
|---|---|
| [工程审计](engineering-audit.md) | 仓库、工作树、接口规范漂移、版本/幂等事实与本轮边界 |
| [CAP01–CAP17 能力映射](capability-map.md) | 当前 RPC、请求参数、ACL、实体范围、预览、版本、回执及拒绝边界 |
| [环境核验](environment.md) | 本机与容器连通性、9B 原生合成 chat、兼容 API 结果和资源状态 |
| [T0 资产与教训](t0-assets-and-lessons.md) | 指定旧 run 的产物清单、哈希、评估结果和复用限制 |
| [差异与验收任务](follow-up-tasks.md) | P0 未决调查、P1–P6 工程工作和 T0–T4 训练工作 |

## 状态口径

- CAP 矩阵以仓库当前迁移定义和 App payload 为静态基线；本次主线另完成了 fresh isolated DB 全套回归（32 个 SQL 文件、237 个 pgTAP assertions）及 Android 268 项测试、`assembleDebug`，不把这些本地证据扩大为所有线上角色/部署已验证。
- 普通活动预存限制的既有云端应用和早期 31 SQL / 235 pgTAP 等数字属于前序记录；本次隔离回归另有 32 SQL / 237 pgTAP 与 Android 构建验证，范围见 [工程审计](engineering-audit.md)。
- 子活动 Participant scope 与跨账本 Expense 修复已在本地完整回归；主线仅应用了该新 migration，远端 catalog/RPC ACL 的只读复核也已通过。此项不代表 CAP01–CAP17 全部真实角色端到端验收。
- 9B Q4_K_M 原生 LM Studio chat 已在 host 与 Docker 路径返回非空合成回复，并定向卸载、确认 `lms ps=[]`；OpenAI 兼容 `chat/completions` 虽 HTTP 200，但在 64/128 token 预算下内容为空，单列为 P2 兼容性待查。T0 的 4B adapter merge/export/load 链路仍未完成，9B runtime 结果不替代它。
- 旧协议、旧数据、旧 checkpoint 和旧报告保留为失败分析材料。不能覆盖冻结文件，也不能据旧指标宣称新版四类语义或 Agent 质量通过。

继续任务时先核对 [差异与验收任务](follow-up-tasks.md) 的状态和本轮环境资源；不要把 P1/P3 尚未实现误记成 CAP 后端不存在，也不要把后端能力存在误记成 Agent 已交付。
