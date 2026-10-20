# P2 baseline calibration — 正式验收记录 R1

> **已复核（2026-10-20）：见 [独立复核记录 R1](P2_BASELINE_CALIBRATION_REVIEW_R1.md)。** 复核判定为 `VERIFIED_WITH_FINDINGS`（四条 leg 的实质数值全部可复算）／`NOT_ACCEPTED_AS_REPRODUCIBLE`（绑定关系未通过）。
> 复核指出并已在本文修正的两点：**(a)** pin 由**本机工作树的字节形态**生成，与干净 checkout 的行尾不一致（46 个仓库组件中 44 个在干净 checkout 上不匹配），因此 pin 不能作为可独立复现的"源码身份"；**(b)** 全量套件那两次运行产自**脏树**（`git_head=0022b00`、工作树非 clean），其与 `3fcb2fd` 的对应属历史推断而非 artifact 可证明。修复与重签建议见复核记录 §6；**在完成前，本文不应被当作可复现的正式验收使用，且需要 root 会签。**

**状态：`ACCEPTED_LIMITED_P2_READONLY_ENGINEERING_BASELINE`（2026-10-19；复核后降级为"实质成立、绑定待修"）。**

本文件是 T1 准入清单中 **P2 baseline calibration** 这一项的 P2 侧正式验收记录，取代此前只有自报摘要的状态。**它通过的是「只读链路工程基线」，不是模型质量，也不是云端部署。**

## 1. 验收对象与边界

| 项 | 内容 |
|---|---|
| 通过的是什么 | 当前源码在**本机隔离环境**下，以当前 pin 装配的 P2 v3 只读链路：真实身份校验 → 真实 RLS 读取 → Store 独立接受 → 类型化 QEV/fact → 受保护答案 → 身份恢复 |
| **不是**什么 | 不是模型质量结论（`INSUFFICIENT_SAMPLE`）；不是云端 Supabase 验收；不是 CAP01–CAP17（仍 0/17）；不是业务写入路径（`Gateway` 仍 `Unimplemented`）；不是 v3 candidate 的基线/生产地位裁决（未裁决，见 [v3 profile 状态](P2_V3_PROFILE_STATUS.md)） |
| 候选开关 | v3 与 native 默认关闭。本记录的全部运行都是**显式开启**这两个开关、在隔离环境中进行的诊断，不代表默认装配行为已改变 |

## 2. 绑定对象

| 项 | 值 |
|---|---|
| 执行 manifest | `D:/AI/runs/shared-ledger/p2/postfix-pin-20261019-01/p2-v3-execution-manifest.json` |
| manifest SHA-256 | `362e66ad04491be4f711c8db076f5bb0736904b5d6e9962a9f13ba82e6e8a848` |
| 组件绑定 | 49 个 component，**对本机工作树逐组件复核 0 处 mismatch**。⚠️ 该 pin 由工作树字节生成，行尾形态与干净 checkout 不一致；复核在 `3fcb2fd` 的干净 checkout 上测得 44/46 不匹配（内容相同、行尾不同）。独立复现须先规范化行尾，见 [复核记录](P2_BASELINE_CALIBRATION_REVIEW_R1.md) R1-1 |
| 源码提交 | `agent` 分支 `3fcb2fd`。**四条 leg** 与它逐条绑定（各 leg 的 artifact 记录了同一 manifest 摘要）；**全量套件**两次运行记录的是 `git_head=0022b00` 且工作树非 clean——`0022b00` 是 `3fcb2fd` 的父提交，字节等同但属历史推断，artifact 本身不足以证明（复核 R1-2） |
| 模型 | 本地 LM Studio `t0-cp36-20261007`（Q4_K_M，native `/api/v1/chat`，context 8192，input 6144，schema margin 512，output 1536，`reasoning=off`，HTTP 90s） |
| 数据库 | D 盘独立 project id 的**隔离**本地 Supabase 栈；未触碰业务本机栈，未触碰任何云端 |
| harness | `D:/AI/runs/shared-ledger/p2/current-postfix-live-20261018-01/`（`bridge.py` loopback HTTPS 只读转发器；`close_loop.py` 驱动器） |

旧 pin `5df93c7f…` 及其证据**不覆盖**本记录描述的行为，不得用于替代本记录。

## 3. 四条证据 leg

| # | leg | 结果 | 关键量 |
|---|---|---|---|
| 1 | 零模型 POST 闭环 | `CLOSE_LOOP_COMPLETED` | 真实 GoTrue 鉴权、真实 RLS 读取（activities/activity_members）、Store 接受、1 QEV / 1 fact proof、受保护答案引用该 QEV、**0 次模型 POST**、业务写入 0 |
| 2 | 真实模型闭环 | `CLOSE_LOOP_COMPLETED` | **2 次 POST**（均 HTTP 200）、模型自主选 `read.activities`、2 条 source 收据、1 QEV、1 fact proof、1 受保护答案；answer 引用**本次新铸**的 QEV，文本含**本次刚创建**的活动名 → 接地端到端成立；两次 POST 的 `reasoning_output_tokens=0` |
| 3 | 身份恢复（零模型 POST） | `AUTH_RESUME_COMPLETED` | 恰好 1 次受控真实上游鉴权故障 → `WAIT_INPUT/auth_required` → `/resume/auth` 202 → 复用单逻辑查询、attempt `1→2` 均 page 0、额度不变 → `COMPLETED`、claim 已释放 |
| 4 | 身份恢复（真实模型） | `AUTH_RESUME_COMPLETED` | 同 #3，且用 **2 次真实 POST** 完成读与答 |

证据目录：`D:/AI/runs/shared-ledger/p2/current-postfix-live-20261018-01/run-*/close-loop-result.json`（含 `orphan_invariant`、`attempt_*_after_resume`、`query_ids_after_resume`、`protected_output_citations`、`model_response_sha256` 与原始 `model-response-*.json`）。

**身份恢复出口条件**以权威 Store 行为准判定：`orphan_invariant: settled`、`state=COMPLETED`、`claim_token=null`。

## 4. 全量套件（必须连同调用方式引用）

- **调用方式（四条前提，缺一不可）**：`agent/tests` **整个目录一次调用**；`P2_V3_STORE_TEST_ROOT` 与 `P2_STORE_TEST_ROOT` **每轮都新建为空目录**（且目录须**预先存在**，否则 sqlite 无法建库）；在**原始 checkout 路径**下运行（三个迁移用例硬编码了该绝对路径，复核 R1-4）；每轮新建的目录在运行前清空。
- **结果**：**745 passed, 1 xfailed, 1 warning**；`export_contracts --check` exit 0。**连跑两次结果一致**。
- 1 个 xfailed 是刻意的 `xfail(strict)`，钉住「消息文本 2000 字上限使 24 条事实无法作答」这一已知缺口（见限制 2）。
- 证据：`D:/AI/runs/shared-ledger/p2/batch-full-20261019-03/`、`D:/AI/runs/shared-ledger/p2/batch-full-20261019-04/`。⚠️ 两份 `baseline-result.json` 记录的 stdout SHA-256 **不可从保存文件复算**（保存时多做了一次换行转换，文件里出现 `\r\r\n`，复核 R1-3）；结果文本本身可读，结论以上表为准。

⚠️ **该套件用固定文件名且从不清理**：复用 store 根目录会产出数十项与代码无关的假失败（实测过一次 50 项）。仅跑单文件、或不新建目录时，结果不保证一致。**引用「745 passed」必须同时引用上述调用方式，否则不可复现。**

## 5. 已知限制逐条判示

| # | 限制 | 本记录判定 | 理由 |
|---|---|---|---|
| 1 | Store 一页续读上限（≤32 事实；运行时窗口 4 页但 Store 门闩未开） | **接受**（能力扩展留 P5） | 超限 fail closed，绝不给部分答案；客户端收到不可重试的「收窄查询」提示。P2 出口要求是「读链路可用」，不是「容量够大」 |
| 2 | 消息文本 2000 字上限（约 22 条事实以上答不出） | **分类已修 → 接受**；**容量治本留 P5** | 不再把「永远不可能成功」报成可重试；容量需与卡片压缩规则一起设计（2A） |
| 3 | 模型协议不遵循（answer 多出契约未声明字段） | **已修，接受为「已缓解」** | 提示词白名单修订落地后，本次真机 answer 根对象恰好是契约四字段，先前多余字段消失。**遵循率未采样**，故不据此给质量结论 |
| 4 | 身份恢复遗弃缺陷（Turn 卡 RUNNING、持 claim 无终态） | **已修，接受** | `_finalize_claim` + 两条 CPU 回归；真机两条 leg 均为 `settled` |
| 5 | 云端 Supabase 未验收 | **不接受为已验证**（明确未测） | 本记录全部产自隔离本地栈；云端属独立门 |
| 6 | CAP01–CAP17 = 0/17 | **不在本记录范围** | P2 基线不替代 CAP 验收 |
| 7 | 模型质量 `INSUFFICIENT_SAMPLE` | **明确不结论** | 累计真实模型 Turn 数量不足 |
| 8 | v3 candidate 的基线/生产地位未裁决 | **本记录不裁决** | 本记录接受的是「显式开启候选开关、隔离环境下的只读工程基线」，与该候选是否成为基线是两件事 |
| 9 | 套件完全确定性（曾有一条时钟混用用例） | **已修，接受** | 基准前移 10 秒（兼顾真实时钟顺序与 30 秒 claim 租约）；单文件 4/4、全量两次一致 |
| 10 | 恢复期间 events 进度接口持续 503（约 7.5s 窗口） | **接受为已知限制，留 owner** | 不影响 Turn 落定局与 claim 释放；503 标可重试，重试可恢复。根因未定位，文档已标注「是否早于本批修复未确立」 |

逐条细节见 [P2 已知限制清单 R1](P2_KNOWN_LIMITS_R1.md)。

## 6. 本记录明确不建立

云端 Auth/RLS、模型质量或遵循率、CAP、业务写入、v3 候选的基线地位、以及「默认装配已启用 v3」——这些均未建立，且不得由本记录推断。

**query-zero 证据口径**：RBR01 的权威定义是**冻结的 T1 protocol v1.1.0 typed query evidence**；P2 v3 的 `query_zero_classification` 只是候选内部字段，**不被本记录采纳为协议、也不构成 T1 可引用的权威**。裁定与理由见 [v3 profile 状态](P2_V3_PROFILE_STATUS.md) 的「query-zero 证据口径」一节。

## 7. 复现方式（简）

1. 起 D 盘隔离 Supabase 栈（独立 project id），确认本地 LM Studio 已加载 `t0-cp36-20261007`（如需 **live** leg）。
2. 以 §2 的 manifest 与四个 `AGENT_P2_V3_EXECUTION_*` 绑定作为环境启动 harness；`offline` 可零模型 POST 运行，`live` 需模型已加载。
3. 依次跑四条 leg，逐条读取 `close-loop-result.json`。
4. 全量套件按 §4 的调用方式与**每轮新建**的 store 根目录运行。

## 8. 签署

- 产出方：P2（本会话）
- 产出日期：2026-10-19
- 验收依据：本文 §2–§5 的可复核证据
- 独立复核：**已做产出方自审式再验证，仍非组织独立**，见 [复核记录 R1](P2_BASELINE_CALIBRATION_REVIEW_R1.md)（`VERIFIED_WITH_FINDINGS` / `NOT_ACCEPTED_AS_REPRODUCIBLE`）。作为 T1 准入的关闭依据，仍须 root 会签。
