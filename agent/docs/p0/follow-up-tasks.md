# 差异调查与阶段验收任务

状态：**P0 仍未关闭**。本表分开标记 P0 调查与验收状态、已有业务修复的代码验收、P1–P6 Agent 工程阶段和 T0–T4 训练阶段。当前的 capability source map 不是产品功能验收；尚未实现 Harness 也不是 P0 mapping 阻断项。

## P0 调查与验收状态

| ID | 未决项 / 当前证据 | 下一步 | 通过证据 | 执行 owner |
|---|---|---|---|---|
| P0-ENV-01（9B native runtime 已通过） | 00:49 预检 RAM 8.83 GiB、GPU free 6.15 GiB/利用率 15%、`lms ps=[]`，隔离回归栈已清理；约 00:59 再确认后临时加载已下载 9B Q4_K_M。兼容 `/v1/chat/completions` 三次 HTTP 200 但 `choices[0].message.content` 字符串均为空，64/128 预算均 `finish_reason=length`。 | 已按主审方案完成 native `/api/v1/chat` host 与 Docker 各一次，均 `reasoning=off`、`store=false`、HTTP 200 且 message content 非空；定向 unload 后 `lms ps=[]`。OpenAI 兼容路径可见回复问题转 P2；不停止未知服务。详见 [环境核验](environment.md)。 | 本项 9B 原生 host+Docker 短时 runtime smoke 通过，不代表 `/v1/chat/completions`、4B adapter 或语义能力通过；卸载后 RAM free 9.14 GiB、GPU free 6,058 MiB、利用率 8%。 | GPT-6 Luna xhigh 执行；root/主会话审阅 |
| P0-ENV-02 | Teacher 静态路由已对上：本机 URL path 是 `/zen/go/v1/chat/completions`，`_endpoint()` 对已完整的路径原样返回；公开 model/route 名称匹配。无请求，key 未显示/验证。 | 保留静态检查证据；远端 completion 不在本次审计范围内。若将来具体生成任务包含 Teacher 调用，随该任务记录额度与数据边界。 | 精确 provider/model/path 与实现拼接规则；当前静态路由匹配已完成，不等于认证/可用性通过。 | GPT-6 Luna xhigh 执行；root/主会话审阅 |
| P0-T0-01 | 4B adapter→HF merge→GGUF→LM Studio 尚未验证。指定旧 run、代表 adapter、日志/报告与小配置 hash 已盘点；adapter 配置指向 `D:/AI/models/Qwen3.5-4B`，9B 是不同 GGUF，不能互代。base 两片 safetensors 合计约 8.68 GiB；D: 可用 137.86 GB。边界预检未在 `D:/AI` 顶层、`D:/AI/tools/llama.cpp`、`D:/AI/LlamaFactory/llama.cpp` 找到 llama.cpp，且 `llama-quantize` / `convert_hf_to_gguf.py` 不在 PATH；这只表示指定范围未找到。最近卸载后 RAM free 9.14 GiB，名义上仅比 base 文件大小多约 0.46 GiB，且未计运行与 merge 峰值。 | 下一步先核验 4B 权重快照、venv/CLI 版本与可用 converter，再由主审复核资源和输出方案；在隔离目录用 A-only checkpoint-36 做一次 merge、支持性检查、F16 转换/量化、独立 LM Studio 导入与短 synthetic chat。尚无工具不支持或链路成功结论；不得用 9B smoke 替代。 | merge 对应 base+adapter、converter 版本、完整 logs/输出 hashes、GGUF metadata、HF 与 F16 对照、Q4_K_M 加载和合成请求证据。若受限，保存有界搜索范围、准确版本与可执行方案；不把 9B host/Docker chat 当 4B adapter 链路通过。 | GPT-6 Luna xhigh 执行；root/主会话复核转换/资源方案 |
| P0-DB-01（本次通过） | `normal_prepayment_executor` 在 fresh isolated DB 完成 32 SQL 文件/237 pgTAP assertions；Android 268 tests（0 failures/errors/skips）及 `assembleDebug` 通过。scope 与 Expense move migration 纳入全套回归。主线按授权只对 linked remote 应用 `20261006142507_sub_activity_participant_scopes.sql`，`--skip-vault`、无 seed/role 或生产业务测试行；只读 catalog/ACL 核查通过。 | 本项已完成；保留本地 shared container 仍旧的事实，不对其迁移/reset。后续 schema/业务改动另起验收，不将此次单 migration 核查扩大成所有 CAP 的线上验收。 | 隔离栈 `sl-dbtest-04074edf63` 已清理；remote history 含目标 migration；scope marker default false、关联表 Member-read-only RLS、authenticated-only overload grants、旧 helper 撤权、三个 trigger enabled 与 projection wrapper guards/rebuild 均经只读核验。 | `/root/normal_prepayment_executor` 执行；root/主会话完成 linked remote 核验 |
| P0-DOC-01（文档项完成） | 六份 P0 文档已同步 CAP 映射、主线 DB/Android/cloud 状态、9B native runtime、兼容 API 结果与 T0 边界；root 已审阅内容与任务分层。 | 文档结构和相对链接检查已完成；打开 README 供查看。P0 总体验收仍由未验证的 4B adapter 链和其他阶段门槛决定。 | 六个文档文件；17 个 CAP ID 齐全；相对文件/标题链接检查无断链。兼容 API 空内容列 P2；9B smoke 不替代 4B。 | GPT-6 Luna xhigh 文档执行；root/主会话最终审阅 |

## 工程阶段 P1–P6

| 阶段 | 当前差异与实现范围 | 通过条件/交付 |
|---|---|---|
| P1 · 可恢复骨架 | 建独立 Agent service/module、持久化状态、会话归属、身份检查、四语义协议快照和 Mock provider；实现重启恢复、重复请求去重、待确认暂停及运行脚本。当前仓库未找到 Agent Harness；此事实属于未来实现，不阻挡 P0 文档映射。 | 可启动服务及 Compose；不同账号隔离；query/clarify/propose 模拟状态重启后恢复；未持久化不承诺接收。先不开放真实业务写。 |
| P2 · 真实只读 | 接本机 ModelProvider 与成员授权 read RPC；传必要 DTO/policy 结果正文、做页面/实体引用校验、事实卡与澄清。 | 固定模型/提示/上下文/timeout；host→服务、身份和真实只读权限通过；有延迟/资源/失败证据。质量低则记录训练任务，不称查询质量通过。 |
| P2 · 兼容接口诊断 | 本次 Qwen 9B 原生 `/api/v1/chat` host/Docker 均返回非空消息；OpenAI 兼容 `/v1/chat/completions` host 64/128 与 Docker 64 均 HTTP 200 但 content 空、finish_reason=`length`。请求均为短合成输入，未改服务设置。 | 核对兼容 API reasoning/output 参数映射与可见回复行为；复现时使用受控小预算并记录解析后的 content/stats。原生 API 成功不代表兼容路径通过，也不作为 Agent 质量验收。 |
| P3 · 确认写入 | 从新增 Expense 及允许的 Expense 财务编辑开始；实现服务端可信 preview、用户确认绑定、事务内权限/版本重核、唯一执行键、持久回执和未知结果恢复。保留 App 原 LWW。CAP08 已有 Expense 更新无客户端 CAS；不得把事务行锁或 presentation optional CAS 误报为 Agent 确认契约。CAP13 return 若要暴露，须先增加/验证 return 专属 preview，不能复用“新增预存”的预览结果当余额返还 diff。 | Mock P3a 后与 T3 同模型 P3b 联调：未确认没有写；并发变化令旧预览失效；相同键不重复记账；响应丢失可查原结果；locked Expense 拒绝财务修改、presentation 路径仍可用。 |
| P4 · Android 接入 | 个人设置开关、入口、对话面板、页面快照和消息卡；真实登录/刷新/网络/后台恢复接通服务端事实，不在 App 内重复算账。 | 安装构建；两账号、两设备或等效隔离客户端验证切页/换号/断网/重启及原有功能。 |
| P5 · 能力扩展 | 逐项完成 CAP01–17 中剩余管理、Participant scope、外币、退款、Expense 删除、普通还款、预存、void、Final、dispute、archive 等已存在 backend capability 的 Agent 接入；按当前 ACL 和没有 restore 的边界实现。新业务 bug fix 与 Agent 注册分开验收。 | 所有待支持 CAP 有 accept/clarify/reject 用例、权限/版本/receipt 检查和独立测试；无静默丢项。没有 restore 能力的 Expense/Transfer 不注册恢复写工具。 |
| P6 · 首版验收 | 冻结候选、独立评测、备份干净恢复、运维/故障/限制文档。 | 金标准、权限、确认、并发、故障和独立语言集通过预设门槛；可恢复，未关闭越权/重复/错账阻断；证据与版本完整。 |

## 训练阶段 T0–T4

| 阶段 | 当前状态 / 任务 | 通过证据 |
|---|---|---|
| T0 · 随 P0 | 已盘点三指定 run、代表 checkpoints、失败教训、adapter config 和工具目录。待核 4B base 完整 snapshot、adapter merge、`Qwen3_5ForConditionalGeneration` converter 支持、量化后 LM Studio 真实加载。9B native smoke 只验证 9B runtime；D 盘余量足但 RAM 与权重/merge 峰值余量未证实，边界路径未找到 converter。指南允许链路暂时不可用时把实际格式/运行方案与 blocker 写清后再长训；不要求用大训练掩盖转换失败。 | 资产表与新旧语义适用性；或者独立复现的 merge→GGUF→LM Studio smoke，或者有明确错误日志、版本和资源/工具方案。旧资产文件不改。 |
| T1 · 随 P1，结合 P2 | 定义 answer/clarify/read/propose 语义、工具契约和版本/hash；新 family/state split 再建 train/validation/sealed。旧六类/Scope、D4、普通预存标签逐项标历史/复核。 | 冻结 schema/contract/data manifest/覆盖矩阵；新 sealed set 与 train/validation 按业务状态或轨迹族隔离，预先固定门槛。 |
| T2 · P2 基线后 | 用已审核数据针对性训练；先小批次检查模板、assistant action mask、loss、断点续训；按语义路由→参数→结果消费→澄清→propose 诊断分类后补数据。 | 可重现训练配置、数据哈希、checkpoint、冻结验证结果与未训练基线比较。只 loss 降低不通过。 |
| T3 · P3/P4 联调 | 导出训练候选到 LM Studio；在 Harness 测查询/澄清、允许 Expense 修改、locked 拒绝、工具故障和 stale preview。量化格式与训练 adapter 版本绑定。 | 实际模型 ID、格式/量化/上下文、完整轨迹与核心端到端报告；未确认写和伪造事实被挡，locked 拒绝，模型错误与工程边界分别报告。 |
| T4 · P5，P6 前 | 按 CAP01–17 扩充数据；失败分类后才补样本/训新版本；以验证集选候选，封存后独立测评。 | 所有 CAP 的按语义版本报告/manifest；若 sealed 失败案例用于调参，该集降级成 regression 并建立新独立 holdout。 |

## 已知不纳入本轮的项

本审计执行子任务仅写 P0 文档；未实现 Agent，未迁移/reset 本地共享 DB，未训练、发 chat 或 Teacher completion，未改持久服务配置、下载/安装/更新工具或模型，也未改冻结资产。主线另按授权完成 isolated DB 回归、scope migration 应用/只读核验及 9B 原生 host/Docker smoke；仅临时加载后定向卸载。既存 NewApi lint 构建检查失败未扩修。9B 原生 runtime 已通过；OpenAI 兼容响应空内容和 4B adapter merge/export 仍分别按 P2、T0 跟进。
