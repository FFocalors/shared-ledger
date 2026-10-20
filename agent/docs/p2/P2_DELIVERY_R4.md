# P2 delivery status R4 — 2026-10-19

> **已收口（2026-10-20）：P2 视为完成，转 P3b 待命。** 未消除的限制（功能/范围 + 复核出的 R1-1…R1-6 证据绑定缺陷）统一登记在 [P2 收口：已知限制一页](P2_CLOSED_LIMITS_R1.md)，并逐条标注「不影响训练，留待以后」。本文的通过结论与调用方式前提不变。

**本文是 P2 当前唯一入口。** R3 及其之前的状态只在两个地方仍有效：作为历史记录，以及作为「哪些缺口当时还没修」的对照。所有结论都以本文为准。

## 一句话

**真实只读链路工程基线通过（本机隔离环境，当前 pin），并附明确限制清单。** 模型读得好不好不在出口要求内，且仍未采样到可下结论的量。

## 当前 pin

- manifest：`D:/AI/runs/shared-ledger/p2/postfix-pin-20261019-01/p2-v3-execution-manifest.json`
- SHA-256：`362e66ad04491be4f711c8db076f5bb0736904b5d6e9962a9f13ba82e6e8a848`
- 49 个 component 对当前工作树 **0 处 mismatch**（逐组件复核）
- 源码：`agent` 分支 `3fcb2fd`（本批修复已提交）
- safe_config：native_candidate wire、model `t0-cp36-20261007`、endpoint `http://127.0.0.1:1234`、HTTP 90s、output 1536、context 8192、input 6144、schema margin 512、预算与旧 pin 逐项一致
- 旧的 `5df93c7f…` pin 已失效（分页改动落在其固定组件 `app/p2_runtime.py` 上），**不得**用它或它的证据描述当前源码

## 四条证据 leg（同一 pin、同一 harness、同一隔离栈）

harness：`D:/AI/runs/shared-ledger/p2/current-postfix-live-20261018-01/`（`bridge.py` 为 loopback HTTPS 只读转发器，`close_loop.py` 为驱动器）。隔离栈为 D 盘独立 project id 的本地 Supabase。业务写入全程关闭，`Gateway` 仍 `Unimplemented`。

| leg | 结果 | 关键量 |
|---|---|---|
| 零模型 POST 闭环（`offline`） | `CLOSE_LOOP_COMPLETED` | 真实 GoTrue 鉴权、真实 RLS 读取、Store 接受、1 QEV / 1 fact proof、受保护答案引用该 QEV、**0 次模型 POST** |
| 真实模型闭环（`live`） | `CLOSE_LOOP_COMPLETED` | **2 次 POST**（均 HTTP 200）、`read.activities`、2 条 source 收据、1 QEV、1 fact proof、1 受保护答案、`reasoning_output_tokens=0` |
| 零模型 POST 身份恢复（`offline-resume`） | `AUTH_RESUME_COMPLETED` | 故障后 `WAIT_INPUT/auth_required`、`/resume/auth` 202、单逻辑查询、attempt 1→2 均 page 0、额度不变、`COMPLETED` 且 claim 已释放 |
| 真实模型身份恢复（`live-resume`） | `AUTH_RESUME_COMPLETED` | 同上，且 **2 次真实 POST** 完成读与答 |

### 真实模型下接地是真的

`live` leg 的 POST 2 输出：

```json
{"kind":"answer","basis":"fresh_read_receipts","citations":["qev_wyfV_izBJUCDPPXGlBL5lo267uU"],
 "text":"当前活动列表包含一条记录：P2 postfix close loop 9e41381182，金额 0 CNY，状态 active。"}
```

引用的正是本次新铸的 QEV；文本中的活动名是本次运行刚通过真实 RPC 创建的活动，模型不可能先验知道。两次 POST 的输入 token 为 1938 / 2631，远低于 6144（提示词加长后仍有充足余量）。

### 身份恢复：复用与重读都实测到了

`live-resume` 的关键量：`auth_503_count=1`（**恰好一次**真实上游鉴权故障，非凭证被拒）；暂停后 `queries=1`、`attempt_seq=[1]`；恢复后 `query_ids` 只有一个、`attempt_seq=[1,2]`、两次 attempt 都是 page 0、`source_get_receipts=4`（原读 2 + 重读 2）、模型调用 3 与逻辑读取 1 **均未增加**。即：复用原逻辑查询、从 page 0 重读、不额外消耗额度，与文档描述一致。

出口条件「Turn 不再卡在 RUNNING、不再持有 claim 无终态」以权威 Store 行为准断言（`orphan_invariant: settled`，`state=COMPLETED`、`claim_token=null`）。

## 本批修了什么（对应四条裁定）

1. **身份恢复遗弃缺陷（已修）**：`_run_claim` 的收尾改为 `_finalize_claim`，先在仍持有 claim 时对账、再释放 claim；任何规划退出若 Turn 仍为 RUNNING 就落定局。CPU 回归 `agent/tests/test_p2_v3_claim_finalization.py` 覆盖两条路径（规划抛 `CancelledError`、规划静默返回）。
2. **2C 文本上限（分类已修，容量保留）**：答案文本超出冻结的 2000 字上限时，不再被兜成「可重试的内部失败」，而是不可重试的能力失败；21/22/24 条那种「合法但答不出」也不再骗客户端重试。
3. **3 超窗/截断分类（已修）**：运行时页窗口与 Store 容量拒绝都归入不可重试的「结果引用容量已达，请收窄查询后新建 Turn」。**未**改 Store 的页上限、**未**改白名单、**未**加错误码。
4. **4 提示词修订（已生效）**：白名单 + 显式禁止复制上下文/query evidence/page summary 的字段名，并禁止把服务端投影字段当作模型输出字段。**实测有效**：本批 `live` 的 answer 根对象恰好是契约声明的 4 个字段，之前两次真机失败的多余字段（`source_query_complete`、`model_projection_complete`、`has_more`）不再出现。两条 wire 的该句逐字节一致并有断言防漂移；**未**放宽 sent guard/契约/parser。

## 全量套件的调用方式前提（必须连同结果一起引用）

- **调用方式**：`agent/tests` **整个目录**一次调用；`P2_V3_STORE_TEST_ROOT` 与 `P2_STORE_TEST_ROOT` **每轮都新建为空目录**（该套件用固定文件名且不清理，复用目录会造成数十项与代码无关的假失败）。
- **结果**：`745 passed, 1 xfailed, 1 warning`，`export_contracts --check` exit 0；**连跑两次均为此结果**（`D:/AI/runs/shared-ledger/p2/batch-full-20261019-03/`、`-04/`）。1 个 xfailed 是刻意的 `xfail(strict)`（24 条事实的答案超出消息文本上限，见限制 2）。
- 仅跑单文件、或不新建目录时，结果不保证一致；引用时必须带上上述前提。

## 已知限制与验收记录

- 逐条限制与细节：[P2 已知限制清单 R1](P2_KNOWN_LIMITS_R1.md)。摘要：Store 两页上限（保留）、消息文本 2000 字容量（容量保留）、恢复期间 events 进度接口不稳（未定位根因，但不影响 Turn 落定局）、云端未验收、CAP 0/17、模型质量 `INSUFFICIENT_SAMPLE`、v3 profile 基线地位未裁决。
- **T1 准入清单中的「P2 baseline calibration」已有正式验收记录**：[P2 baseline calibration R1](P2_BASELINE_CALIBRATION_R1.md)（`ACCEPTED_LIMITED_P2_READONLY_ENGINEERING_BASELINE`），含逐条限制判示与本记录全部绑定量。
- **query-zero 证据口径已裁定并关闭**：RBR01 的唯一权威是冻结的 T1 protocol v1.1.0 typed query evidence；v3 的 `query_zero_classification` **不被采纳为协议**，仅作候选内部字段。详见 [v3 profile 状态](P2_V3_PROFILE_STATUS.md) 的 ruling 一节。

## 本文不建立什么

不建立云端 Supabase 结论；不建立模型质量结论（本批共 5 次真实模型 Turn，样本仍不足）；不建立 CAP01–CAP17；不建立「v3 candidate 已是基线」；不建立业务写入路径可用。
