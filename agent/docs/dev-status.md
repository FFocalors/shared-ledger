# Agent 开发状态

## T1 release-v3 候选（2026-10-19）

四个 RBR 项已全部落到新版本。新 source freeze（27 文件，绑定 git head、91 文件 pin 快照与冻结 v1.1 manifest）；新候选 417 条（train/validation/sealed = 143/137/137，即 v2 形状 + 12 条原币 RBR04 覆盖行 + 12 条 base 币覆盖行）；RBR01 3 条、RBR02 414 条、RBR03 56 条、RBR04 24 条。RBR01：三条空结果读样本（packet 行 21/22/24）按数据集适用性政策要求的「显式转换」转到冻结的离线协议 v1.1.0 profile，答案由冻结的可信 renderer 生成并引用 `query_1`，两条 `backend_zero`、一条 `post_filter_zero`（后端确返回 5 条、被 title 后置筛选清空）保持可区分；RBR01 的权威定义取冻结 T1 v1.1.0 typed query evidence，P2 v3 的 `query_zero_classification` 是**未裁决候选**、仅作对齐目标，并入协议需另开 freeze（P2 已在 `P2_V3_PROFILE_STATUS.md` 记录同一裁定）。RBR03：56 条歧义澄清改用已返回事实列候选（标题/日期/金额/币种/参与人），回复用日期+金额选择，不再出现裸 `expense_ref`；提案、目标 ref 与金额不变。RBR04：按「覆盖缺失、非算法缺陷」补 24 条案例。**AA 量子裁定（按后端源码写入版本记录）：原币 `splits.amount` = 0.0001 量子（`p_original_amount * 10000`），base 币 `splits.base_amount` = 0.1 量子（`base_amount * 10`），两者是不同列、不是二选一；生成器保留原币 0.0001 分摊，base 列另行补齐。**base 案例覆盖 B01 原例 100.0/3 → 33.4/33.3/33.3、10.0/6 → 1.7×4/1.6×2，以及「原币有尾差、base 无」（150.01/6）与「外币两列都有尾差」（100.00 EUR @7.10 → base 236.7/236.7/236.6）。**落库语义**：创建时 base 尾差给最后一人，但每次 create/update/delete/restore 与修复路径都会调用 `redistribute_aa_split_base_amounts` 覆盖为「前 N 人各 +1」；训练数据存后者，转换器拒绝「最后一人兜底」形状；`payments.base_amount` 仍保留最后一人补差。RBR02：所有已转换行的模型输入与原始用户请求逐字相同。

产出：`D:\AI\runs\shared-ledger\t1-release-v3-20261020\`（`baseline-snapshot/` 91 文件 pin 快照；`review/source-manifest.json`；`candidate-v3/{train,validation}.jsonl`；`review/candidate-report.json`；`review/near-pair-review-v3.json` + `near-pair-dispositions-v3.json`；`review/human-review-v3/` 新 34 条 packet + pending receipt；`review/handoff/independent-near-pair-review/` 与 `review/handoff/human-receipt/` 两个交接包）。2026-10-19 那次准备保留为历史、不复用；每次准备用独立 run root，新 freeze 不复用旧 receipt。代码在 `agent/evaluation/t1_release_v3/`（profile / snapshot / schema / runtime / v11_evidence / convert / rbr03 / rbr04 / base_allocation / near_pairs / hashing / bridge / generate_v2_rows / freeze / build_candidate / packet / handoff / 三个 slice），信封 schema 由冻结 v2 schema 显式变换生成并内嵌冻结 v1.1 schema，并允许 `base_amount` 列。v2 生成与 v1.1 转换各 pin 一套冻结基线、不能同进程共存，因此生成阶段走隔离子进程，不弱化任何一边的 pin；`checker`/`signatures` 是纯记录分析，故在 pin 之前导入。v2 goldguard 硬要求澄清回复用 `expense_ref=`，故 RBR03 行自带 v3 gold 检查。

验证：417 行全部通过 release-v3 信封；写入的 414 个工具观测全部逐字节重放一致（一个反例已修：工具观测的 `request` 必须保持冻结模拟器实际消费的 v1 形状，typed post-filter 只放在 query observation 上）；family 计数 18 项恰为 20、read.expenses 为 24（新增 4 个 base family/split）；每条空结果证据由冻结 v1.1 harness 重新证明；每个 base 案例按声明的两列份额逐项比对并核对各自量子守恒；新 packet 选择确定（重跑得同一 packet hash），receipt gate 拒绝「pending 却声称已审」「无真人与证据的 approved」以及「即使签名也不等于 training_eligible」；`pytest agent/evaluation/t1_release_v3/tests -q` = 40 passed。改生成器后全量可读候选逐行比对仍与冻结 v2 零 mismatch（135 train / 129 validation），三份 v2 载荷哈希不变，既有 `t1_release/tests` = 122 passed 不变。近似项分析已覆盖全部三个 split（5,429 组：55 跨 operation、5,374 独立 state family，0 未分类），但标注为 `assistant_technical_review`——由产出数据的同一会话完成，不是 `root_agent` 独立裁定。

边界：**未准入**。collection gate 因 5,429 组 near-pair findings 未经独立 root 裁定而不通过（分析已完成且覆盖 sealed，但由产出会话自审，harness 的分类器也以 Self-Approval 拦下了把它改标为 `root_agent` 的尝试）；sealed 只生成校验、未写出（须在 gate 关闭后按一次性 receipt 最后写）；无 genuine human receipt（新 packet 与 pending 模板已就绪，签名需真人）；`human_reviewed=false`、`human_review_pending=true`、真实 CAP 仍 0/17、`training_eligible=false`。P2 已记录 `ACCEPTED_LIMITED_P2_READONLY_ENGINEERING_BASELINE`（2026-10-19，只读工程基线、明确未做独立复核、不是模型质量或云端结论），可作为准入输入但仍需 T1/root 记录；T2 授权仍是用户的决定。旧 393 候选、其 packet 与全部 receipt 字节不变，未读 sealed。详见 [release-v3 转换记录](t1/release-v3/README.md)。

## P2 当前 private-v3 检查点（2026-10-19；2026-10-20 收口）

**P2 已完成，转 P3b 待命。** 未消除的限制（含复核出的 R1-1…R1-6 证据绑定缺陷）统一登记在 [已知限制一页](p2/P2_CLOSED_LIMITS_R1.md)，逐条标注「不影响训练，留待以后」——含义是这些项不改变任何训练数据、模型输出或业务代码，因此不阻塞训练；但 P2 **不可作为可独立复现的对外验收依据**（pin 由本机工作树字节生成，干净 checkout 上 44/46 组件因行尾不匹配）。

**当前入口是 [P2 交付状态 R4](p2/P2_DELIVERY_R4.md)**（一句话：真实只读链路工程基线通过，带明确限制清单）。当前 source/config manifest SHA-256 为 `362e66ad04491be4f711c8db076f5bb0736904b5d6e9962a9f13ba82e6e8a848`（49 个 component 对当前树 0 处 mismatch，源码 `3fcb2fd`）；旧 `5df93c7f…` 已因分页改动失效，其证据不得用于描述当前源码。

**全量套件的调用方式前提必须连结果一起引用**：`agent/tests` **整个目录**一次调用 + 两个 store 根目录**每轮新建为空**。该调用下为 `745 passed, 1 xfailed`，`export_contracts --check` exit 0，**连跑两次一致**；1 个 xfailed 是刻意钉住的消息文本上限缺口。仅跑单文件或不新建目录时不保证一致。

Private-v3/native 默认关闭；业务写入全程关闭，`Gateway` 仍 `Unimplemented`。

新 pin 下四条 leg 全部通过（D 盘隔离 Supabase + 本地 `t0-cp36-20261007`），详见 [R4](p2/P2_DELIVERY_R4.md)：

- **零模型 POST 闭环** `CLOSE_LOOP_COMPLETED`：真实 GoTrue 鉴权、真实 RLS 读取、Store 接受、QEV/fact、受保护答案精确引用该 QEV；业务写入 0。
- **真实模型闭环** `CLOSE_LOOP_COMPLETED`：2 次 POST（均 200），answer 引用了本次新铸 QEV，文本含本次刚建的活动名，接地端到端成立。
- **零模型 POST 身份恢复** 与 **真实模型身份恢复** 均 `AUTH_RESUME_COMPLETED`：恰好一次真实上游鉴权故障 → `WAIT_INPUT/auth_required` → `/resume/auth` 202 → 复用单逻辑查询、attempt 1→2 均 page 0、额度不变 → `COMPLETED` 且 claim 已释放（`orphan_invariant: settled`）。
- **本批修复**：身份恢复遗弃缺陷（`_finalize_claim`，CPU 回归覆盖两条路径）；2C/3 能力失败分类诚实化（不再把「永远不可能成功」报成可重试）；4 提示词白名单修订**实测有效**（本次真机 answer 根对象恰好是契约 4 字段，先前的多余字段消失）。

v3 candidate 的裁决现状见 [v3 profile 状态](p2/P2_V3_PROFILE_STATUS.md)：只有「disabled CPU candidate foundation」范围的 root 接受，**没有**把它作为基线的裁决。分项限制见 [已知限制清单](p2/P2_KNOWN_LIMITS_R1.md)（Store 两页、消息文本 2000 字、恢复期间 events 进度接口不稳、云端未测、CAP 0/17、模型质量 `INSUFFICIENT_SAMPLE`）。历史入口另见 [P2 交付状态 R3](p2/P2_DELIVERY_R3.md)、[R2 当前状态](p2/R2_STATUS.md) 和 [P2 配置示例](p2/P2_CONFIGURATION_EXAMPLE.md)。

## P3a Mock 写路径（2026-10-19）

**引擎已实现并通过五条验收条件；HTTP 确认仍返回冻结的 501。** 详见 [P3a 实现记录](p3/P3A_MOCK_WRITE_PATH.md)。

- 链条：预览（沿用 Mock Runtime 的 `WAIT_CONFIRM`）→ 确认 → 固定命令 → Mock 账本上的恰好一次效果 → 持久回执（提案 `execution`、Turn `execution_resolution`、`execution_result` 事件三者一致）。
- **`execution_id` 是派生的**：确认时调用冻结契约的 `derive_execution_id(actor, proposal_id, revision)`，非派生 id 被契约拒绝。
- **未知结果按原键恢复**：写路径两次提交（钉死键 → 落效果 → 记结果），死在中间时 Turn 进 `RECOVERING`，运行时按键先查账再结算，缺行才用同一个键补做；未知永不写成终态。
- 四条验收条件各有对应用例：未确认不落账 / 同请求无重复效果 / 并发改账使旧预览失效 / 响应丢失可找回；另有正常闭环与"模拟提案不可执行"。
- **第五条（2026-10-21 补齐）：无权限 / 已归档的写提案在执行前拒绝。** 补齐前并不存在——`permission_checked` 只是 `Literal[True]` 的声明、Mock 无成员表也无 `archived` 概念；现由 `MockActivityRoster` 显式建模，并在派发、落账、恢复三个边界检查，6 条用例覆盖。权限来源仍是注入的 Mock，不代表真实 RLS 已验收。
- 全量：**760 passed + 1 xfailed**（调用方式前提同 P2：整目录一次调用 + 两个 store 根目录每轮新建）。
- 边界：不碰真实业务写入与云端、不动 P2 v3 防火墙、不碰 T1；HTTP 成功响应需先批准 [确认响应差异提案](p3/P3A_CONFIRM_RESPONSE_DIFF.md)。
- **pin 提示**：P3a 改动了 `store.py` 与 `runtime.py`，执行 pin `362e66ad…` 现已 2 处 mismatch、不再匹配当前树；新模块 `p3_execution.py` 不在该 manifest 的枚举组件内。

日期：2026-10-12
当前阶段：**P0 工程核查通过；T0 六步部署链验收通过；P1 限定工程范围通过；T1 protocol v1.1.0 离线协议冻结已批准；release-v2 数据准入及训练仍未完成，genuine human receipt、P2校准、T2授权pending**

Agent 项目路径：agent/  
本次指南源文件 SHA-256（下载的 v0.3 HTML；源文件未修改）：40e2c2b017c71a3081e3e7460dd964a34af7484f0ae6be17d896a28c11d39a09

## 当前状态与版本化快照（2026-10-12）

- **T0：**六步部署链验收通过；提交 `1a80a0f29e1ea432a60b95e7437af23d51182938` 已推送，跟踪引用一致。T0 运行证据见下方按日期保留的历史记录及 [T0 清单](t0/README.md)。
- **T1 protocol v1.1.0 离线冻结（2026-10-12）：**[Root receipt](file:///D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/ROOT-FREEZE-APPROVAL.json) `352dcba6cce50c249709be37ba96fd2427b43958406ec570fb5cd2a183ea2036` 批准离线协议冻结；最终36-file manifest SHA-256 `5665565eb503c16e5e8c8ca6cb207743ee52e5add1b0b27c7aeca8cc3a6a80c3`。范围为 25/25 PF、22 package tests、46 root probes、17 independent export checks、10 schemas、5 examples，CAP01–CAP17 execution/external writes 全false。具体边界与证据见 [v1.1.0协议冻结](t1/protocol-v1.1.0/PROTOCOL.md)、[root review](t1/protocol-v1.1.0/ROOT_REVIEW.md)。这是离线协议门，不是数据准入/真实后端/模型验收；training_eligible=false，genuine human review、P2 calibration、T2 authorization仍pending，Student按用户指示延期，GPU未运行。下一轮数据须fresh source freeze/new candidate，修复RBR01–04并重跑Gold/replay/near/split及人审；旧111/393候选和receipt不改、不复用。
- **P1：**主会话批准限定工程范围通过（`PASSED_LIMITED_P1_ENGINEERING`）：126 pytest passed（34.25s）、本地 Auth 29/29、Docker 部署/备份恢复与重启恢复证据通过，107 个 P1 源码文件 manifest 全匹配；55 个生成 contract 文件复核匹配且 `export_contracts --check` exit 0。通过范围只包括可恢复骨架、Mock Runtime、身份隔离和 Docker 恢复；不代表真实业务 Backend、工具执行或模型质量通过。P1 文件仍未提交，完整限定与边界见 [P1 终审](p1/FINAL_REVIEW.md)。
- **T1 数据与候选：**API/语义/操作/轨迹版本为 1.0.0。旧 `t1-synth-1.0.1` 仍是获诊断用途审批的111条（train/validation/sealed各37），manifest SHA-256 `f87eae34f7d77632701ed3fcf1090e1e6a5adedcbe5e39342241a44448f0dddf`、approval SHA-256 `8b5f94329a3c2e7f1c008152ebc440fcb2434c6af32d05da8775307583ae7188`；其15组潜在prompt近重复和 `INSUFFICIENT_SAMPLE` 是旧版记录。release-v2 候选现已写入393条（train/validation/sealed分别135/129/129），全393条strict schema、independent Gold与deterministic replay零失败；exact duplicate/state leakage均为0，24个boundary rows不计入positive family floor，18个operation×split的独立family count均为20。Root对4,984组near findings均完成技术处分，当前未解决项为0；这不替代人审。Source manifest `f92f5074d898ba25922bbd609e1c2fed2f82780eb4b03427c9317dacf03cbfc3`，collection `382dda0a21ab42d12f11df72794e1c8cece866cb0b557a8b592d0a1268aa1c86`，creation manifest `08bebb9c96101d6be09c4d5273d4ff7b019c4608c8057aeac64b661f3e0ea820`，checker report `0fa561067849b9233ddbe23245aaa8710a34e0c9d5d934bf6ecb0f3e7339dd21`，write metadata `8316a5bfcc358a1fbfb76e4400972ab03eddf4085914b61d05117c045f1b3ba2`。candidate与哈希细节见[T1 release-v2记录](t1/release-v2/README.md)和[候选准备记录](t1/release-v2/CANDIDATE_PREPARATION.md)。
- **模型 / Teacher：**用户选择将Student实际模型评估延期，状态为 `NOT_TESTED_USER_DEFERRED`；没有Student推理或质量 PASS。模型 preregistration 仍在任何模型输出前冻结，64项来源指纹匹配，并绑定manifest、approval、protocol fingerprint及validation/sealed bundle hashes；这只是冻结运行方案，不代表已评估。sealed one-shot评测授权为false。Teacher最新v2检查限于一次请求、三个短合成文本案例，root limited semantic review通过3/3；Teacher data quality仍为 `NOT_ASSESSED`，并非训练数据。此前v1 evaluator因400字符截断而隔离的解释保持不变。19项evaluator单元测试只验证评分器、runner门禁和受限回放逻辑，不是模型质量测试。详见[T1索引](t1/README.md#model-evaluation)及[Teacher v2 readiness](t1/release-v2/TEACHER-READINESS.md)。
- **人工审核与准入：**Root已完成34条train-only逐项业务复核，报告SHA-256 77ce270ee836d889f119008348caaa702781e667a61a44e4964b84e826c9f7ad，结论REQUIRES_TRAINING_DATA_REVISION。34/34业务文字、金额与范围正确；31/34输出来源通过，rows 21/22/24的空结果缺少来源绑定。12项资金提案的Decimal总额/allowlist独立检查通过。逐项root_note见[T1 root业务复核](t1/release-v2/ROOT-BUSINESS-REVIEW.md)，P2接续任务见[P2校准发现](t1/release-v2/P2-CALIBRATION-REVIEW-FINDINGS.md)。其他训练质量待办：33/34条context.input_text有人为已读取并消费提示；rows 19/20/26使用裸expense_ref澄清；rows 15/16/17的AA分配都能整分，故此包未覆盖AA最小单位尾差。第21/22/24条业务文字正确，但结果来源需可引用；其中22是5条已读结果再经title筛选为空，需绑定过滤条件和完整性，21/24为tool空结果。P1现有citation类型不含read-result引用；任何typed-query citation或canonical协议调整必须版本化并重新freeze，不得静默改旧协议或伪造Fact/Policy/citation。Root报告不是genuine human receipt，仍human_review_pending=true、human_reviewed=false；P2 baseline calibration和显式T2授权pending，Student仍按用户决定延期，training_eligible=false。冻结候选和packet不改；数据修订必须新版本及fresh source freeze，不能复用旧receipt。sealed仅核对root receipt/hash/行数，无语义readback，模型评测授权false。
- **业务能力：**本轮 Agent 后端验收为 `NOT_RUN_RESOURCE`；当前真实 Agent CAP01–CAP17 为 **0/17 可验收**，默认真实 Backend/Gateway 尚未接入。现有 Mock 验证不等于业务通过。B01–B14 后端测试映射、隔离回归未运行事实和确切缺口见 [业务验收报告](t1/BUSINESS_ACCEPTANCE.md)；prereg 输入哈希绑定 main `3f938ee6114b763e6cd3dbd10792a78c691eb526`。
- **工作树/授权边界：**业务 main 该基线保持 clean；Agent 分支的 P1 与 T1 新工作未提交。release-v2候选仅写入D盘本地证据路径，不涉及云端业务写入、模型评测或训练。

以下章节是此前按各自时间点保留的状态快照和证据。其 P1、T1、数据库回归及模型待办措辞如与本节冲突，以本节和链接的最新验收文件为准；原历史事实不改写。

## 历史快照与证据（按各节原记录时间保留）

P0 工程核查按统一指南验收条件已通过：现状、CAP/RPC 参数与角色权限映射、环境/资产证据及未决项归属均有记录；不要求 P1/P3 先实现。9B 原生 host/Docker chat 是前序独立验证；OpenAI 兼容 chat/completions 空 content 单列 P2。T0步骤1–5实测、固定输入对照与静态资产适用性审核已完成；步骤5的4B Q4_K_M host/Docker smoke和服务/日志生命周期复核通过，步骤6共享文档、D盘日志归档与C原hold清理完成，T0六步部署链验收通过（2026-10-08）。详见[T0清单](t0/README.md)、[HF报告](t0/runs/20261008-hf-loader-preparation.md)、[F16/Q4/HF对照](t0/runs/20261008-f16-cpu-comparison.md)和[LM smoke报告](t0/runs/20261008-lmstudio-q4-smoke.md)。

## P0 原始核查工作区快照（历史记录）

- 分支：feature/ai-training-pipeline
- HEAD：dcdb033b9cc245f355f61b5a303007b7d7571e18
- 当前工作树保留前序普通活动预存限制及相关 Android、数据库夹具、业务文档和 verifier 未提交修改；本轮另有子活动 Participant 范围、Expense 跨账本投影修复、对应测试与文档未提交变更。未覆盖既有修改，没有提交。
- 新项目路径创建前，仓库没有根 README.md 或 agent/；既有 AI 资料在 docs/ai/，冻结协议与训练资产未改。

## 当前 Agent 与业务工作区（2026-10-07 拆分后）

- Agent 文档/开发工作区：D:/project/Android/shared-ledger-agent；分支 agent，本次 T0 核查起点 HEAD 82ad2994084ff964746aa43476a923d30cf26d09。并行P1文件包括 `agent/app/__init__.py`、`agent/app/contracts.py`、`agent/docs/p1/P1_DEVELOPMENT_PLAN.md`；P1正在并行进行协议冻结，进展以`agent/docs/p1/`记录和实际文件为准。P1文件未改动或暂存；本次提交只含T0文档/metadata，Git提交推送以agent/origin/agent实际记录为准。
- 工作区迁移历史（2026-10-07）：654个原文件（25,259,017 bytes）已留存在 `D:/computer/Hermes/backups/agent-worktree-relocation-20261007/retained-source`，654项hash/size已核验；同级`retained-source.codex-worktree-name.marker`为0字节且已核验。旧Codex附件metadata仍指向C盘，D盘attach返回“The checkout exists but is not a managed worktree.”；本轮只读观察显示原C盘Agent worktree与`relocation-hold`均不存在、枚举为0，清理主体/方式未核实。历史[relocation-final-status.md](D:/computer/Hermes/backups/agent-worktree-relocation-20261007/relocation-final-status.md)在13:08记录当时hold有174个空目录且清理请求被拒；仅为历史快照。
- 当前业务源码工作区：D:/project/Android/shared-ledger；分支 main，HEAD 3f938ee6114b763e6cd3dbd10792a78c691eb526。最新提交包含 35 个业务相关文件，origin/main 已同步且工作区 clean；当前业务实现、迁移与测试核对以此工作区为准。
- Agent工作区根目录的 `app/`、`supabase/`、`docs/backend/` 是旧业务基线，不能替代当前main实现；新 `agent/app/` 是并行P1工程文件。下文业务文件链接使用main工作区绝对路径；P0原始审计的旧branch/HEAD仅作历史快照。

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

## P0 工程核查结论与证据

- 已盘点当前分支、提交、工作树、AGENTS/项目说明及真实 App/后端入口，记录在[工程审计](p0/engineering-audit.md)；本次 T0 起点与当前并行 P1 文件另见本页工作区快照。
- [CAP01—CAP17 能力表](p0/capability-map.md) 已静态映射有效迁移定义、App payload 与 ACL；scope migration 的远端 catalog/ACL 已只读核验。CAP 全角色真实客户端端到端实测仍是后续验收，不是本路线图 P0 的通过前提。
- Teacher 配置中的 provider opencode、model deepseek-v4.1-flash、endpoint 与公开路由已静态核对；本次未发请求，认证、额度和实际availability尚未验证，作为独立后续任务而非T0关闭门。指定run的历史盘点见[资产记录](p0/t0-assets-and-lessons.md)；T0实测以[清单](t0/README.md)及对应运行报告为准。
- 9B 原生 host/Docker 合成请求及统计已由主审复核通过；OpenAI兼容 /v1/chat/completions 空content单列P2。A-only训练时base精确快照仍未证明。T0步骤3 attempt3 merge与checkpoint1219 raw-copy builder已通过，HF v4固定三例均为finite float32[248320]且base+adapter/merged生成IDs相同；raw logits非逐位相等。步骤4 F16/Q4三格式对照完成，首token argmax全匹配，raw logits非逐位相等，严格数值等价未建立；详见[T0清单](t0/README.md)和[F16/Q4/HF对照报告](t0/runs/20261008-f16-cpu-comparison.md)。步骤5已用model key t0-cp36-20261007、publisher shared-ledger加载Q4_K_M（SHA acfd01df6cbd3c8e1fa4dbe144f5852290689851c4f92d4ab892707d08724b34；D目标与批准文件同FileID硬链接，非9B），host/Docker各两case均HTTP 200、client exit 0、instance匹配；严格JSON通过。524次采样最低可用RAM 9.798 GiB、GPU free最低4077 MiB，无保护门越界；定向卸载该instance后remaining=0。server运行前后均为stopped；D日志稳定SHA-256 E15741505DF01B53438A75EAFDD2B68BB24EB4C78298AFC66AA387F1086BB597。运行后C日志目录快照33 files/19,214,214 bytes的逐文件SHA已与D历史归档匹配；归档位于 `D:\AI\runtime\lmstudio\server-log-history\pre-t0-20261007-200705`，C原plain hold已清理，C junction保留并指向D active。清理证明SHA-256 25e315f94c53414c57cafa0a493f5a6335a37e4f446616a40beabc90b0e92146。完整证据见[4B LM Studio smoke报告](t0/runs/20261008-lmstudio-q4-smoke.md)。
- P0 的交付是有证据的工程/能力映射/环境与资产记录，以及有明确归属的缺口清单；不要求在 P0 内实现 Agent 骨架或所有功能。

## 已定位的后续实现缺口（不作为 P0 完成前提）

- P1：正在并行进行协议冻结并推进初步工程文件；当前进展以 `agent/docs/p1/` 记录和实际文件为准。本轮可见 `agent/app/contracts.py` 等文件，但服务骨架、持久化、认证隔离与恢复验收尚未因此宣称完成。
- P3：真实后端 preview、确认后执行、执行回执、重复确认与未知结果恢复的端到端集成尚未验证。
- P1/T1：新版 Agent 协议、CAP 范围与历史数据适用性需独立版本化；旧协议/冻结训练资产不原地改写、不无标记混训。
- P3：为 Agent 确认执行设计可验证的版本失效与重复/未知结果恢复；现有 Expense 财务更新无 `expected_version`/CAS，不能改变原 App LWW。
- P0 工程核查按指南条件已通过；T0步骤1–5核心运行、对照和静态资产审核完成，步骤5生命周期已验证，步骤6共享文档、D盘日志归档和C原hold清理完成，T0六步部署链验收通过（2026-10-08）；日志归档、静态适用性审核与根主审完成。P1正并行冻结协议/推进工程文件；本次未调用Teacher、未训练、未做云端业务写入或发布Android客户端。9B验证仍是此前独立记录。
