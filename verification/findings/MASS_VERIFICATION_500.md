# 500-case 大规模业务漏洞扫描报告

**状态：`MASS VERIFICATION 500: COMPLETE`**

- 日期：2026-09-25
- 代码基线：Stage 3（`MASS VERIFICATION PIPELINE: READY`）提交后的固定版本
- 只读分析；未修改业务 migration / RPC / `BUSINESS_LOGIC.md` / Android / Judge Prompt / `TEST_TMP.md`
- 结构化清单：[business_bug_candidates_500.json](business_bug_candidates_500.json)

> **后续裁定（2026-09-25）**：本报告正文及 `business_bug_candidates_500.json` 保留 500-case 当时的候选、严重度和复现统计，不代表当前待修清单。`MASS500-001` 已由新 migration 修复：原失败 Scenario 在隔离本地 Supabase 重放为 `EXECUTED`，30 个数据库测试文件、223 条断言通过，详见 [MASS500_001_FIX.md](MASS500_001_FIX.md)。`MASS500-002` 裁定为 **DOCUMENTATION_AMBIGUITY / NOT_A_BUG**：单条 ExpenseDebt base 金额无需逐人等于 Split base/net，原币债务准确、base 非负且总量守恒即可；该规则已补入 `BUSINESS_LOGIC.md` §7–8。`MASS500-003` 为字段单位可观测性问题，`MASS500-004` 为数值表示差异，均未发现资金计算错误。正文中“先修 001”及“002 待决”的措辞仅反映原扫描时点。

---

## 0. 最终结论

| 项 | 数值 |
| --- | --- |
| 500-case 实际有效样本数 | **456 唯一有效**（`unique_valid_count`，456 个不同场景） |
| 异常总数 | **27**（21 FAIL + 2 UNCERTAIN + 1 JUDGE_ERROR + 3 RUNNER_FAILED） |
| 聚类后独立问题数 | **4 个 BUSINESS_BUG 候选** + 5 条记录在案的非候选 |
| BUSINESS_BUG 候选数 | **4** |
| CRITICAL | **0** |
| HIGH | **1** |
| MEDIUM | **2** |
| LOW | **1** |
| 建议交给 Codex | `MASS500-001`(HIGH)、`MASS500-002`(MEDIUM)、`MASS500-003`(MEDIUM, 置信度 0.5)、`MASS500-004`(LOW) |
| 是否建议进入 2000-case | **建议先修 `MASS500-001`，再决定**（理由见 §9） |

**一句话**：核心资金路径（还款、预存、退款、作废、混合流程）在 500 次随机场景下**零异常**；全部异常集中在 AA 的 base 币种投影/取整、一个会拒绝合法 Expense 的算术缺陷，以及多币种结算分配记录的字段语义。

---

## 1. 执行统计

```
generated=500  focus_valid=494  focus_mismatch=1  duplicate=38
unique_valid=456  distinct_scenarios=456  coverage_rate=91.2%
compiler_repair=0  loader_valid=494  loader_invalid=3
runner_executed=492  runner_failed=3
judge: PASS=468  FAIL=21  UNCERTAIN=2  JUDGE_ERROR=1
有效 PASS rate = 431 / 456 = 94.5%
```

> `judge:` 一行是**全部 500 个 case** 的原始裁决计数；`有效 PASS rate` 的分母是 `unique_valid_count = 456`（去掉重复场景与非有效样本），其分子 431 是这 456 个中的 PASS 数。两者差值来自 38 个 `DUPLICATE_CASE` 与 6 个未产出场景的样本。

| 指标 | 数值 |
| --- | --- |
| 总耗时 | 6990 s（**1.94 小时**） |
| 吞吐 | **257.5 cases/hour** |
| Generator / Compiler / Runner / Judge 平均 | 8.65 s / 11.83 s / 0.55 s / 55.97 s |
| 队列最大长度 | raw 20 / compiled 20 / judge 20（均触到上限，背压全程生效） |
| DeepSeek timeout | **3**（均为 network，占约 1500 次调用中的 0.2%） |
| DeepSeek 429 | **0** |
| worker 崩溃 | 0 |
| 本地 Supabase | 无重启（Up 18h, healthy）、连接数 14 恒定、DB 16→31 MB、`fatal/panic/deadlock` **0 条**、REST/Auth 错误 **0 条** |

### 按 focus 分布

| focus | n | PASS | FAIL | UNCERTAIN | JUDGE_ERROR | RUNNER_FAILED | 异常率 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| multi_currency | 20 | 12 | 7 | 0 | 0 | 0 | **35.0%** |
| final_settlement | 10 | 8 | 0 | 0 | 0 | 2 | 20.0% |
| multi_payer_aa | 40 | 33 | 6 | 1 | 0 | 0 | 17.5% |
| aa_rounding | 30 | 25 | 4 | 1 | 0 | 0 | 16.7% |
| single_payer_aa | 30 | 26 | 3 | 0 | 0 | 1 | 13.3% |
| refund_boundary | 25 | 24 | 0 | 0 | 1 | 0 | 4.0% |
| expense_aa | 30 | 29 | 1 | 0 | 0 | 0 | 3.3% |
| completion_archive | 10 | 9 | 0 | 0 | 0 | 0 | **0.0%** |
| fifo_repayment | 30 | 30 | 0 | 0 | 0 | 0 | **0.0%** |
| large_activity | 15 | 15 | 0 | 0 | 0 | 0 | **0.0%** |
| linked_refund | 25 | 24 | 0 | 0 | 0 | 0 | **0.0%** |
| manual_split | 30 | 30 | 0 | 0 | 0 | 0 | **0.0%** |
| mixed_flow | 15 | 15 | 0 | 0 | 0 | 0 | **0.0%** |
| multiple_repayments | 30 | 30 | 0 | 0 | 0 | 0 | **0.0%** |
| negative_expense | 20 | 20 | 0 | 0 | 0 | 0 | **0.0%** |
| prepayment_after_debt | 25 | 25 | 0 | 0 | 0 | 0 | **0.0%** |
| prepayment_before_debt | 25 | 25 | 0 | 0 | 0 | 0 | **0.0%** |
| prepayment_refund | 20 | 19 | 0 | 0 | 0 | 0 | **0.0%** |
| prepayment_return | 20 | 20 | 0 | 0 | 0 | 0 | **0.0%** |
| targeted_repayment | 30 | 29 | 0 | 0 | 0 | 0 | **0.0%** |
| void_transfer | 20 | 20 | 0 | 0 | 0 | 0 | **0.0%** |

**21 个 focus 中有 13 个异常率为 0%**，覆盖了全部还款模式（FIFO / TARGETED / 多次）、全部预存模式（四类）、关联退款、负数调整、作废转账、混合流程、手工分摊、大型活动与归档。

---

## 2. 方法

1. **500 case 执行**：`build_batch_plans` 预生成全部 ScenarioPlan（seed 1000–1499，按 §1 权重映射到 21 个 focus），经 Stage-3 流水线执行（Qwen 单路、DeepSeek 4 并发、有界队列 20）。
2. **异常池**：Judge FAIL / UNCERTAIN 与 RUNNER_FAILED 进入池中；`FOCUS_MISMATCH`、`DUPLICATE_CASE`、`COMPILER_INVALID`、`BAD_SCENARIO`、`ENVIRONMENT`、`WORKFLOW` 记录后继续，不中止批次（全程未中止）。
3. **DeepSeek 二次分析**（新增 `anomaly_analysis.py`）：把异常池连同**本地签名统计**交给 DeepSeek 按可疑根因聚类，再对每个聚类的**代表 case 完整证据包**（ScenarioPlan / raw_case / scenario / operations / state_final / judge / focus）做分类与严重度判定。
4. **复现确认**：对 BUSINESS_BUG 候选用**同一份已保存 scenario** 重跑（不重新生成场景），写入 `<case>/repro/<run_id>`，不触碰原始证据。
5. **PASS 抽查**：从 431 个 PASS 中随机抽 **34 个（7.9%）**，逐例让 DeepSeek 判定 Compiler 是否改变意图、是否真的命中 focus、Judge 是否漏判。

### 2.1 对分析结果的两处修正（重要）

DeepSeek 的聚类/分类是**建议**，不是最终裁定。本次有两处我核查后做了修正：

- **拆出 `MASS500-001`**：DeepSeek 把"合法 Expense 被拒绝"（RUNNER_FAILED，1 例）并入了 base 取整投影聚类（14 例）。我把它拆成独立候选并把严重度从 MEDIUM 提到 **HIGH** —— 拒绝一笔合法资金事实与 0.1 的投影尾差不是同一量级。
- **降低 `MASS500-003` 置信度**：DeepSeek 判 BUSINESS_BUG/MEDIUM(0.85)，但 **§6 复现失败**（FAIL → PASS）。按 §6 要求降低置信度至 0.5 并注明，不排除是字段语义歧义而非缺陷。

各聚类对同一问题的分类在两次分析间出现过翻转（`total_prepayment_precision` 由 BUSINESS_BUG/MEDIUM(0.9) 变为 JUDGE_FALSE_POSITIVE(0.84)），这类不稳定在本报告中一律以我核查后的结论为准，并保留分歧。

---

## 3. 提供给 DeepSeek 的输入

按 §4 要求，分类阶段的输入包含：`scenario_plan`、`raw_case`、`scenario`、`operations`（前 60 步）、`state_final`、`judge`、`focus`，以及该聚类在批次中的**出现次数与成员 case id**。聚类阶段的输入是全部 27 条异常的紧凑表（focus / verdict / runner / error_category / judge summary / 前 5 条 differences / 失败操作）加上本地签名分组统计。所有产物经 `judge._clean_json` 脱敏。

---

## 4. 严重度分布

| 严重度 | 数量 | 候选 |
| --- | --- | --- |
| CRITICAL | **0** | — |
| HIGH | **1** | `MASS500-001` |
| MEDIUM | **2** | `MASS500-002`、`MASS500-003`（置信度已下调） |
| LOW | **1** | `MASS500-004` |

没有任何候选涉及"金额凭空增减""债权债务方向错误""原始资金事实被改写"或"真实 Transfer/Prepayment 被改变"。

---

## 5. Confirmed / High-confidence Business Bug Candidates

### MASS500-001 — AA base 债务分摊可为负，导致合法 Expense 被整笔拒绝（**HIGH**，置信度 0.9，已复现 1/1）

- **focus**：`single_payer_aa`（任何 AA focus 都可能触发）
- **代表 case**：`20260925T085415387133Z_single_payer_aa_e4ce0d`
- **预期**：0.3 CNY 的 AA 账单由 alice 全额支付、5 人平摊，每人原币 0.06 CNY。这是完全合法的资金事实：§6 规定不得因债务问题拒绝 Expense，§7 固定原币分摊，§8 更明确要求"原币非零但 base 舍入为零的 Debt 仍须保留"。应正常落库。
- **实际**：`create_expense_auto_rate` 直接失败，SQLSTATE **23514 `expense base debt allocation cannot be negative`**；Expense、Payment、Split、Debt **全部没有写入**，活动停留在零财务事实。
- **根因区域**：`private.rebuild_expense_debts_locked` 的 base 分摊算法（`20260923022250_business_logic_finalization.sql` 约 409–419 行）：每一对 debtor-creditor 的 base 用 `round(original_amount * fx, 1)` **独立取整**，然后把**最后一对**设为 `(债权人 base 净额 − 已分配)`。当独立取整的合计已经超过债权人 base 净额时，这个"plug"变成负数，整个事务抛错。
- **触发条件**：`(n−1) × round(P/n, 1) > P`（P 为账单金额，n 为 AA 人数，单一付款人且本人也参与分摊）。实测 P=0.3/n=5 触发；P=0.4、0.6、1.2、3.3 不触发（与 `(n−1)·r > P` 完全吻合）。这是**确定性**的：同一场景每次都会触发。
- **证据**：`scenario.json`、`operations.jsonl` 第 1 步失败记录、以及同一 scenario 的重跑复现（`<case>/repro/`）。

### MASS500-002 — 跨债务 base 币种尾差：单笔债务 base 与自身分摊不符（**MEDIUM**，置信度 0.8，已复现 1/1）

- **focus**：`multi_payer_aa`、`aa_rounding`、`single_payer_aa`、`expense_aa`，**13 例**
- **代表 case**：`20260925T085255934396Z_single_payer_aa_26b856`
- **预期**：§5 要求 base 金额 1 位小数，且"base amount 舍入不得抹掉非零原币债务或改变债务双方"；§7 固定 AA **分摊**的尾差按 participant_order 稳定分配。**但 §5/§7/§8 都没有规定跨债务的 base 尾差如何分配。**
- **实际**：**原币债务完全正确**，**分摊的 base 也完全符合 §7**（尾差按顺序逐个分配，没有全压给最后一人）。问题只在 ExpenseDebt/BilateralDebt 的 base：它只守住了**总量**守恒，把 0.1 的 base 尾差整个压给**最后一条债务**，于是单条债务的 base 与其自身分摊相差最多 0.1 CNY。
  例（1.2 CNY，5 人 AA，alice 全付）：分摊 base `0.3/0.3/0.2/0.2/0.2`，债务 base 却是 `0.2/0.2/0.2/0.3`。
- **性质说明**：这条更像是**规则文档缺口**而非实现缺陷。**Judge 自己在其中 2 例返回了 UNCERTAIN**，理由是"规则没有规定 AA 尾差如何分配"。可执行的决策是二选一：在 `BUSINESS_LOGIC.md` 里写明跨债务 base 尾差策略，或者让单条债务 base 与自身分摊对齐。
- **证据**：13 例异常全部只差 0.1；每例的原币金额都等于 §7 值；代表 case 复现 FAIL → FAIL；两例 UNCERTAIN 的描述与该缺口一致。

### MASS500-003 — 多币种结算的 `transfer_allocations.amount` 是 base 值（**MEDIUM**，置信度 **0.5**，**未复现** 0/1）

- **focus**：`multi_currency`，**7 例**（19 个有效中占 37%）
- **代表 case**：`20260925T114525433875Z_multi_currency_0a4c6b`
- **预期**：§5 要求 Transfer 的分配事实引用来源 ExpenseDebt 的原币、base 金额与历史 FX。Judge 把 `transfer_allocations.amount` 读作"结算原币金额"。
- **实际**：外币结算时 `transfer_allocations.amount` 存的是 **base 值**（1.8600 EUR 的转账对应 14.6000），与 `base_amount` 重复；同一行的 `original_amount` **正确**存着 1.8600，且持久记录 `transfer_expense_allocations` 的 `payment_amount / original_amount / base_amount` **全部正确**。**没有任何资金事实出错**，只是那个裸 `amount` 列的含义没有文档定义。
- **复现**：**FAIL → PASS，未复现**。按 §6 置信度下调至 0.5，并倾向于认为这是**字段语义歧义**而非缺陷。
- **证据**：7 例全部只报这一个字段；每例的 `original_amount`/`base_amount`/`payment_amount` 都正确；复现未通过。

### MASS500-004 — `total_prepayment` 使用 4 位小数（**LOW**，置信度 0.6，未复现）

- **focus**：`expense_aa`，1 例
- **代表 case**：`20260925T085848194345Z_expense_aa_3376ea`
- **预期**：§5 "Activity base currency 金额使用 1 位小数"。同一对象里 `total_debt` 就是 `20.0`（1 位）。
- **实际**：`activity_financial_status.total_prepayment` 为 `"0.0000"`（4 位）。底层值为零，不影响任何资金事实。
- **分歧**：DeepSeek 判 JUDGE_FALSE_POSITIVE(0.84)，理由是字段为零。仍列出，因为 §5 对 base 币种精度有明确规定，而同一对象的两个汇总字段位数不一致；Codex 可判定其是否仅为显示问题。

---

## 6. Recorded but NOT for Codex

| 编号 | 分类 | 数量 | 说明 |
| --- | --- | --- | --- |
| MASS500-N01 | BAD_SCENARIO | 2 | `final_settlement` 生成的 plan 把结算双方写死，而服务端方案里没有该组合；另一例的外部还款把后续结算要用的债务先消耗掉了。**这是我自己的 plan 设计缺陷**，已修复（人数下限提到 4、外部还款移到结算之前），两个 seed 重跑均 PASS |
| MASS500-N02 | JUDGE_FALSE_POSITIVE | 1 | Judge 算术错误：它期望 1.93 EUR 对应 base 0.3，但 1.93 × 0.1273885350 = 0.2459，四舍五入就是 0.2（观测值） |
| MASS500-N03 | ENVIRONMENT | 1 | Judge 响应被判为 FORBIDDEN_CONTENT；该 run 本身执行成功且状态符合规则 |
| MASS500-N04 | WORKFLOW | 20 | **本地 FX fixture 方向写反了**：文档约定 `rate = r(base)/r(quote)`（ECB 的 r(X) = X per EUR），所以 `(CNY, EUR)` 行应是 7.85 而非其倒数。首轮 20 个多币种 case 的 base 金额全部错误。已修正 fixture 并**重跑这 20 个 case**，本报告只使用修正后的数据 |
| MASS500-N05 | WORKFLOW | 1 | `stage_compile` 在 CompilerError / DeepSeekApiError 分支没有 `run.save()`，这些 case 的 `result.json` 停留在 PENDING（内存状态正确）。已修复 |

另外 3 个 `COMPILER_INVALID`（2 个 EMPTY_RESPONSE、1 个 FORBIDDEN_CONTENT）与 1 个 `FOCUS_MISMATCH`、38 个 `DUPLICATE_CASE` 按 §2 过滤，不计入异常。

---

## 7. PASS 抽查（34/431 = 7.9%）

| 检查项 | 结果 |
| --- | --- |
| Compiler 保持 raw_case 核心意图 | **33/34** |
| Focus Contract 确实命中测试目标 | **28/34** |
| Judge 疑似漏判 | **8/34** |

**唯一一次意图漂移**：`negative_expense_897e9e` —— plan 要求 4 个参与者，编译后的 scenario 只剩 `[alice, dave]`，bob 与 carol 被丢掉（bob 仍作为分摊债权人出现）。**这是框架缺陷**：`stage_generate` 只校验 raw_case 的名单，没有校验编译后 scenario 的名单。已记录，未修（本任务不扩展 Workflow）。

**6 例 focus 未真正命中**（框架覆盖缺口，非业务问题）：

- `fifo_repayment` ×2：场景里只有**一笔**未结债务，FIFO 顺序无从区分（与 LIFO/TARGETED 等价）。
- `prepayment_refund` ×3：预存创建后**从未被消费也未被退回**，账户余额原样保留，focus 的区分性行为没有发生。
- `refund_boundary` ×1：还款是**全额**而非部分，两次退款合计 54/60（合同阈值 90% 过松）。

**8 例"疑似漏判"** 经核查全部落在已知的**可观测性歧义**或 **§7 明文规定**上，不是真实漏判：

- `return_prepayment` 响应里 `new_prepayment_balance` 为 null（2 例）；
- 操作响应里的 `financial_version` 是行版本而非 Activity 版本（与此前两轮报告同一问题）；
- `prepayment_accounts.base_balance` 在 CNY 活动中为 null（与 Stage 2 报告同一问题）；
- `aa_rounding` 的 base 分摊不等于 `amount × fx_rate` —— 但 §7 **明确规定**了 base 尾差按稳定顺序分配（示例 100.0 → 33.4/33.3/33.3），审阅者忽略了该条，属审阅者过度判定。

---

## 8. 复现确认（§6）

| 候选 | 代表 case | 原结果 | 重跑结果 | 是否复现 |
| --- | --- | --- | --- | --- |
| MASS500-001 | `..._single_payer_aa_e4ce0d` | RUNNER_FAILED / 23514 | RUNNER_FAILED / 23514 | **是** |
| MASS500-002 | `..._single_payer_aa_26b856` | EXECUTED / FAIL | EXECUTED / FAIL | **是** |
| MASS500-003 | `..._multi_currency_0a4c6b` | EXECUTED / FAIL | EXECUTED / **PASS** | **否**（置信度已下调） |

复现一律使用**已保存的同一份 `scenario.json`**，未重新生成场景；重跑结果写入 `<case>/repro/<run_id>`，原始证据与 `runs/` 完全未动。MASS500-001/002 无 CRITICAL，但为增强证据仍各做了一次复现。

---

## 9. 是否建议进入 2000-case

**建议先修 `MASS500-001`，修完再决定。**

理由：

1. 本轮 4 个候选中 3 个（`MASS500-001/002/004`）都指向**同一个函数** —— `private.rebuild_expense_debts_locked` 的 base 分摊算法。这是**一处集中修改点**，修完后这 15 例异常大概率一起消失，届时再做 2000-case 的边际信息量会明显提高。
2. `MASS500-001` 是**确定性可复现**的功能缺陷（不是概率性的），且会让一整个类别的合法 AA 账单无法创建；先修它再扩容更划算。
3. 若希望现在就看规模效应，2000-case 的预计成本是 **约 7.8 小时**（257.5 cases/hour），主要新增价值在于**其他 focus 的长尾**——但从本轮看，13 个 focus 的异常率为 0%，长尾很可能仍是同一函数。建议把 2000-case 的重点放在**提高 AA 系与多币种的权重**，而不是等比例放大。
4. 若要继续扩容，建议同时做两件低成本的事：把 `fifo_repayment` 的 plan 改成制造**至少两笔竞争债务**；把 `prepayment_refund` / `refund_boundary` 的 plan 与阈值收紧，让 focus 真正被命中（§7 的 6 例缺口）。

---

## 10. 产物与复现

```powershell
cd D:\project\Android\shared-ledger\verification

# 500-case 批次（本报告的数据来源）
#   plans = build_batch_plans(MIX, seed_base=1000)   # MIX 见 business_bug_candidates_500.json
#   run_pipeline(plans, config=PipelineConfig.from_env())
py -3.12 -m shared_ledger_verifier fx-fixture      # 外币 focus 前置：确定性本地 FX fixture

# 单例复现（MASS500-001）
py -3.12 -m shared_ledger_verifier run-generated-case --focus single_payer_aa --seed <seed>
```

- 覆盖/流水线数据：`local_llm_probe/coverage_reports/`、批次统计 JSON（含 `case_ids` / `coverage` / `pipeline`）
- 每个异常 case 的完整证据目录：`local_llm_probe/generated_cases/<case_id>/`，含 `plan.json`、`raw_case.json`、`scenario.json`、`operations.jsonl`、`state_final.json`、`judge.json`；复现证据在同目录 `repro/` 下
- 新增分析模块：`src/shared_ledger_verifier/anomaly_analysis.py`（14 项离线测试）；离线测试合计 **162 passed**，未删除任何失败 run

---

## 11. 禁止事项确认

未修改业务 migration / RPC / `BUSINESS_LOGIC.md` / Android 业务代码 / Judge Prompt；未为提高 PASS 率自动重跑；未删除任何失败 run；未部署远程；未修改 `TEST_TMP.md`；未扩展 Workflow 功能（唯一新增是本次任务要求的异常分析模块与其测试）。
