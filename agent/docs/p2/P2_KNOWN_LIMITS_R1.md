# P2 已知限制清单（R1，2026-10-19）

本文是 P2「真实只读链路工程基线」的**随附限制清单**。它列出当前**确实存在**的功能缺口与未测项，供引用 P2 结论时一并引用；不把它们写清就等于夸大。

状态列：**已修**＝本批改动已落地并有 CPU 回归覆盖；**保留**＝按裁定本批不做，列为已知限制。

| # | 限制 | 现象 | 是否 fail-closed | 状态 |
|---|---|---|---|---|
| 1 | Store 一页续读上限 | 一次读最多 page 0 + 一个终止的第二页，即 ≤ 32 事实（`MAX_FACTS_PER_PAGE*2`）。运行时窗口派生出 4 页，但 Store 的门闩（`p2_source_store_v3.py:5369/5374/2545/2761/691` 等）使其不可达 | 是：超限拒绝并终态失败，绝不给部分答案 | **保留**（留 P5 与文本上限一起做） |
| 2 | 消息文本 2000 字上限 | `MessageEventPayload.text` 上限 2000 字（`contracts.py:3062`）。实测 18 条→1545 字通过、20 条→1715 通过、24 条失败；即合法两页读在约 22 条事实以上无法作答 | 是：不产出部分答案 | **分类已修**（不再报「可重试」）；**容量仍保留**（治本＝压缩卡片文本，留 P5） |
| 3 | 模型协议不遵循 | 当前 pin 上 3 次真机 Turn 中 2 次因 answer 根对象多出契约未声明字段被严格 sent guard 拒绝（业务内容正确） | 是：拒绝并终态失败 | **提示词已按批准修订**（白名单 + 禁止复制上下文投影字段名）；**新 pin 下尚未真机复验** |
| 4 | 身份恢复的遗弃缺陷 | 查询描述符已绑定后恢复，第 2 次规划任务被取消时回合被遗弃为 `RUNNING`（仍持有 claim、无终态或暂停事件） | 否——**这是唯一不 fail-closed 的一条**，属缺陷 | **已修**（`_finalize_claim` 保证任何规划退出都落定局 + 释放 claim；两条路径的 CPU 回归已过）；**新 pin 下待真机复验** |
| 5 | 云端 Supabase 未验收 | 全部证据产自 D 盘隔离本地栈；云端 Auth/RLS/双用户未跑 | — | **保留**（用户延期） |
| 6 | CAP01–CAP17 | 真实 Agent 能力验收仍为 **0/17** | — | **保留** |
| 7 | 模型质量 | `INSUFFICIENT_SAMPLE`：真实模型闭环 3 次 Turn 的样本量不足以谈准确率 | — | **保留**（按出口要求不追模型准确率） |
| 8 | v3 candidate 的基线地位 | 只有「disabled CPU candidate foundation」范围的 root 接受（2026-10-14 装配前批准、2026-10-15 R4 review），**没有**把它作为基线/生产路由的裁决；而它已被实际装配进 Runtime/Store/API，超出当时「unassembled」的表述 | — | **未裁决**，见 [v3 profile 状态](P2_V3_PROFILE_STATUS.md) |
| 9 | 套件完全确定性 | `test_p2_v3_store_recovery_edges.py` 的一条用例曾混用合成时间戳与真实时钟，导致全量与单文件调用结果不一致 | — | **已修**（基准前移 10 秒，兼顾真实时钟顺序与 30 秒 claim 租约；单文件连跑 4/4 通过）；全量连跑结果见证据目录 |
| 10 | 恢复期间进度通道不可靠 | 真实鉴权暂停 → `/resume/auth` 之后，`GET /v1/turns/{id}/events` 会**持续**返回 503 `dependency_unavailable` "The request could not be completed safely."（3/3 次离线恢复运行均为连续 15 次、约 7.5 秒，直到客户端放弃轮询）；而回合本身仍正常完成 | 是：Turn 照常落定局并释放 claim；503 标 `retryable=true`，重试即可恢复 | **未修，未定位到根因**（详见下节） |

## 关于限制 10 的实测细节（不夸大）

- **来源已定位到代码位置**：该 503 由 [api.py:289-290](../../app/api.py) 的 `_store_call` 通用分支产生——即 store 调用抛出了**既非 `StoreError` 也非 `ValueError`** 的异常。已用 `dependant.call` 包装确认：15 次全部是来自 events endpoint 内的 `_ApiFailure(503, …)`，不是中间件兜的。
- **是哪个 store 调用：按排除法推断**是 `read_turn_view`（该 endpoint 内唯一的 store 调用），**不是抓到的**——第一次尝试包装 `read_turn_view` 时我把已绑定方法当未绑定用，导致那一次运行本身报 `TypeError` 而作废；修正后的捕获在该运行窗口内未能取到，故此处标记为推断。
- **对产品行为的影响有限**：同一次运行里权威 store 行显示 `COMPLETED`/`terminal`/`claim_token` 已释放，`orphan_invariant` 为 settled；`read.activities`、4 条 source 收据、1 个受保护答案均正常。即**状态机是对的，进度读接口在恢复窗口内不稳**。
- **是否早于本批的 claim-finalization 修复：未确立。** 修复前对该窗口的观测被两个 harness 缺陷污染（桥在故障解除后重新武装、以及轮询对瞬时错误不容忍），所以没有可比的修复前数据。**不要**在引用时断言它由本批引入或早于本批存在。
- 复现与证据：`D:/AI/runs/shared-ledger/p2/current-postfix-live-20261018-01/run-*-offline-resume/`（其中 `read_turn_view_errors`、`transient_poll_errors`、`orphan_invariant` 字段可直接复核）。

## 与「不做」的边界

P2 明确不做、也不应据本文推断的事项：不追模型准确率、不开 P3、不接云端、不放宽任何安全边界（严格 sent guard、契约、parser、`extra="allow"` 都不动）。

## 引用建议

引用 P2 结论时请同时引用本文与当次运行证据的调用方式（全量目录调用 + 每个 store 根目录每轮新建），以及证据所绑的执行 pin。
