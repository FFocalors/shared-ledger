# 批量校验 Stage 1 报告（30 case）

**状态：`BATCH VERIFICATION STAGE 1: BLOCKED`**

阻断原因**不是**业务逻辑缺陷，也**不是**管线故障。E2E 管线 30/30 全阶段成功、无一个错误、无需任何重跑。
阻断原因是**测试有效性**：30 个 case 全部违反本仓库 Probe v2.1 已有的 focus 形状契约，且只覆盖 3 个不同的业务场景。详见 §2。

- 日期：2026-09-25
- 仓库 revision：`32b6d93`（HEAD）；`docs/backend/BUSINESS_LOGIC.md` commit `12fc5401f6e7f25ce9e110b47d9feda2722795cf`
- 执行方式：Web Workflow API（`POST /api/workflow/run` + SSE），3 个批次各 10 case，**串行**（非并发）
- 未修改：业务 migration / RPC / `BUSINESS_LOGIC.md` / Android / Judge Prompt / `TEST_TMP.md`；未部署远程；未删除任何失败案例；未覆盖任何旧 run

---

## 1. 结论摘要

| 项 | 结果 |
| --- | --- |
| 管线稳定性 | **通过**。Generator 30/30、Compiler 30/30、Loader VALID 30/30、Runner EXECUTED 30/30、Judge 全部返回 `PASS` |
| 端到端平均耗时 | 83.0 s（p50 70.6 s，p90 155.4 s，最大 249.6 s） |
| 错误分类分布 | PASS 30 / FAIL 0 / UNCERTAIN 0 / JUDGE_ERROR 0 / RUNNER_FAILED 0 / ENVIRONMENT_ERROR 0 |
| 疑似业务 Bug | **本阶段未发现新的 SUSPECTED_BUSINESS_BUG** |
| 场景重复度 | **30 个 case = 3 个不同业务场景**（三个 focus 各为同一场景重复 10 次） |
| focus 形状合规 | **0/30 通过** `local_llm_v2._focus_error`；E2E 流程根本不调用该契约 |
| 本地 Supabase | 稳定，无重启、无连接耗尽、无超时、无错误日志 |
| Dashboard API | 与磁盘完全一致（0 处不一致） |
| 是否建议进入 100-case 第二阶段 | **不建议**（见 §10） |

---

## 2. 阻断项

### 2.1 E2E 流程未执行 focus 形状契约：30/30 全部 `FOCUS_MISMATCH`

`verification/src/shared_ledger_verifier/local_llm_v2.py:151` 的 `_focus_error()` 定义了每个 focus 必须满足的场景形状：

- 公共：`normal` activity、CNY base、`multi_currency_enabled=false`、**3–4 个 participant**
- `expense_aa`：恰好 3 participant、恰好 1 个 operation、`split_method == "aa"`、`aa_participants` 等于全部 participant、**2–3 个正的付款人**
- `targeted_repayment`：恰好 2 个 operation（expense → targeted）、ref 指向该 expense、金额严格小于债务
- `prepayment_refund`：恰好 3 个 operation（prepayment → expense → linked_refund），ref 与金额上限合规

该函数只在 `local_llm_v2.run_probe_v2()`（Probe v2.1）内被调用。`generate_case()` 只调用 `load_scenario()` 与 `_validate_smoke_currency()`，**从不调用 `_focus_error()`**；`run_generated_case()` 亦然（`grep -rn "_focus_error" src/ tests/` 仅命中 `local_llm_v2.py` 自身）。

把 30 个 Stage 1 场景逐个喂给 `_focus_error()`，结果：

| focus | case 数 | 结果 |
| --- | --- | --- |
| expense_aa | 10 | 10/10 `FOCUS_MISMATCH: expected all-participant AA and 2-3 positive payers` |
| targeted_repayment | 10 | 10/10 `FOCUS_MISMATCH: expected normal CNY activity with 3-4 participants` |
| prepayment_refund | 10 | 10/10 `FOCUS_MISMATCH: expected normal CNY activity with 3-4 participants` |

后果：

1. **case 上的 focus 标签不代表该 case 真的测了那个 focus。** expense_aa 的 10 个 case 全是"单人付款 + 三人 AA"，focus 的核心（多付款人、按付款人原币净额、债务环）完全没有被覆盖；这也正是已知缺陷 `findings/multi_payer_aa.md` 所在路径，本阶段一个 case 都没碰到。
2. targeted_repayment / prepayment_refund 只有 2 个 participant（契约要求 3–4）；`target_expense_refs` 因只有一笔 expense 而必然唯一，无法区分 TARGETED 与 FIFO 语义。
3. 探针会判定 `FOCUS_MISMATCH` 的场景，在 E2E 里被报告成 `VALID` / `EXECUTED` / `PASS`，**gate 在 E2E 路径上丢失**，指标因此虚高。

复现命令见 §11。

### 2.2 生成器确定性：30 个 case 只覆盖 3 个不同业务场景

`LocalLLMClient.complete()` 在 `local_llm.py:196` 硬编码 `"temperature": 0`，focus prompt 又是固定文本，因此**同一 focus 的生成结果是纯函数**：

- `expense_aa`：10/10 语义指纹完全相同 —— `150.0 CNY`、participants `[A,B,C]`、付款人仅 `A`、AA 全员
- `targeted_repayment`：10/10 完全相同 —— `100.0 CNY`（Alice 付）→ `40.0 CNY` TARGETED（Bob→Alice）
- `prepayment_refund`：10 个 case 落在 4 个 JSON 指纹（仅 participant 拼写与 `split_method` 编码不同），但**业务事实完全一致** —— 预存 `100.0 CNY` Alice→Bob、消费 `50.0 CNY` Alice 付 / Alice 25 + Bob 25、linked refund `-25.0 CNY` Alice 收

跨会话证据：`20260925T035524810081Z_prepayment_refund_23bbb8` 的 `raw_case.json` 与昨天 18:19 生成的 `20260924T181915400432Z_prepayment_refund_8862e4` **逐字节相同**。

因此 Stage 1 实际测的是 **3 个不同业务场景 × 10 次重复**，而不是 30 个场景。Generator 成功率 100% 是构造性的，不代表生成质量。

---

## 3. 完整统计（30 个 case）

### 3.1 各阶段成功率与耗时

| 阶段 | 指标 | 数值 |
| --- | --- | --- |
| Generator (qwen/qwen3.5-9b) | 产出 `raw_case.json` / 成功率 | 30/30 / 100% |
| Generator | 平均 / p50 / p90 / max | 15.69 / 7.20 / 18.66 / 176.25 s |
| Compiler (deepseek-v4.1-flash) | 产出 `compiler_result.json` / 成功率 | 30/30 / 100% |
| Compiler | repair 次数分布 | `{0 次: 28, 1 次: 2}` |
| Compiler | repair 后成功率 | 2/2 |
| Compiler | 平均 / p50 / p90 / max | 19.11 / 18.05 / 32.17 / 34.97 s |
| Loader | VALID / INVALID | 30 / 0 |
| Runner | EXECUTED / FAILED | 30 / 0 |
| Runner | 平均 / max | 0.534 / 0.86 s |
| Judge (deepseek-v4.1-flash) | PASS | 30 |
| Judge | FAIL / UNCERTAIN / JUDGE_ERROR | 0 / 0 / 0 |
| Judge | 平均 / p50 / p90 / max | 47.68 / 43.20 / 92.47 / 150.16 s |
| 产物完整性 | `operations.jsonl` / `state_final.json` | 30/30 |
| 端到端 | 平均 / p50 / p90 / max / 合计 | 83.0 / 70.6 / 155.4 / 249.6 s / 2490 s |

两次 repair 的 Loader 错误均为 `scenario.participants[0]: must be a short ref using letters, numbers, underscores, or hyphens`（Compiler 写出了 `Alice (Owner)` 这类带空格与括号的名字），一次 repair 后即通过。

### 3.2 按 focus 分组

| focus | n | 不同业务场景 | PASS | FAIL | UNCERTAIN | JUDGE_ERROR | 其他 | gen 均值 | comp 均值 | run 均值 | judge 均值 | e2e 均值 | repair |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| expense_aa | 10 | 1 | 10 | 0 | 0 | 0 | 0 | 5.16 s | 15.65 s | 0.454 s | 14.63 s | 35.89 s | 0 |
| targeted_repayment | 10 | 1 | 10 | 0 | 0 | 0 | 0 | 7.74 s | 13.12 s | 0.521 s | 45.52 s | 66.91 s | 0 |
| prepayment_refund | 10 | 1（按 JSON 形状 4） | 10 | 0 | 0 | 0 | 0 | 34.17 s | 28.55 s | 0.627 s | 82.89 s | 146.24 s | 2 |

prepayment_refund 明显更慢：场景有 3 个 operation、状态更大，Judge 输入更长（judge 均值 82.9 s，最大 150.2 s；该 focus 的 generator 有一次 176 s 的尖峰）。

### 3.3 最慢 10 个案例（端到端）

| case | focus | e2e | gen | comp | run | judge |
| --- | --- | --- | --- | --- | --- | --- |
| 20260925T041145896510Z_prepayment_refund_071a70 | prepayment_refund | 249.6 | 176.25 | 28.59 | 0.697 | 44.10 |
| 20260925T040156662219Z_prepayment_refund_660ef8 | prepayment_refund | 186.7 | 16.11 | 19.83 | 0.582 | 150.17 |
| 20260925T035524810081Z_prepayment_refund_23bbb8 | prepayment_refund | 180.0 | 18.66 | 32.33 | 0.569 | 128.49 |
| 20260925T040503547484Z_prepayment_refund_7ab23e | prepayment_refund | 155.4 | 16.06 | 33.11 | 0.643 | 105.55 |
| 20260925T040739218946Z_prepayment_refund_cd8806 | prepayment_refund | 142.4 | 14.41 | 34.97 | 0.596 | 92.47 |
| 20260925T041736069635Z_prepayment_refund_952c23 | prepayment_refund | 133.4 | 40.16 | 31.83 | 0.738 | 60.67 |
| 20260925T035825088586Z_prepayment_refund_eac6fe | prepayment_refund | 124.9 | 8.34 | 25.24 | 0.474 | 90.87 |
| 20260925T041001864815Z_prepayment_refund_d7753c | prepayment_refund | 103.8 | 22.83 | 23.78 | 0.857 | 56.32 |
| 20260925T041555852229Z_prepayment_refund_2969c5 | prepayment_refund | 100.0 | 17.72 | 23.69 | 0.653 | 57.93 |
| 20260925T035121713492Z_targeted_repayment_978708 | targeted_repayment | 97.1 | 5.84 | 12.00 | 0.421 | 78.87 |

瓶颈全部在 Judge（DeepSeek 端到端延迟），Runner 恒定 < 1 s。

### 3.4 重复 / 高度相似场景

| 指纹 | 重复数 | focus |
| --- | --- | --- |
| `150.0 CNY, [A,B,C], payments=[A], aa` | 10 | expense_aa |
| `100.0 CNY Alice 付 → 40.0 TARGETED Bob→Alice` | 10 | targeted_repayment |
| `prepay 100 Alice→Bob / expense 50 / refund -25` | 10（4+3+2+1 个子形状） | prepayment_refund |

**30 个 case 中，29 个处于重复组内；不同业务场景数 = 3。**

---

## 4. 失败与问题队列

Stage 1 的 30 个 case 中**没有任何** FAIL / UNCERTAIN / RUNNER_FAILED / COMPILER_INVALID / GENERATOR_ERROR，因此按规则没有 Stage 1 案例进入问题队列。

`GET /api/issues` 当前返回 12 条，全部来自 Stage 1 之前的旧数据（`multi_payer_aa`、`basic_single_payment`、`linked_refund_after_settlement`、`prepayment_before_debt` 等历史 run），与本次批量无关；队列归类经逐条比对与磁盘一致（`missing=0, extra=0`）。

未对任何失败案例自动重跑；未调整 Judge Prompt；未删除任何案例。

---

## 5. 疑似业务 Bug

**Stage 1 未发现新的 `SUSPECTED_BUSINESS_BUG`。**

需要明确说明两点：

1. 已知缺陷 `findings/multi_payer_aa.md`（AA 原币债务被 `normalize_expense_debt_currency` 覆盖）**在本阶段完全未被触发**，因为 30 个 case 里没有任何一个是多付款人 AA。这是 §2 覆盖面问题的直接后果。
   **后续结论（2026-09-25，见 [COVERAGE_FRAMEWORK.md](COVERAGE_FRAMEWORK.md) §11.1）：** 新覆盖框架首次生成出多付款人 + 尾差的 AA 场景后复测，该缺陷在当前 migration 集（42/42，含 `20260924020249_fix_aa_original_currency_debt_preservation.sql`）上**已不再复现**——`26.6666 / 6.6667` 与规则推导值逐位一致。
2. 本阶段所有 case 的 `PASS` 均经独立复核（§6），未发现 Judge 漏判。

---

## 6. 人工抽检（独立复核）

按规则对 PASS 抽取约 10%。由于不同业务场景只有 3 个，实际做法是：**对全部 3 个不同业务场景做独立复核**（场景级覆盖 3/3，远超 10%）。每个场景由两个视角不同的独立 reviewer 审核——算术视角（§5/§6/§7/§8/§13/§15）与生命周期/投影视角（§9–§18/§21/§24）——外加一个 raw→scenario→state 链路审核；任何声称的违规都必须经过对抗性反驳（默认"反驳成立即否决"）。

复核结论：**无一条违规声明通过对抗性反驳；三个场景的 `PASS` 均未被推翻，未发现 Judge 漏判。**

### 6.1 场景级结论

| focus | 重复数 | 算术视角 | 生命周期视角 | 违规是否存活 |
| --- | --- | --- | --- | --- |
| expense_aa | 10 | PASS (conf 0.96) | PASS (conf 0.97) | 否（无违规声明） |
| targeted_repayment | 10 | PASS (conf 0.95) | PASS (conf 0.93) | 否（无违规声明） |
| prepayment_refund | 10 | PASS (conf 0.93) | PASS (conf 0.85 / 0.90) | 否（无违规声明） |

prepayment_refund 的形状有两个变体（`manual` 与 `aa` 分摊编码），两个都做了独立复核：`23bbb8`（4 次重复）走生命周期视角，`cd26fd`（3 次重复）走算术 + 生命周期双视角，结论一致。
另有一次 reviewer 因推理网关瞬时 `502` 失败（见 §6.3），已用同形状的 `cd26fd` 变体补齐算术视角，并由本人手工复算 `23bbb8` 核对。

独立复核逐项确认的关键数值：

- **expense_aa**：`150.0000 CNY`、fx `1.0000000000`、base `150.0`；splits `50.0000 × 3`（合计 `150.0000`）；ExpenseDebt 2 行（`B→A 50.0000`、`C→A 50.0000`）；BilateralDebt 2 行同值；`total_debt 100.0`、`has_unsettled_debt true`、`completed false`；`total_prepayment 0.0000`；`financial_version 1`；transfers / prepayment / final 集合全空。
- **targeted_repayment**：expense `100.0000 CNY` / base `100.0`；payment Alice `100.0000`；split Bob `100.0000`；ExpenseDebt `Bob→Alice 100.0000`（**按 §10/§16 不因 Transfer 而改写**）；BilateralDebt `Bob→Alice 60.0000`；settlement Transfer `40.0000` + 1 个 component；TransferAllocation `40.0000`；`financial_locked true`（§16：被真实 Transfer 来源触达）；`financial_version 1 → 2`。
- **prepayment_refund**：预存 `100.0 CNY`（owner Alice / custodian Bob）→ PrepaymentAccount 余额 `100.0000`；expense `50.0`（Alice 付 / Alice 25 + Bob 25）→ ExpenseDebt `Bob→Alice 25.0000`；linked refund `-25.0`（payments/splits 均为 Alice `-25.0`）→ 无新债务；**§12 判定不需要 PrepaymentUsage**（账户方向为 owner Alice → custodian Bob，而唯一未结债务是 Bob→Alice 的反方向，§12 明确"相反方向的未结债务不能提前消费另一方向的预存"）；余额保持 `100.0000`、`total_prepayment 100.0000`、`total_debt 25.0`、`completed false`；§13 的 linked refund 上限与永久财务锁均满足。

### 6.2 链路（raw → scenario → state）质量

- **Compiler 未改变原测试意图**：三个场景的 participants、币种、金额、事件顺序与语义引用均被保留；唯一"发明"的是 raw case 未写明的付款人（expense_aa 补成单人 `A`，为使 `payments` 守恒）。所有 case 均为 `repair_count = 0`（除 §3.1 的两例命名修复）。
- **expense_aa 的 `raw_case` 被评为不合理**：raw 文本命名了 **0 个付款人**（focus 指导要求 "two or three payers"），`150.0 / 3 = 50.0` 整除，因此 §7 唯一的非平凡规则（base 尾差按顺序逐个分配，如 `100.0 → 33.4/33.3/33.3`）与 §8 的"不进行无现金多人环路冲销"都无法被触及。
- **targeted_repayment 的 `raw_case` 合理**：金额严格部分（`40 < 100`）、债务人/债权人/方向与语义目标明确；但仅 2 个 participant、仅一笔 expense，`target_expense_refs` 必然唯一，无法区分 TARGETED 与 FIFO。
- **prepayment_refund 的 `raw_case` 也不合理**：预存是"惰性"的（创建时 Alice 并不欠 Bob，没有任何债务被清偿，也没有余额被消耗）；退款是"退化"的（raw 把 Alice 同时写成 receiver 与 beneficiary，故 Payment `-25` 与 Split `-25` 相抵为零，不产生新债务，`Bob→Alice 25.0` 保持不变）。**而 raw 文本却断言 "this refund reduces the original debt obligation"——这是规则不会产生的效果，执行后的状态直接证伪了它。** 该 focus 真正需要覆盖的形状（receiver ≠ beneficiary、结算后退款、退款释放 PrepaymentUsage、预存真正清偿既有 Owner→Custodian 债务）一个都没有出现。
- **该 focus 的 raw 是"罐头输出"**：整个 `generated_cases/` 目录内 14 个 prepayment_refund raw 只有 **2 个不同内容**（本 case 的 `raw_case.json` 与另外 11 个逐字节相同），跨 20260924T175438Z → 20260925T041736Z 多个会话。
- **`operations.jsonl` 的 `input` 字段是场景级回显**（participant ref 用名字、无 title），并非 Runner 实际发送的 wire payload；如需用它做审计需注意这一语义。

### 6.3 复核方法与偏差

- 复核由 Workflow 编排的多智能体对抗性流程执行：每个场景 2 个视角 reviewer + 1 个链路审核，任何声称的违规都要经过"默认反驳成立即否决"的对抗性反驳；三个场景共 0 条违规声明，故无一条进入反驳阶段。
- 偏差记录：prepayment_refund 的第二轮中，`chain:cd26fd` 与 `review:23bbb8:amounts` 两个 agent 因推理网关瞬时 `502`（上游转发失败）未返回。二者均**不影响结论**：算术视角已由 `cd26fd` 变体覆盖（PASS 0.93，两个变体业务事实相同），链路审核已由 `23bbb8` 覆盖，`23bbb8` 的算术另由本人手工复算核对（见上）。缺口填补重跑的结果记于 §6.4。

### 6.4 缺口填补复跑结果

两个缺失的 reviewer 已重跑成功，结论与前述一致：

- `23bbb8` 算术视角：**PASS（conf 0.85，0 条违规）**。20 项逐字段期望全部命中，包括：`prepay_1` Transfer `100.0000` 与 TransferComponent 合计相等；`transfer_allocations` 为 0（预存是第 1 个操作，当时 Alice 欠 Bob 为 0，无可清偿债务）；PrepaymentAccount 余额 `100.0000`；**PrepaymentUsage 为 0 且按 §12 本就应当是 0**（唯一债务 `Bob→Alice` 是账户 owner→custodian 轴的**反方向**）；`expense_1` Payment `50.0000` = Splits `25.0000 + 25.0000`；ExpenseDebt `Bob→Alice 25.0000 / base 25.0`；`refund_1` 的 Payment/Split 均为 `-25.0000` 且相抵为零 → **不产生新债务行**；`|−25| ≤ 50` 上限满足；`expense_1.financial_locked = true`（§13 永久锁）、`refund_1.financial_locked = false`。
- `cd26fd` 链路审核：`raw_case_reasonable = false`（理由与 `23bbb8` 相同：2 个 participant 违反 focus 指导的 3–4；预存惰性；退款退化且 receiver == beneficiary；raw 断言的"reduces the original debt obligation"被规则与状态双双证伪），`compiler_preserved_intent = true`，`scenario_matches_raw = true`。

两位 reviewer 另外记录了两条 **OUT-OF-LENS 观察**（非规则违反，但值得记录）：

1. `operations.jsonl` 中 expense 与 linked refund 步骤返回的 `result.financial_version` 均为 `1`，而 `state_final.json` 的 `activity.financial_version` 为 `3`；同一批次 10 个 case 表现一致。§19/§20/§22 只定义 `expected_financial_version` 为并发控制的**入参**，从未定义 RPC **返回**的 `financial_version` 语义，因此不构成对任何条款的违反——看起来返回的是"本次写入行的版本"而非 Activity 版本。属于**可观测性/命名歧义**，建议后续在文档或返回值命名上澄清。
2. `prepayment_accounts[].base_balance` 为 `null`（即使 CNY 就是 base 币种），且 `total_prepayment` 打印 4 位小数（`100.0000`）而 `total_debt` 打印 1 位（`25.0`）。§18 对 by-currency 输出只定义 `{currency, balance}`，未定义 `base_balance` 字段。已核对 Stage 1 之前的 smoke run（`runs/20260923T085626Z-ab8a98ea`）同样为 `null`，属既有行为而非本阶段引入。

---

## 7. Workflow / Dashboard 稳定性

### 7.1 稳定性结论

- 3 个批次共 30 个 SSE 流全部正常收敛到 `batch_completed`，无 `case_failed` 事件，无断流。
- 每个 case 的 5 个阶段各产生 2 条 `stage_progress`（running + 终态），计数精确为 `10 × 2 = 20`，无丢失、无乱序。
- SSE keepalive 正常工作：expense_aa 批次 0 次（事件密集），targeted_repayment 9 次，prepayment_refund 21 次（Judge 单次最长 150 s，必然出现 >30 s 空档）。
- 批量结束后 `GET /api/dashboard`、`/api/cases`、`/api/issues` 与磁盘**完全一致**（0 处不一致）；42 个 generated case 的详情接口全部返回 7 个产物，`has_artifacts` 标志与详情负载逐项吻合。

### 7.2 已确认的 Dashboard 缺陷（UI / 编排，非业务）

**D1 — SSE 缺少重放缓冲，订阅前的首批事件必然丢失。**
前端先 `POST /api/workflow/run` 再 `new EventSource(...)`（`static/app.js` 的 `run` 处理与 `startPipelineEventStream`），而 `batch_started` 与第 1 个 `case_started` 在这两步之间就已经广播。
证据：3 个批次的 SSE 抓包中 `case_started` 序列**全部**从 `2` 开始（`[2,3,…,10]`），`batch_started` 一次都没收到；`case_completed` 则是完整的 `1..10`。
影响：`#pipeline-batch-info` 整批为空（用户看不到"场景 / 批次数量"），第 1 个 case 不会触发 `resetPipelineDisplay()`。

**D2 — SSE 对未知或已完成批次永不结束。**
`GET /api/workflow/events/batch_does_not_exist` 返回 **HTTP 200** 并无限发送 keepalive；对已完成批次同样如此（历史事件不重放，`batch_completed` 永不再发，`event_generator` 的 `break` 条件无法达成）。
证据：`curl -m 34` 两者都只收到 `: keepalive`，连接不关闭。
影响：页面刷新一次就多泄漏一个服务端协程；重复订阅会持续累积。

**D3 — 前端无状态对账与断线恢复。**
`static/app.js` 从不调用 `GET /api/workflow/status/{batch_id}`（该接口数据完整），`EventSource.onerror` 只关闭连接并复位按钮。断线或刷新后批次仍在服务端继续，但 UI 进度全部丢失。

上述三项均未修改：工作区 `web/` 在本次运行期间正被另一处并行编辑（`app.py`/`service.py`/`app.js`/`index.html`/`style.css`/`test_web.py`，mtime 11:51–11:53，新增 `/api/workflow/live` 轮询横幅以捕捉外部 CLI/Claude Code 运行），此时改动同一批文件会与其冲突。建议的最小修法：`WorkflowOrchestrator` 为每个 batch 保留有界事件历史，`subscribe()` 时先回放；对未知 batch 返回 404；前端在 `onerror` 与页面挂载时用 `/api/workflow/status` 对账。

### 7.3 其它运行观察

- **`.env` 在进程启动后被缓存**：`load_local_env()` 不覆盖已存在的 `os.environ`，因此运行中的 Dashboard 不会感知之后对 `.env` 的修改。本次 `SUPABASE_ANON_KEY` 在 11:30 补入 `.env` 后，11:29 启动的 8000 端口实例一直报 `has_supabase_anon_key: false`；该实例随后被重启后恢复正常。**改 `.env` 后需重启 Dashboard。**
- 本次验证使用独立实例 `127.0.0.1:8010`（由 HEAD revision 启动），未干扰仓库既有的 8000 端口实例。
- 批次为**串行**执行。`WorkflowOrchestrator` 每批次一个线程，并发多批次未测试。

---

## 8. 本地 Supabase 稳定性

| 指标 | 结果 |
| --- | --- |
| 容器 | `supabase_db_shared-ledger` Up 11 小时（healthy），运行期间**无重启** |
| 连接数 | 全程 12–13（无连接耗尽） |
| 数据库大小 | 16 MB |
| 数据增长 | activities 18 → 36，users 21 → 34，expenses 17 → 45，transfers 4 → 22，prepayment_accounts 0 → 11 |
| postgres 日志 | 0 条 fatal / panic / deadlock / connection refused |
| PostgREST / Auth / Storage 日志 | 各 0 条 error / timeout |
| Runner 延迟 | 恒稳 0.33–0.86 s（30 个 case 无退化趋势） |
| migration 状态 | 42/42 已同步 |

**未出现异常连接、超时或性能下降。** 唯一的日志异常是一条 03:29:57 UTC 的 `terminating walsender process due to replication timeout`，发生在批次开始之前，与本次运行无关。

---

## 9. 产物与证据

- 30 个 case 目录：`verification/local_llm_probe/generated_cases/` 下 `20260925T0337*_expense_aa_*`（10）、`20260925T0343*_targeted_repayment_*`（10）、`20260925T0355*_prepayment_refund_*`（10）
- 每个 case 均完整保留 `raw_case.json`、`compiler_result.json`、`scenario.json`、`result.json`、`operations.jsonl`、`state_final.json`、`judge.json`；`runs/` 下各有**恰好 1 个** run 目录（30/30，无覆盖）
- 旧 run 未被覆盖：11 个 Stage 1 之前的 case 目录 mtime 全部保持原值
- 模型与规则版本：`qwen/qwen3.5-9b` + `deepseek-v4.1-flash`（编译与判定同一模型），`business_logic_commit` 30/30 一致为 `12fc5401…`
- 离线用例：`py -3.12 -m pytest -q` → 68 passed（HEAD revision）；工作区 `web/` 被并行修改后为 69 passed

---

## 10. 是否建议进入 100-case 第二阶段

**不建议按现状进入第二阶段。**

理由：Stage 1 已经证明，在当前生成器与 E2E gate 下，把规模从 30 扩到 100 或 500，只会把 **3 个业务场景**重复 100 / 500 次。它能把"管线重复稳定性"这条曲线画得更细（目前 30/30 已无一次抖动），但不会增加任何业务覆盖率，也不会提高发现真实业务缺陷的概率——已知的 `multi_payer_aa` 缺陷就是因为缺多付款人场景而完全没被碰到。

建议的最小前置修复（均属验证工具，不涉及业务逻辑；是否执行由负责人 / Codex 决定）：

1. **把 focus 形状 gate 接进 E2E**：在 `generate_case()` 的 Loader 校验之后调用 `local_llm_v2._focus_error(scenario, focus)`，不通过则走现有的一次 repair 机制，仍不通过则记为 `COMPILER_INVALID / FOCUS_MISMATCH`。这会让现在 30/30 的 `VALID` 回到真实水平。
2. **给生成器引入多样性**：不要只依赖 `temperature=0` 的固定 prompt。可在 focus 指导里注入随 case 变化的维度（金额是否整除、人数、付款人组合、是否需要尾差、是否构成债务环、是否含退款/预存交叉），或按 stage 允许采样温度。目标是每个 focus 至少覆盖 2–3 个不同形状。
3. **（可选）修复 §7.2 的 D1/D2/D3**，使批量观测不再依赖抓包。

修好第 1、2 项之后，100-case 阶段才有统计意义；届时建议把"每个 focus 的不同业务场景数"与"focus 契约通过率"一并作为阶段门槛指标。

---

## 11. 复现步骤

```powershell
# 环境（本地隔离 Supabase + LM Studio，均在 127.0.0.1）
cd D:\project\Android\shared-ledger
supabase migration list --local                       # 42/42

# 启动控制台（用 HEAD revision；8010 避免与既有实例冲突）
cd verification
py -3.12 -m shared_ledger_verifier web --port 8010 --no-browser

# 单批次（Web Workflow API），随后订阅 SSE
curl -s -X POST http://127.0.0.1:8010/api/workflow/run -H "Content-Type: application/json" -d "{\"focus\":\"expense_aa\",\"count\":10}"
curl -sN http://127.0.0.1:8010/api/workflow/events/<batch_id>

# Dashboard 缺陷 D2：未知批次与已完成批次都应立即结束，实际永不结束
curl -sN -m 34 http://127.0.0.1:8010/api/workflow/events/batch_does_not_exist
```

focus 形状契约违规（§2.1）可用以下脚本复核（脚本放在 `verification/` 下执行）：

```python
import sys, json
from pathlib import Path
sys.path.insert(0, "src")
from shared_ledger_verifier import load_scenario
from shared_ledger_verifier.local_llm_v2 import _focus_error

for d in sorted(Path("local_llm_probe/generated_cases").glob("20260925T*")):
    r = json.loads((d / "result.json").read_text(encoding="utf-8"))
    print(d.name, r.get("focus"), _focus_error(load_scenario(d / "scenario.json"), r.get("focus")))
```
