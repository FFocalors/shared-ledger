# P2 v3 读取页窗口：运行时推广与仍存的上限（R1）

**状态：运行时已推广为有界 N 页；端到端 N≥3 仍不可达，原因在 Store 侧，未改。** 本文不改契约、不改 Store。

## 1. 运行时改动（`agent/app/p2_runtime.py`）

原实现把分页硬编码为「page 0 + 一个终止的第二页」，并在 `p2_runtime.py:1157` 以「续页必须产生恰好 page_index==1 且终止」的断言 fail closed。现改为：

- **页窗口由既有上限派生，不新造预算**（`_v3_read_page_window(max_model_calls)`）：
  - 每页占一次模型调用：`model_calls(pages) = 选择(1) + (pages-1)×续页(1) + 回答(1) = pages + 1`，故模型预算单独允许 `max_model_calls - 1` 页
  - 另两个**已存在且更紧**的上限：`p2_read_backend.MAX_PAGES_PER_QUERY`（=4）与 `codec3.MAX_FACTS_PER_QUERY // codec3.MAX_FACTS_PER_PAGE`（64//16=4，即 manifest 的 `rows_per_table` / `get_rows_per_page`）
  - 窗口 = `max(1, min(三者))`；默认 6 次调用 ⇒ **4 页**（`(6)→4 (5)→4 (4)→3 (3)→2 (2)→1 (1)→1`）
  - 原 `reserved_model_calls = 3 if planned_read else 1` 改为具名常量，取值逐位不变（选择 + 1 次续页 + 回答 = 3）；该预留是**下限**，真正上限仍由 Store 逐次计费
- **逐页安全序列完整保留**（审计确认无遗漏）：续页决策必须严格等于授权的那一个（`validate_sent_p2_v3_decision` + `parse_p2_decision` 的相等性检查）；每页重建 `_active_grant` / `_make_verified_context`；`next_page_ref` 只取自服务端 minted 的 continuation；`read_candidate_v3 → accept_p2_v3_query_attempt → issue_p2_v3_page`（Store continuation nonce 单次消费）；返回页号必须等于 `expected_page_index`；读后重新 `_ensure_claim_current` + `_fresh_identity` + `_current_gate`
- **末页仍 `has_more` 一律 fail closed**，绝不把截断投影当作最终结果

测试：新增 `agent/tests/test_p2_v3_read_page_window.py`（6 个用例，含 1 个 `xfail(strict)`）；未改动任何既有测试文件。

## 2. 端到端 N≥3 仍不可达：Store 侧的页数门闩（未改）

真实 Store 仍把一次读限在两页，门闩位置（均未改动）：

| 位置 | 约束 |
|---|---|
| `p2_source_store_v3.py:5369-5370` | accept 拒绝 > `MAX_FACTS_PER_PAGE*2`（>32 事实连 page-0 收据都不给） |
| `p2_source_store_v3.py:5374-5375` | accept 拒绝 `page_index==1 and has_more` |
| `p2_source_store_v3.py:2545` | `begin_p2_v3_query_attempt` 拒绝 `page_index != 0` |
| `p2_source_store_v3.py:2761` | `consume_p2_v3_continuation` 拒绝 `page_index != 1` |
| `p2_source_store_v3.py:691` / `:2439` / `:6510` | registry 发行与 `issue_p2_v3_page` 只允许 page 0 的完整收据发行一次 continuation |

因此「两页都 `has_more`、第三页才终止」在真实 Store 上**不成立**。该事实被钉成 fail-closed 证据（用例 3/4/6），**没有**伪造一条绿色的 N≥3 链路。要真正打开需同时改 Store 的发行、消费与 accept 三处（可能连带迁移常量与文档），超出本次允许的文件范围，留 owner 决策。

同时：v1 checkpoint 仍只预留 3 次调用（与旧行为一致）。N≥3 时真实调用数为 N+1，Store 逐次计费仍是硬上限，但 checkpoint 会低记；放开 Store 页数时应把预留改为 `页窗口+1` 并在每页补记。

## 3. 新发现：消息文本上限比页窗口更紧（既有缺口）

`MessageEventPayload.text` 上限 2000 字（`agent/app/contracts.py:3062`）。实测同一操作的事实条数与答案文本长度：

| 事实数 | 答案文本 | 结果 |
|---|---|---|
| 18 | 1545 字 | 通过 |
| 20 | 1715 字 | 通过 |
| 24 | — | 失败 |

24 条时 `_commit_v3_answer` 内 pydantic 抛 `string_too_long`，被 `except Exception` 兜成 `dependency_unavailable / internal_failure / retryable=true`。

后果：**合法且被 Store 允许的两页读（上界 32 事实）在约 22 条以上无法作答**，且对客户端表现为"可重试的内部失败"，即重试也不会成功。已用 `xfail(strict)` 钉住该行为，避免它被遗忘。修法（压缩卡片文本 / 放宽契约 / 改判为不可重试的能力失败）属产品决策，未做。

顺带：`_closed_error`（`p2_runtime.py:3061`）只放行固定三元组，新增的 `CapabilityUnavailable` 文案（含"超过页窗口"）一律塌缩为 `dependency_unavailable / internal_failure / retryable=true`，所以截断对客户端也表现为可重试的内部失败——与 v3 其它能力失败一致，但语义上值得单独给一个不可重试的分类。

## 4. 验证

- 定向：`test_p2_v3_runtime_activity_flow.py` + `test_p2_v3_runtime_semantics.py` + `test_p2_v3_store_recovery_edges.py` + `test_p2_v3_query_store_acceptance.py` + `test_p2_v3_read_page_window.py` → **63 passed, 1 xfailed**
- 全量目录调用：**743 passed, 1 xfailed**（`D:/AI/runs/shared-ledger/p2/recheck-full-20261018-04/`）
- 注意调用方式前提：见 `P2_SUITE_REPRODUCIBILITY_R1.md`

## 5. 未决项

1. 是否打开 Store 的一页续读上限（需改 Store 三处 + 预留记账），以及打开后 `MAX_FACTS_PER_PAGE*2` 与页窗口如何对齐
2. 消息文本 2000 字上限的处置（压缩 / 放宽 / 改判）
3. 截断与超窗是否应改成不可重试的独立错误分类

## 6. 连带影响：旧执行 pin 已不再匹配当前源码树

本次改动落在 `agent/app/p2_runtime.py`，而该文件是 manifest pin
`5df93c7fe360e8cedda27b2ca38379c031cd227768f31f7505c127bcd3dd92c6` 的 49 个固定组件之一。
提交后逐组件复核：**恰好 1 处 mismatch，即 `agent/app/p2_runtime.py`**，其余 48 个仍匹配。

因此：

- 该 pin 对应的是**改动前**的源码（截至提交 `aaf9fc3`）。本文与 `P2_LIVE_CLOSE_LOOP_R1.md` 里
  的全部真机/闭环证据都产自那个源码状态，**不是**本次分页改动之后的源码。
- 现在若直接用旧 pin 起一次 v3 运行，会因组件哈希不匹配而 fail closed——这是正确行为。
- 任何后续 live（含身份恢复）运行**必须先重新生成执行 manifest**（`agent.app.p2_v3_manifest_cli`，
  参数与四元绑定见 `P2_CONFIGURATION_EXAMPLE.md`）；新 pin 在重新跑出证据之前**没有**任何真机证据，
  不得沿用旧 pin 的证据描述它。
- 未擅自重新生成 pin，以避免把"旧源码的真机证据"隐式挂到"新源码的 pin"上。
