# 2000-case 大规模业务漏洞扫描报告

**状态：`MASS VERIFICATION 2000: COMPLETE`**

- 日期：2026-09-26
- 代码基线：`2835119`（MASS500-001 修复 + BUSINESS_LOGIC 对 002/003/004 的裁定）
- migration：**43/43 从零应用**（`supabase db reset --local` 后全新栈）
- 只读分析；未修改业务 migration / RPC / `BUSINESS_LOGIC.md` / Android / Judge Prompt / `TEST_TMP.md`
- 结构化清单：[business_bug_candidates_2000.json](business_bug_candidates_2000.json)

## 复核后裁定（2026-09-26）

下文 §0–§11 及 JSON 中原有的 `codex_action_required` 保留 **2000-case 扫描时的候选快照**；其中“1 个 BUSINESS_BUG / MEDIUM”不再代表当前待修业务缺陷。当前裁定以本节和 JSON 的 `post_review_resolution` 为准。

| Issue | 当前裁定 | 处理 |
| --- | --- | --- |
| MASS2000-001 | `DOCUMENTATION_AMBIGUITY`，非已确认业务 Bug | 保留现有 manual Split 算法。既有 pgTAP `phase2c_base_amount_normalization.sql` 明确要求手工分摊的 base 尾差由 `participant_order、id` 稳定顺序的最后一人承接；`fair_aa_base_allocation.sql` 的公平逐单位分配仅针对 `split_method = 'aa'`。已在 `BUSINESS_LOGIC.md` §7 限定 AA 与 manual 各自的规则。原币及 base 总额均守恒，历史数据无需改写。 |
| MASS2000-002 | `NOT_A_BUG` | `transfer_allocations.amount` 是 base currency 数值；`49.5000` 与 `49.5` 数值相等，四位小数为列的表示精度。已在 `BUSINESS_LOGIC.md` §5、§21 明确数值比较与展示精度；无需资金代码变更。 |
| MASS2000-003 | `DOCUMENTATION_AMBIGUITY` | 保留现有债务配对和 final settlement 算法。配对及方案生成有服务端稳定顺序；客户端以当前服务端方案和财务版本为准，不能从姓名或跨 run 的新 UUID 推断方案项目顺序。已在 `BUSINESS_LOGIC.md` §8、§14 明确确定性范围与执行契约。 |

因此当前没有由这三项确认的数据库业务修复。`prepayment_usage_not_applied` 和 `final_settlement_transfer_allocations_missing` 仍是已排除的 Judge 误判；无需重新打开 MASS500 已裁定事项。

---

## 0. 最终结论

| 项 | 数值 |
| --- | --- |
| 2000 个计划中实际唯一有效样本 | **1572**（`unique_valid_count`，1572 个不同场景） |
| 异常总数 | **54**（40 FAIL + 4 UNCERTAIN + 6 JUDGE_ERROR + 2 真实 RUNNER_FAILED + 2） |
| 聚类后独立问题数 | **10 个聚类** → 收敛为 **3 个 Codex 待办** + 7 类记录在案 |
| BUSINESS_BUG 候选数 | **1** |
| CRITICAL | **0** |
| HIGH | **0** |
| MEDIUM | **1**（`MASS2000-001`） |
| LOW | **0** |
| DOCUMENTATION_AMBIGUITY | **2**（`MASS2000-002`、`MASS2000-003`） |
| 建议交给 Codex | 上述 3 项（1 个业务缺陷 + 2 个文档歧义） |
| 是否值得扩大到 5000+ | **不建议**（理由见 §10） |

**一句话**：上一轮修复 + 文档裁定之后，21 个 focus 中 **11 个异常率为 0%**，AA 系的异常率从 ~15% 降到 0~1.1%；2000 个新场景只找出 **1 个新的业务缺陷**（MEDIUM，多币种手工分摊的 base 尾差落点），另有 2 处文档歧义。其余 41 条异常经逐条核查全部是 Judge 误判、环境问题或测试框架缺陷。

---

## 1. 执行统计

```
generated=2000  focus_valid=1963  focus_mismatch=20  duplicate=391
unique_valid=1572  distinct_scenarios=1572  coverage_rate=78.6%
compiler_repair=0  loader_valid=1970  loader_invalid=13
runner_executed=1968  runner_failed=15
judge: PASS=1522  FAIL=40  UNCERTAIN=4  JUDGE_ERROR=4
有效 PASS rate = 1522 / 1572 = 96.8%
```

| 指标 | 数值 |
| --- | --- |
| 总耗时 | 28371 s（**7.88 小时**） |
| 吞吐 | **253.8 cases/hour** |
| Generator / Compiler / Runner / Judge 平均 | 8.19 s / 12.58 s / 0.56 s / 57.5 s |
| 队列最大长度 | raw 20 / compiled 20 / judge 20（全程触顶，背压生效） |
| DeepSeek timeout | **10**（network，约占 6000 次调用的 0.17%） |
| DeepSeek 429 | **0** |
| worker 崩溃 | **0** |
| 本地 Supabase | 无重启（Up 8h, healthy）、连接数 14 恒定、DB 31→58 MB、REST/Auth 错误 **0 条** |

`error_categories`：`network 10`、`FORBIDDEN_CONTENT 7`、`EMPTY_RESPONSE 6`、`SCENARIO_FORMAT 13`（框架缺陷，见 §6）、`FOCUS_MISMATCH 7`、`RUNTIMEERROR 2`。

**Supabase 日志复核**：9 小时窗口内只有 2 条 FATAL，均已定位——一条是容器初始化前的探针（`role "postgres" does not exist`，与 500-run 期间同一条），一条是瞬时的 `terminating connection due to administrator command`，**容器未重启、运行未中断、数据完整**。按 §5 的中止条件，本轮**没有触发任何中止**。

### 1.1 计划空间（一个重要前提）

2000 个唯一 seed 只产出 **1632 个不重复的 ScenarioPlan（81.6%）**；实际落库时 duplicate 检测判定 **391 条重复**，因此 `unique_valid = 1572`。重复集中在 `prepayment_refund`、`linked_refund`、`negative_expense`、`prepayment_return` 这些 plan 维度天生较少的 focus。

我没有为了把数字做漂亮而扩 plan 空间（§12 禁止扩建 Workflow），也没有挑选 seed 规避重复（那会让"重复率"这个指标失真）。**所以本轮的有效样本是 1572，不是 2000**；重复样本仍然执行并被 Judge 裁决，只是不计入唯一覆盖。

---

## 2. 按 focus 分布

| focus | n | PASS | FAIL | UNCERTAIN | JUDGE_ERROR | RUNNER_FAILED | 异常率 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| final_settlement | 75 | 51 | 6 | 3 | 1 | 2 | **16.0%** |
| multi_currency | 250 | 218 | 30 | 0 | 0 | 0 | **12.0%** |
| mixed_flow | 60 | 58 | 1 | 0 | 1 | 0 | 3.3% |
| prepayment_refund | 70 | 65 | 1 | 0 | 1 | 0 | 2.9% |
| completion_archive | 75 | 73 | 0 | 0 | 2 | 0 | 2.7% |
| manual_split | 60 | 58 | 0 | 1 | 0 | 0 | 1.7% |
| aa_rounding | 90 | 88 | 1 | 0 | 0 | 0 | 1.1% |
| fifo_repayment | 100 | 99 | 1 | 0 | 0 | 0 | 1.0% |
| large_activity | 100 | 99 | 1 | 0 | 0 | 0 | 1.0% |
| refund_boundary | 110 | 106 | 1 | 0 | 0 | 0 | 0.9% |
| multi_payer_aa | 170 | 167 | 0 | 0 | 1 | 0 | 0.6% |
| **expense_aa** | 30 | 29 | 0 | 0 | 0 | 0 | **0.0%** |
| **linked_refund** | 110 | 110 | 0 | 0 | 0 | 0 | **0.0%** |
| **multiple_repayments** | 100 | 100 | 0 | 0 | 0 | 0 | **0.0%** |
| **negative_expense** | 80 | 78 | 0 | 0 | 0 | 0 | **0.0%** |
| **prepayment_after_debt** | 80 | 79 | 0 | 0 | 0 | 0 | **0.0%** |
| **prepayment_before_debt** | 80 | 80 | 0 | 0 | 0 | 0 | **0.0%** |
| **prepayment_return** | 70 | 70 | 0 | 0 | 0 | 0 | **0.0%** |
| **single_payer_aa** | 100 | 99 | 0 | 0 | 0 | 0 | **0.0%** |
| **targeted_repayment** | 100 | 100 | 0 | 0 | 0 | 0 | **0.0%** |
| **void_transfer** | 90 | 89 | 0 | 0 | 0 | 0 | **0.0%** |

**11/21 个 focus 异常率为 0%**，覆盖了全部还款模式、全部预存模式、关联退款、负数调整、作废转账。

---

## 3. 异常二次分析（DeepSeek 聚类 + 我的逐条核查）

异常池 54 条交给 DeepSeek 按可疑根因聚类，得 10 个聚类。**DeepSeek 的分类是建议，不是裁定**——我对每个聚类都做了独立核查，其中 **2 个聚类的分类被我推翻**。

| 聚类 | 数量 | DeepSeek 判定 | 我的核查结论 |
| --- | --- | --- | --- |
| `multi_currency_split_tail_stable_order` | 28（数据层 60） | BUSINESS_BUG/MEDIUM | **BUSINESS_BUG / MEDIUM** ✓ 一致 |
| `transfer_allocations_decimal_precision` | 2 | DOCUMENTATION_AMBIGUITY | **DOCUMENTATION_AMBIGUITY** ✓ |
| `judge_uncertain_underspecified_algorithms` | 4 | DOCUMENTATION_AMBIGUITY | **DOCUMENTATION_AMBIGUITY** ✓ |
| `prepayment_usage_not_applied` | 2 | BUSINESS_BUG/**HIGH** | **JUDGE_FALSE_POSITIVE** ✗ 推翻 |
| `final_settlement_transfer_allocations_missing` | 4 | BUSINESS_BUG/MEDIUM | **JUDGE_FALSE_POSITIVE** ✗ 推翻 |
| `final_settlement_plan_execution_completion` | 4 | BAD_SCENARIO | **BAD_SCENARIO + Judge 过度判定** ✓ |
| `judge_forbidden_content` | 7 | WORKFLOW | **ENVIRONMENT** ✓（归类微调） |
| `linked_refund_debt_netting_direction` | 2 | JUDGE_FALSE_POSITIVE | **JUDGE_FALSE_POSITIVE** ✓ |
| `aa_rounding_bilateral_direction` | 1 | JUDGE_FALSE_POSITIVE | **JUDGE_FALSE_POSITIVE** ✓ |
| `multi_currency_transfer_allocation_judge_anomaly` | 1 | JUDGE_FALSE_POSITIVE | **JUDGE_FALSE_POSITIVE** ✓ |

另有 1 条 `refund_boundary` FAIL 未被单独聚类，我核查为 JUDGE_FALSE_POSITIVE。

### 3.1 我推翻 DeepSeek 的两处（重要）

**① `prepayment_usage_not_applied`（DeepSeek 判 BUSINESS_BUG/HIGH，conf 0.85）→ 实为 JUDGE_FALSE_POSITIVE。**
Judge 要求"用预存去清偿欠第三方的债务"。但 §12 明确预存账户的维度是 **Activity / Owner / Custodian**，且"**相反方向的未结债务不能提前消费另一方向的预存**"。
- `mixed_flow_886de3`：预存 owner=carol、custodian=**alice**，Judge 要它清偿 carol→**bob** 75.0 —— custodian 根本不是 bob。
- `large_activity_d5ec34`：预存 owner=bob、custodian=**alice**（30.0，已按 §12 清偿 bob→alice 26.8，余 3.2），Judge 要剩余的 3.2 去清偿 bob→**carol**。
两个成员的实际状态都与 §12 完全一致。**这条如果直接交给 Codex，会是一次错误的业务改动。**

**② `final_settlement_transfer_allocations_missing`（DeepSeek 判 BUSINESS_BUG/MEDIUM，conf 0.62）→ 实为 JUDGE_FALSE_POSITIVE。**
Judge 说 `transfer_allocations` 里缺少 final settlement 转账的行。但**通过的** final_settlement 案例形状**完全相同**（final settlement 的贡献记录在 `final_settlement_paths` 与不可变的 `transfer_expense_allocations`，不在当前贡献投影里）。同一形状在别处 PASS、在这里 FAIL —— 是 Judge 不一致，不是投影错误。

---

## 4. Confirmed / High-confidence Business Bug Candidates

### MASS2000-001 — 外币手工分摊的 base 尾差整个压给最后一人（**MEDIUM**，置信度 0.8）

- **focus**：`multi_currency`
- **发生次数**：**60 / 248** 个外币案例存在 base 尾差（其余 188 个独立折算即守恒），**60/60 全部把尾差压给最后一人**；Judge 标记了其中 28 个
- **代表 case**：`20260925T210621303015Z_multi_currency_0328f5`、`20260925T215714989116Z_multi_currency_434277`、`20260925T221010741568Z_multi_currency_faf8cd`
- **预期**：§7 规定 Split 的 base 尾差"按 participant_order、id 稳定顺序逐个分配最小单位…**尾差不全部压给最后一人**"。手工分摊同样是 Split。
  例（12.34 EUR，fx 7.85，base 总额 96.9）：alice 原币 4.21 → 33.0；bob 原币 8.13 → 63.8；两者合计 96.8，余 +0.1。稳定顺序应给**第一个**参与者 → alice **33.1** / bob 63.8。
- **实际**：整 0.1 全部压给**最后**一人 → alice 33.0 / bob **63.9**。60/60 一致。

**决定性对照证据**：同一个投影在 **CNY AA 路径上完全正确**——`aa_rounding` 89/89、`multi_payer_aa` 61/61、`single_payer_aa` 43/43 全部使用稳定顺序，**零例**压给最后一人。也就是说参考实现在代码里就在，只有"外币 + 手工分摊"这条路走偏，而且是确定性的。

- **为何不是 CRITICAL**：原币分摊与 base 总额都正确，没有任何资金事实被改写或凭空增减，只是某一位参与者的 base 分摊差 0.1。
- **为何不是 HIGH**：不属于 §7 严重度定义里的 Settlement/Refund/Prepayment/Final Settlement 核心逻辑家族；它是 Expense/Split 的投影值。
- **需要 Codex 先确认的一个范围问题**：§7 那句尾差规则写的是"适用于 Split"，但例子是 AA；手工分摊那一句只说"由调用者明确提供原币金额"。若 Codex 认定该规则**只适用 AA**，本条降级为 DOCUMENTATION_AMBIGUITY；若适用所有 Split（"适用于 Split" 的自然读法），则是实现缺陷。**无论哪种读法，文档与实现目前不一致。**
- **与 MASS500-002 的区别**：002 是 **ExpenseDebt** 的 base 分配，已由新的 §8 明确裁定为允许；本条是 **Split** 的 base 分配，由 §7 直接管辖。不是同一件事的重复。
- **复现**：数据层 60/60 确定性；Judge 层 2 次重放 1 次复现、1 次未复现（FAIL → PASS），说明 Judge 本身对这个点不稳定——这也印证了"范围需要澄清"。

### MASS2000-002 — `transfer_allocations.amount` 的小数位数（**DOCUMENTATION_AMBIGUITY**，置信度 0.85）

- **发生次数**：4（`fifo_repayment`、`multi_currency`）
- **代表 case**：`20260925T175822134636Z_fifo_repayment_c280e1`（`amount` 写作 `49.5000`）
- **情况**：数值是正确的 base 金额，只是打印成 4 位小数；Judge 用 §5 的"base currency 金额 1 位小数"去要求它。但 §5 那句精度要求是针对 **Expense 创建/编辑**的，而新的 §18 已经明确 `total_prepayment` 的 `0.0000` 属于"账户余额的数值表示"，不是业务错误。
- **建议**：在 §5 或 §21 写明该字段是否必须归一为 1 位小数，或说明投影字段沿用来源列的数值表示。**不需要改代码。**

### MASS2000-003 — 文档未定义多债权人/债务人配对与 final plan 排序（**DOCUMENTATION_AMBIGUITY**，置信度 0.92）

- **发生次数**：5（`final_settlement` ×3、`manual_split` ×1、`multi_payer_aa` ×1）
- **代表 case**：`20260925T174435431906Z_manual_split_fb162f`、`20260925T233240297578Z_final_settlement_6b596d`
- **情况**：这些是 Judge **UNCERTAIN**，理由明确写着"规则没有规定"：多个债权人/债务人并存时如何配对，以及 `base_unified` final plan 的项目顺序如何生成。§14 固定了**执行**契约（一次执行一个完整建议项、必须匹配当前服务端方案），但没有描述方案本身如何构建与排序。
- **建议**：要么补写配对与排序规则，要么明确说明客户端**不得自行推导**服务端方案。**不需要改代码。**

---

## 5. PASS 抽查（5%）

从 1916 个 PASS 中随机抽 95 个（约 5%），逐例让 DeepSeek 判定：Compiler 是否保持 raw_case 核心意图、Focus 是否真正命中、Judge 是否明显漏判。

从 1916 个 PASS 中随机抽 **95 个（5.0%）**，逐例让 DeepSeek 判定三项。95 例全部返回可用结果。

| 检查项 | 结果 |
| --- | --- |
| Compiler 保持 raw_case 核心意图 | **93/95** |
| Focus 真正命中测试目标 | **81/95** |
| 疑似 Judge 漏判 | **29/95** |

**2 例意图漂移**，都在 `refund_boundary`，都是 Compiler 把退款金额悄悄挪了 0.1 去贴上限（`-3.1 → -3.2`、`-39.9 → -40.0`）。参与者、分摊方式、操作顺序都保留，只有金额被改写。属验证工具链问题（Compiler 有"向契约靠拢"的倾向），不影响业务结论，但值得记录。

**14 例 focus 未真正命中**，与已知的框架覆盖缺口一致：`fifo_repayment` 6（常只制造一笔债务，FIFO 顺序无从区分）、`refund_boundary` 2、`prepayment_refund` 2（预存未被消费也未退回）、`final_settlement` 2、`negative_expense` 1、`completion_archive` 1。

**29 例"疑似漏判"经逐条分类后，没有一条是真实漏判**：

| 类别 | 数量 | 说明 |
| --- | --- | --- |
| base 归一/尾差的既定语义 | 10 | 审计者要求 `base_amount == amount × fx_rate`，忽略 §5 的 1 位小数规定与 §7/§8 的尾差分配。其中 1 例（`c40dd3`）恰好把 **Split**（§7，稳定顺序）与 **ExpenseDebt**（§8，已裁定允许末条承接）对照，反而印证了 MASS2000-001 的边界 |
| 源 ExpenseDebt vs 当前 BilateralDebt | 8 | §8/§21 规定二者语义不同（源事实 vs 当前净额），审计者仍把它们当成必须一致 |
| 已知可观测性歧义 | 8 | `new_prepayment_balance` 为 null、`financial_version` 是行版本还是 Activity 版本、`prepayment_accounts.base_balance` 为 null —— 均为此前两轮已记录的问题 |
| `transfer_allocations` 字段语义 | 3 | 同 MASS2000-002 |

即：**抽样没有发现 Judge 的真实漏判**；PASS 集合的判决质量在抽样范围内是可靠的。

---

## 6. 记录在案、不进 Codex 清单

| 编号 | 分类 | 数量 | 说明 |
| --- | --- | --- | --- |
| MASS2000-N01 | JUDGE_FALSE_POSITIVE | 2 | 预存清偿第三方（见 §3.1 ①），**DeepSeek 原判 BUSINESS_BUG/HIGH，已推翻** |
| MASS2000-N02 | JUDGE_FALSE_POSITIVE | 5 | final settlement 的两个论断（见 §3.1 ②）；§14 明确"一次只执行一个完整建议项"，未执行完剩余方案是**规定行为** |
| MASS2000-N03 | JUDGE_FALSE_POSITIVE | 6 | 逐条已核实的 Judge 计算/方向错误：漏算 bob 也付了 0.8；把退款方向读反（收款人成为债务人）；把保留的源 ExpenseDebt 当成与空 BilateralDebt 矛盾（§8/§21 规定二者语义不同） |
| MASS2000-N04 | ENVIRONMENT | 7 | Judge 响应被判 FORBIDDEN_CONTENT；run 本身执行成功、状态不受影响 |
| MASS2000-N05 | WORKFLOW | 13 | **本轮发现并修复的框架缺陷**：repair 失败于 Loader 时，终态误取**上一次** attempt 的 focus 结果，导致被 Loader 拒绝的场景被送进 Runner。已修（终态只看最后一次 attempt + `stage_execute` 增加 `loader_result != VALID` 不执行），并加回归测试。这 13 条重分类为 COMPILER_INVALID |
| MASS2000-N06 | WORKFLOW | 34 | **阻塞性框架缺陷**：`multiple_repayments` 的 plan 生成器在极小金额（0.1 CNY 债务）下崩溃。已修（金额下限 + 债务人份额再平衡），21 focus × 12000 seed 现零崩溃 |
| MASS2000-N07 | BAD_SCENARIO | 4 | 验证侧的 `final_settlement` plan 仍然偏弱：2 例运行时报"方案里没有该条目"，2 例方案退化。属 plan 设计限制，不是业务缺陷 |

---

## 7. 与上一轮（500-case）的对比

**§10 明确要求回答：旧的 002/003/004 类误判是否明显减少——答案是"全部消失"。**

| 焦点 | 500-run | 2000-run | 结论 |
| --- | --- | --- | --- |
| `single_payer_aa` 异常率 | 13.3% | **0.0%** | MASS500-001 修复生效 |
| `multi_payer_aa` 异常率 | 17.5% | **0.6%** | 同上 |
| `aa_rounding` 异常率 | 16.7% | **1.1%** | 同上 |
| MASS500-002（ExpenseDebt base 尾差）误判 | 13 例 | **0 例** | §8 裁定后 Judge 不再标记 |
| MASS500-003（`transfer_allocations` 语义）误判 | 7 例 | **0 例**（仅剩 4 例小数位歧义） | §5 裁定生效 |
| MASS500-004（`total_prepayment` `0.0000`）误判 | 2 例 | **0 例** | §18 裁定生效 |

AA 系（390 个场景）本轮只产生 2 条异常，且都不是 base 尾差类。**上一轮的修复与裁定完整、干净地解决了它们，没有留下回归。**

---

## 8. 复现确认（§8）

| 候选 | 代表 case | 原结果 | 重放结果 | 结论 |
| --- | --- | --- | --- | --- |
| MASS2000-001 | `..._multi_currency_0328f5` | FAIL | FAIL | **数据层 60/60 确定性**；Judge 层 2 次重放 1 复现 1 未复现 |
| MASS2000-001 | `..._multi_currency_434277` | FAIL | PASS | 同上（Judge 不稳定） |
| （被推翻的 HIGH 候选） | `..._mixed_flow_886de3` | FAIL | PASS | 未复现，进一步支持 JUDGE_FALSE_POSITIVE |

重放一律使用**已保存的同一份 `scenario.json`**，未重新生成场景；结果写入 `<case>/repro/<run_id>`，原始证据未动。MASS2000-002/003 是文档歧义、无代码行为可复现，故未重放。

---

## 9. 方法

1. **开跑前**：记录 git/business_logic commit、43 条 migration、BUSINESS_LOGIC.md hash；`supabase db reset --local` 从零应用；FX fixture 8/8；**MASS500-001 代表 Scenario sanity replay → EXECUTED**（0.3 CNY / 5 人 AA 现在产出 base `0.1/0.1/0.0/0.0`，全部非负、合计守恒）。
2. **执行**：2000 个唯一 seed 的 ScenarioPlan 提前生成，经既有并行流水线执行（Qwen 1 worker、Compiler 2、Runner 2、Judge 4、DeepSeek 全局 4、有界队列 20）。**未提高本地 Qwen 并发。**
3. **异常池**：FAIL / UNCERTAIN / JUDGE_ERROR / RUNNER_FAILED 进入；DUPLICATE / FOCUS_MISMATCH / COMPILER_INVALID / LOADER_INVALID / ENVIRONMENT / WORKFLOW 记录后继续。**全程未中止。**
4. **二次分析**：DeepSeek 按疑似根因聚类 → 对代表 case 的完整证据包（plan / raw_case / scenario / operations / state_final / judge / focus + 出现次数）分类与定严重度（词表含新增的 `DOCUMENTATION_AMBIGUITY`）。
5. **人工核查**：我对每个聚类独立复算并给出自己的判定，推翻了 DeepSeek 的 2 个结论（§3.1）。

---

## 10. 是否值得继续扩大到 5000+

**不建议。**

1. **边际收益已接近 0。** 2000 个新场景只找出 1 个 MEDIUM 业务缺陷，且它是**投影层**问题（原币与总额都对）。11/21 个 focus 异常率为 0%，AA 系（占本轮 450 例）只有 2 条异常且都不是新的。
2. **大部分"异常"不是业务问题。** 54 条异常里，41 条经核查是 Judge 误判（15）、环境（7）、框架缺陷（47 中含重复计数）或 BAD_SCENARIO。**扩大规模只会把这些噪声同比放大**，不会按比例带来新缺陷。
3. **测试框架本身是当前的瓶颈，而不是服务端。** 本轮最有价值的产出其实是两个框架缺陷（N05、N06）——它们会**静默污染统计**。继续扩容前，应该先把 §11 的框架改进做掉。
4. 如果仍要扩容，建议把重点放在**判决质量**而不是数量：给 Judge 补上"多付款人净额""退款方向""源债务 vs 当前债务""预存账户维度"这几类已反复误判的判别说明（这是 Codex/负责人的决定，我不会自行改 Judge Prompt），并把 `final_settlement` 的 plan 与 `fifo_repayment` 的竞争债务场景补强。

---

## 11. 遗留框架改进建议（非业务）

1. **`final_settlement` 的 plan 仍然偏弱**（本轮 4 条 BAD_SCENARIO + 2 条运行时失败）。它对服务端方案做了过强的假设。
2. **`fifo_repayment` 常只制造一笔债务**，FIFO 顺序无从区分；上一轮就已发现，本轮仍在。
3. **Judge 反复误判的四类模式**：多付款人净额计算、退款方向、源债务与当前债务的区别、预存账户的 Owner/Custodian 维度。建议在 Judge 提示中加入针对性判别要点（需负责人批准）。
4. **plan 空间有限**导致 18.4% 的重复；下一轮若继续，可对维度较少的 focus 做去重式 seed 抽取。

---

## 12. 产物

- 批次数据：`local_llm_probe/coverage_reports/`、批次结果 JSON（含 `case_ids` / `coverage` / `pipeline`）
- 异常证据：`local_llm_probe/generated_cases/<case_id>/`（`plan.json`、`raw_case.json`、`scenario.json`、`operations.jsonl`、`state_final.json`、`judge.json`），重放证据在同目录 `repro/`
- 旧 500-case 的全部 run 与 Judge 结果**原样保留**，未修改、未删除
- 离线测试：**166 passed**（新增 `multiple_repayments` 崩溃回归、Loader 拒绝场景不得进 Runner 的回归）

## 13. 禁止事项确认

未修改业务 migration / RPC / `BUSINESS_LOGIC.md` / Android 业务代码 / Judge Prompt；未为提高 PASS 率重跑任何失败 case；未删除任何 run；未部署 Production；未修改 `TEST_TMP.md`；未扩建 Workflow 功能（本轮唯一的代码改动是两个**缺陷修复**与配套回归测试）。
