# 差异调查与阶段验收任务

状态：**P0 工程核查已通过；T0步骤1–5运行与资产适用性审核、步骤6共享文档同步、D盘日志归档及C原hold清理完成，T0六步部署链验收通过（2026-10-08）；日志归档、静态适用性审核与根主审完成**。本表分开记录P0证据核查、已有业务修复验收、P1–P6工程阶段和T0–T4训练阶段。CAP source map不是产品功能验收；P1/P3尚未完成也不是P0阻断项。4B adapter链归T0，兼容chat/completions空content归P2。

## P0 工程核查记录

| ID | 检查项 / 当前证据 | 下一步 | 通过证据 | 执行 owner |
|---|---|---|---|---|
| P0-ENV-01（9B native runtime 已通过） | 00:49 预检 RAM 8.83 GiB、GPU free 6.15 GiB/利用率 15%、`lms ps=[]`，隔离回归栈已清理；约 00:59 再确认后临时加载已下载 9B Q4_K_M。兼容 `/v1/chat/completions` 三次 HTTP 200 但 `choices[0].message.content` 字符串均为空，64/128 预算均 `finish_reason=length`。 | 已按主审方案完成 native `/api/v1/chat` host 与 Docker 各一次，均 `reasoning=off`、`store=false`、HTTP 200 且 message content 非空；定向 unload 后 `lms ps=[]`。OpenAI 兼容路径可见回复问题转 P2；不停止未知服务。详见 [环境核验](environment.md)。 | 本项 9B 原生 host+Docker 短时 runtime smoke 通过，不代表 `/v1/chat/completions`、4B adapter 或语义能力通过；卸载后 RAM free 9.14 GiB、GPU free 6,058 MiB、利用率 8%。 | GPT-6 Luna xhigh 执行；root/主会话审阅 |
| P0-ENV-02 | Teacher 静态路由已对上：本机 URL path 是 `/zen/go/v1/chat/completions`，`_endpoint()` 对已完整的路径原样返回；公开 model/route 名称匹配。无请求，key 未显示/验证。 | 保留静态检查证据；远端 completion 不在本次审计范围内。若将来具体生成任务包含 Teacher 调用，随该任务记录额度与数据边界。 | 精确 provider/model/path 与实现拼接规则；当前静态路由匹配已完成，不等于认证/可用性通过。 | GPT-6 Luna xhigh 执行；root/主会话审阅 |
| P0-DB-01（本次通过） | `normal_prepayment_executor` 在 fresh isolated DB 完成 32 SQL 文件/237 pgTAP assertions；Android 268 tests（0 failures/errors/skips）及 `assembleDebug` 通过。scope 与 Expense move migration 纳入全套回归。主线按授权只对 linked remote 应用 `20261006142507_sub_activity_participant_scopes.sql`，`--skip-vault`、无 seed/role 或生产业务测试行；只读 catalog/ACL 核查通过。 | 本项已完成；保留本地 shared container 仍旧的事实，不对其迁移/reset。后续 schema/业务改动另起验收，不将此次单 migration 核查扩大成所有 CAP 的线上验收。 | 隔离栈 `sl-dbtest-04074edf63` 已清理；remote history 含目标 migration；scope marker default false、关联表 Member-read-only RLS、authenticated-only overload grants、旧 helper 撤权、三个 trigger enabled 与 projection wrapper guards/rebuild 均经只读核验。 | `/root/normal_prepayment_executor` 执行；root/主会话完成 linked remote 核验 |
| P0-DOC-01（P0状态收尾） | P0工程核查证据与未决项已按新指南归档；4B部署链仍归T0，兼容API空内容列P2。 | 已同步P0总览、状态页、指南与Agent入口；T0清单和步骤5运行报告链接已更新。 | P0通过条件满足；T0六步运行、适用性审核、日志归档与清理证据已形成，T0六步部署链验收通过（2026-10-08），不影响P0收尾。 | GPT-6 Luna xhigh文档执行；root/主会话复核 |

## 工程阶段 P1–P6

| 阶段 | 当前差异与实现范围 | 通过条件/交付 |
|---|---|---|
| P1 · 可恢复骨架 | 正在并行进行协议冻结并推进初步工程文件，进度以本地并行P1计划 `../p1/P1_DEVELOPMENT_PLAN.md`（该文件尚未纳入本次T0提交）和实际文件为准；服务、持久化、会话隔离、Mock恢复仍待实现/验收。P1不阻挡P0文档映射。 | 可启动服务及 Compose；不同账号隔离；query/clarify/propose模拟状态重启后恢复；未持久化不承诺接收。先不开放真实业务写。 |
| P2 · 真实只读 | 接本机 ModelProvider 与成员授权 read RPC；传必要 DTO/policy 结果正文、做页面/实体引用校验、事实卡与澄清。 | 固定模型/提示/上下文/timeout；host→服务、身份和真实只读权限通过；有延迟/资源/失败证据。质量低则记录训练任务，不称查询质量通过。 |
| P2 · 兼容接口诊断 | 本次 Qwen 9B 原生 `/api/v1/chat` host/Docker 均返回非空消息；OpenAI 兼容 `/v1/chat/completions` host 64/128 与 Docker 64 均 HTTP 200 但 content 空、finish_reason=`length`。请求均为短合成输入，未改服务设置。 | 核对兼容 API reasoning/output 参数映射与可见回复行为；复现时使用受控小预算并记录解析后的 content/stats。原生 API 成功不代表兼容路径通过，也不作为 Agent 质量验收。 |
| P3 · 确认写入 | 从新增 Expense 及允许的 Expense 财务编辑开始；实现服务端可信 preview、用户确认绑定、事务内权限/版本重核、唯一执行键、持久回执和未知结果恢复。保留 App 原 LWW。CAP08 已有 Expense 更新无客户端 CAS；不得把事务行锁或 presentation optional CAS 误报为 Agent 确认契约。CAP13 return 若要暴露，须先增加/验证 return 专属 preview，不能复用“新增预存”的预览结果当余额返还 diff。 | Mock P3a 后与 T3 同模型 P3b 联调：未确认没有写；并发变化令旧预览失效；相同键不重复记账；响应丢失可查原结果；locked Expense 拒绝财务修改、presentation 路径仍可用。 |
| P4 · Android 接入 | 个人设置开关、入口、对话面板、页面快照和消息卡；真实登录/刷新/网络/后台恢复接通服务端事实，不在 App 内重复算账。 | 安装构建；两账号、两设备或等效隔离客户端验证切页/换号/断网/重启及原有功能。 |
| P5 · 能力扩展 | 逐项完成 CAP01–17 中剩余管理、Participant scope、外币、退款、Expense 删除、普通还款、预存、void、Final、dispute、archive 等已存在 backend capability 的 Agent 接入；按当前 ACL 和没有 restore 的边界实现。新业务 bug fix 与 Agent 注册分开验收。 | 所有待支持 CAP 有 accept/clarify/reject 用例、权限/版本/receipt 检查和独立测试；无静默丢项。没有 restore 能力的 Expense/Transfer 不注册恢复写工具。 |
| P6 · 首版验收 | 冻结候选、独立评测、备份干净恢复、运维/故障/限制文档。 | 金标准、权限、确认、并发、故障和独立语言集通过预设门槛；可恢复，未关闭越权/重复/错账阻断；证据与版本完整。 |

## 训练阶段 T0–T4

| 阶段 | 当前状态 / 任务 | 通过证据 |
|---|---|---|
| T0 · 与P1并行 | 步骤1–5运行及固定输入对照、旧资产适用性标记完成；步骤5的4B Q4_K_M host/Docker smoke和生命周期复核通过。见[T0清单](../t0/README.md)、[HF报告](../t0/runs/20261008-hf-loader-preparation.md)、[F16/Q4/HF对照](../t0/runs/20261008-f16-cpu-comparison.md)及[LM Studio smoke报告](../t0/runs/20261008-lmstudio-q4-smoke.md)。4B模型key t0-cp36-20261007、publisher shared-ledger、Q4 SHA acfd01df6cbd3c8e1fa4dbe144f5852290689851c4f92d4ab892707d08724b34；D目标与获批产物同FileID硬链接，host/Docker各两case HTTP 200/client exit 0且instance匹配，严格JSON exact-object通过；524次采样最低RAM 9.798 GiB、GPU free最低4077 MiB，无floor breach，定向卸载后remaining=0。server运行前后均为stopped，D日志稳定SHA E15741505DF01B53438A75EAFDD2B68BB24EB4C78298AFC66AA387F1086BB597。运行后C日志目录快照33 files/19,214,214 bytes的逐文件SHA已与D历史归档匹配；归档为 `D:\AI\runtime\lmstudio\server-log-history\pre-t0-20261007-200705`，C原plain hold已精确清理，C junction保留并指向D active。清理证明SHA-256 25e315f94c53414c57cafa0a493f5a6335a37e4f446616a40beabc90b0e92146。旧资产审核覆盖266行/145轨迹：0直接复用、187待重标、73证据不足、6排除，所有旧模型输出隔离。 | 六步运行与适用性审核证据已形成；T0六步部署链验收通过（2026-10-08），根主审已完成。步骤3/4仅记录raw logits观测到的逐位差异，严格数值等价未建立；不宣称质量通过。T1重标、新数据集冻结与Teacher实际availability为独立后续，不是T0关闭门；本轮未调用Teacher。 |
| T1 · 随 P1，结合 P2 | 定义 answer/clarify/read/propose 语义、工具契约和版本/hash；新 family/state split 再建 train/validation/sealed。旧六类/Scope、D4、普通预存标签逐项标历史/复核。 | 冻结 schema/contract/data manifest/覆盖矩阵；新 sealed set 与 train/validation 按业务状态或轨迹族隔离，预先固定门槛。 |
| T2 · P2 基线后 | 用已审核数据针对性训练；先小批次检查模板、assistant action mask、loss、断点续训；按语义路由→参数→结果消费→澄清→propose 诊断分类后补数据。 | 可重现训练配置、数据哈希、checkpoint、冻结验证结果与未训练基线比较。只 loss 降低不通过。 |
| T3 · P3/P4 联调 | 导出训练候选到 LM Studio；在 Harness 测查询/澄清、允许 Expense 修改、locked 拒绝、工具故障和 stale preview。量化格式与训练 adapter 版本绑定。 | 实际模型 ID、格式/量化/上下文、完整轨迹与核心端到端报告；未确认写和伪造事实被挡，locked 拒绝，模型错误与工程边界分别报告。 |
| T4 · P5，P6 前 | 按 CAP01–17 扩充数据；失败分类后才补样本/训新版本；以验证集选候选，封存后独立测评。 | 所有 CAP 的按语义版本报告/manifest；若 sealed 失败案例用于调参，该集降级成 regression 并建立新独立 holdout。 |

## 已知不纳入本轮的项

本轮完成P0状态收尾及T0步骤1–5的实测：HF merge/builder与固定输入对照、F16/Q4转换和三格式比较、4B Q4_K_M LM Studio host/Docker smoke及生命周期复核均有单独证据；旧资产适用性静态审核已完成。步骤6共享文档、D盘日志归档及C原hold精确清理完成，等待T0最终审查。报告与运行manifest见../t0/和D盘run目录。本轮未调用Teacher、未训练、未做云端业务写入或Android发布；P1及main保持隔离，Git提交/推送结果以agent分支与origin/agent记录为准。主线DB回归、scope migration应用/只读核验及9B原生host/Docker smoke为前序记录，不扩大为本轮实测。
