# 验证覆盖框架：Focus Contract + ScenarioPlan + 去重 + 唯一有效覆盖

**状态：`VERIFICATION COVERAGE FRAMEWORK: READY`**

- 日期：2026-09-25
- 仓库 revision：`32b6d93`（HEAD，未提交的工作区改动）
- 未修改：业务 migration / RPC / `BUSINESS_LOGIC.md` / Android 业务逻辑 / Judge Prompt / `TEST_TMP.md`；未部署远程
- 离线测试：**137 passed**（改动前 69）

---

## 0. 结论摘要

| 项 | 改动前（Stage 1） | 改动后（本次） |
| --- | --- | --- |
| focus 命中率 | 0/30 通过契约（管线根本不调用） | **41/42 命中，0 个 `FOCUS_MISMATCH`** |
| 不同业务场景 | 30 个 case = **3 个**场景 | 42 个 case = **39 个**场景 |
| 重复率 | 29/30 处于重复组（**96.7%**） | 2/41 命中案例重复（**4.9%**） |
| PASS 率分母 | 全部生成尝试 | **唯一有效覆盖**（39） |
| 新增 focus | 0 | **14 个正式覆盖 focus**（+ 保留 3 个 E2E smoke） |
| 疑似业务 Bug | 1 个已知未触发 | **0 个新增**；且已知缺陷经复测**已修复** |

管线本身仍然稳定：41/42 通过 Loader，38/42 执行成功，Judge 36 PASS / 0 FAIL / 0 UNCERTAIN / 0 JUDGE_ERROR。

---

## 1. Focus Contract 接入正式 Pipeline

新增 `src/shared_ledger_verifier/focus_contract.py`，持有 16 个 focus 的注册表。每个条目声明该 focus 代表的**业务形状**（人数区间、付款人数、允许的金额形态、操作数、edge tags）以及一个**契约**——一个只依赖已解析 Scenario 的谓词，不需要数据库、不需要模拟服务端投影。

管线现在有两道闸门，顺序执行：

```
Qwen raw_case → DeepSeek Compiler → Loader（文档合法吗？）→ Focus Contract（真的测到那个业务形状吗？）→ Runner → Judge
```

- 两道闸门**共用同一次** Compiler repair（不引入额外请求，也不自动重跑失败案例）。
- 通过 Loader 但不通过契约的场景标记为 **`FOCUS_MISMATCH`**：仍然执行与判定（它确实在跑真实业务逻辑），但**不计入任何覆盖分母**。
- `check_focus()` 返回 `("FOCUS_VALID", None)` 或 `("FOCUS_MISMATCH", reason)`，`reason` 说明缺失的业务形状，可直接喂给 repair 步骤并写入产物。

契约不是格式检查，而是业务形状检查。例如：

- `multi_payer_aa`：≥3 人、AA 全员、**2–3 个正付款人**、每人付款严格小于总额、**至少一人只欠不付**（否则债务拓扑退化）
- `aa_rounding`：AA 全员，且 `amount × 10⁴ mod 人数 ≠ 0`——精确整数运算证明等分必有尾差
- `targeted_repayment`：先有 Expense、存在真实债务、方向匹配、**0 < 还款额 < 该债务**（严格部分清偿）
- `prepayment_before_debt`：预存在前，且后续 Expense 必须让 **owner 成为债务人、custodian 成为债权人**（否则预存永远不会被核销）
- `prepayment_after_debt`：顺序相反，Expense 必须先制造出 owner→custodian 债务，预存才会去清偿
- `linked_refund`：绑定正 Expense、金额不超上限，且**退款接收人 ≠ 受益人**（否则负 Payment/Split 相抵为零，完全不触及 §13 的债务方向语义）
- `void_transfer`：必须有 `void_transfer`，且其 `transfer_ref` 指向更早的转账产生操作

`local_llm_v2._focus_error()` 仍然保留为 Probe v2.1 的入口，但 `select_business_sections()` 现在以注册表为准，Probe 与正式管线共用同一个业务规则来源。

---

## 2. ScenarioPlan

新增 `src/shared_ledger_verifier/scenario_plan.py`。不再靠提高 temperature 制造随机性——那样既不可复现，也不保证换到新形状。改为**先生成可复现的 ScenarioPlan，再把 Plan 交给 Qwen**：

```python
plan_for(focus, seed) -> ScenarioPlan   # (focus, seed) 的纯函数
```

Plan 固定参与者名单、付款人数、精确金额、金额形态、操作序列，并同时交给 Qwen 生成器和 DeepSeek Compiler 作为**必须逐字编码的事实**（同一份 `render_plan()` 文本进入两个阶段）。生成物落在 `plan.json`，`result.json` 记录 `plan_seed` 与 `plan_fingerprint`。

- **相同 seed + 相同 plan → 完全相同的业务数据**（测试逐字段断言）
- **不同 seed → 走不同的 variation 维度**
- 本地 Qwen 仍然保持 `temperature = 0`

`check_plan()` 在 `plan_for()` 内部运行：任何违反自身 focus spec 的 plan 在**规划期**就抛错，不会浪费一次生成请求去产出注定 `FOCUS_MISMATCH` 的案例。已验证 16 个 focus × 80 seeds = 1360 个 plan 全部自洽。

---

## 3. Variation 维度

| 维度 | 取值 |
| --- | --- |
| `participant_count` | 3 / 4 / 5（`aa_rounding` 数学上锁定 3） |
| `payer_count` | 1 / 2 / 3（**恒小于人数**，保证至少一个纯债务人） |
| `amount_pattern` | `divisible` / `non_divisible` / `decimal` / `large` / `small` |
| 操作复杂度 | 1–5 个操作（`single` / `short_chain` / `multi_step`） |
| `edge_tags` | `rounding_residual` / `partial_repayment` / `multiple_creditors` / `remaining_prepayment` / `full_settlement` |
| `currency` | CNY（本阶段全部 focus 均为 CNY-only） |

金额不是从表里随便抽的：`non_divisible` 会先过滤出对该人数真的除不尽的总额；`divisible` 直接取人数的整数倍；`edge_tags` 在金额定下来之后会**再过滤一次**——一个整除的总额不会宣称 `rounding_residual`（`check_plan()` 也会复核这一点）。

---

## 4. Duplicate 判定方式

新增 `src/shared_ledger_verifier/duplicates.py`，不依赖向量库：

- **scenario 指纹**：把每个 participant ref 与 operation ref 映射成**位置下标**，只保留业务字段（金额、币种、payments/splits 结构、split_method、aa 成员、操作类型序列、操作间引用）。改名 ref、改写 title/description/scenario_id **不改变指纹**；改任何金额、付款人、分摊方式或拓扑**一定改变指纹**。
- **raw_case 指纹**：事件类型序列 + 币种 + 人数 + intent 中抽出的数字多重集（忽略措辞）。
- **判定**：按时间顺序，同一指纹的第一个案例为 canonical，之后的一律标记 **`DUPLICATE_CASE`**（记录 `duplicate_of`）。
- 去重**按业务结构全局进行，不按 focus 分组**：同一形状换个 focus 名字产出仍然只算一次覆盖。

---

## 5. 新增 Focus 列表

保留 3 个 E2E smoke focus，新增 14 个正式业务验证 focus。规则以 `BUSINESS_LOGIC.md` 与现有 Scenario 契约为准；**未加入** multi_currency、final_settlement、large_activity、archive、participant lifecycle（按要求后续单独做）。

| focus | tier | 人数 | 付款人 | 金额形态 | 操作数 | edge tags |
| --- | --- | --- | --- | --- | --- | --- |
| `expense_aa` | smoke | 3 | 2–3 | divisible, decimal | 1 | multiple_creditors |
| `prepayment_refund` | smoke | 3–4 | 1 | divisible, non_divisible, decimal | 3 | remaining_prepayment, partial_repayment |
| `targeted_repayment` | coverage | 3–5 | 1 | divisible, non_divisible, decimal | 2 | partial_repayment |
| `single_payer_aa` | coverage | 3–5 | 1 | 全部 5 种 | 1 | rounding_residual |
| `multi_payer_aa` | coverage | 3–5 | 2–3 | non_divisible, divisible, decimal | 1 | multiple_creditors, rounding_residual |
| `aa_rounding` | coverage | 3 | 1–3 | non_divisible | 1 | rounding_residual, multiple_creditors |
| `manual_split` | coverage | 3–5 | 1–2 | 全部 5 种 | 1 | multiple_creditors |
| `fifo_repayment` | coverage | 3–5 | 1 | divisible, non_divisible, decimal | 2 | partial_repayment, full_settlement |
| `multiple_repayments` | coverage | 3–5 | 1 | divisible, non_divisible, decimal | 3–4 | partial_repayment, full_settlement |
| `prepayment_before_debt` | coverage | 3–5 | 1 | divisible, non_divisible, decimal | 2 | remaining_prepayment |
| `prepayment_after_debt` | coverage | 3–5 | 1 | divisible, non_divisible, decimal | 2 | full_settlement, remaining_prepayment |
| `prepayment_return` | coverage | 3–5 | 1 | divisible, non_divisible, decimal | 2–3 | remaining_prepayment, full_settlement |
| `linked_refund` | coverage | 3–5 | 1–2 | divisible, non_divisible, decimal | 2 | partial_repayment |
| `negative_expense` | coverage | 3–5 | 1 | divisible, non_divisible, decimal | 1 | multiple_creditors |
| `void_transfer` | coverage | 3–5 | 1 | divisible, non_divisible, decimal | 3 | partial_repayment, full_settlement |
| `mixed_flow` | coverage | 3–5 | 1–2 | divisible, non_divisible, decimal | 4–5 | partial_repayment, remaining_prepayment, multiple_creditors |

---

## 6. 批量统计更新

`coverage.py` 与 Dashboard / Batch 报告新增以下计数（PASS 率**只以 `unique_valid_count` 为分母**）：

`generated_count`、`focus_valid_count`、`focus_mismatch_count`、`duplicate_count`、`unique_valid_count`、`distinct_scenarios`、`compiler_repair_count`、`loader_valid_count` / `loader_invalid_count`、`runner_executed_count` / `runner_failed_count`、`judge_verdicts{PASS,FAIL,UNCERTAIN,JUDGE_ERROR}`、`pass_rate`、`coverage_rate`、`focus_breakdown[]`。

`unique_valid` 定义：**Focus Contract 通过 + Loader 合法 + 不是结构重复 + Runner 已被尝试**。最后一条很重要——只跑 `generate-case` 没执行过的案例没有任何验证证据，不能进分母；而 `RUNNER_FAILED` 必须留在分母里，因为那是真实的验证失败。

CLI：`coverage-run --per-focus N --seed-base S [--focus ...]`，结束时打印全部计数并写出 `local_llm_probe/coverage_reports/coverage_<ts>.json`。Dashboard：`GET /api/coverage`、`GET /api/dashboard` 的 `coverage` 块、`GET /api/cases?coverage=UNIQUE_VALID|DUPLICATE|FOCUS_MISMATCH|NOT_VALID`，批次结束的 SSE 事件也回传 `coverage`。

---

## 7. 单元测试结果

```
py -3.12 -m pytest -q
137 passed, 1291 subtests passed
```

改动前为 69 passed。新增测试模块：

- `tests/test_focus_contract.py`（24）：注册表完整性、每个 focus 的正/反例、历史 smoke 契约仍接受自身形状
- `tests/test_scenario_plan.py`（13）：可复现性、跨 seed 多样性、全部 plan 通过 `check_plan`、恒有纯债务人、`aa_rounding` 必有尾差、金额小数位合法、roster 是 Loader 安全的 ref、序列化往返
- `tests/test_duplicates.py`（10）：改名/改写不改变指纹、改业务数据改变指纹、操作引用按结构比较、raw 指纹忽略措辞但跟踪数字与事件序列、全局与按 focus 两种去重
- `tests/test_coverage.py`（10）：唯一有效覆盖是唯一分母、`FOCUS_MISMATCH` / `LOADER_INVALID` / 未执行案例被排除、`RUNNER_FAILED` 留在分母、重复不提升 PASS 数
- `tests/test_generate_case.py` 新增 6 项：`FOCUS_MISMATCH` 与 `LOADER_INVALID` 区分、契约失败可用一次 repair 修复、plan 被记录并传给两个阶段、raw 忽略 plan roster 会被拒绝
- `tests/test_runner.py` 新增 1 项：`return_prepayment` 必须带 custodian 的 behalf
- `tests/test_web.py` 新增 8 项：`/api/coverage`、覆盖筛选、重复标记、多 focus + seed 批次、SSE 重放、未知批次 404

---

## 8. 42-case 验证统计

14 个正式 focus × 3 个 seed（`--seed-base 1`），串行执行，合计 51 分钟。

```
generated=42  focus_valid=41  focus_mismatch=0  duplicate=2
unique_valid=39  distinct_scenarios=39  coverage_rate=92.9%
loader_valid=41  runner_executed=38  runner_failed=3  compiler_repair_count=2
judge: PASS=36, FAIL=0, UNCERTAIN=0, JUDGE_ERROR=0   pass_rate=92.3%
```

| 阶段 | min | p50 | p90 | max | mean |
| --- | --- | --- | --- | --- | --- |
| Generator | 4.64 | 10.16 | 18.73 | 63.00 | 12.96 s |
| Compiler | 0.00 | 9.59 | 18.30 | 29.39 | 10.86 s |
| Runner | 0.33 | 0.54 | 0.68 | 0.85 | 0.55 s |
| Judge | 8.80 | 50.41 | 92.63 | 132.72 | 54.38 s |
| 端到端 | 7.17 | 72.63 | 107.33 | 145.40 | 73.30 s |

模型：`qwen/qwen3.5-9b` + `deepseek-v4.1-flash`（编译与判定同模型）。

## 9. 每个 focus 的命中情况

| focus | 生成 | 命中 focus | 未命中 | 重复 | 唯一有效 | 不同场景 | PASS | RUNNER_FAILED | repair | PASS 率 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| aa_rounding | 3 | 3 | 0 | 1 | 2 | 2 | 2 | 0 | 1 | 100.0% |
| fifo_repayment | 3 | 2 | 0 | 0 | 2 | 2 | 2 | 0 | 0 | 100.0% |
| linked_refund | 3 | 3 | 0 | 0 | 3 | 3 | 3 | 0 | 0 | 100.0% |
| manual_split | 3 | 3 | 0 | 0 | 3 | 3 | 3 | 0 | 0 | 100.0% |
| mixed_flow | 3 | 3 | 0 | 0 | 3 | 3 | 3 | 0 | 0 | 100.0% |
| multi_payer_aa | 3 | 3 | 0 | 0 | 3 | 3 | 3 | 0 | 0 | 100.0% |
| multiple_repayments | 3 | 3 | 0 | 0 | 3 | 3 | 3 | 0 | 0 | 100.0% |
| negative_expense | 3 | 3 | 0 | 1 | 2 | 2 | 2 | 0 | 0 | 100.0% |
| prepayment_after_debt | 3 | 3 | 0 | 0 | 3 | 3 | 3 | 0 | 0 | 100.0% |
| prepayment_before_debt | 3 | 3 | 0 | 0 | 3 | 3 | 3 | 0 | 0 | 100.0% |
| prepayment_return | 3 | 3 | 0 | 0 | 3 | 3 | 0 | 3 | 0 | 0.0%¹ |
| single_payer_aa | 3 | 3 | 0 | 0 | 3 | 3 | 3 | 0 | 0 | 100.0% |
| targeted_repayment | 3 | 3 | 0 | 0 | 3 | 3 | 3 | 0 | 0 | 100.0% |
| void_transfer | 3 | 3 | 0 | 0 | 3 | 3 | 3 | 0 | 1 | 100.0% |

¹ 全部 3 次失败已定位为**测试框架缺陷**（见 §11），修复后同 seed 与新 seed 均 `EXECUTED` + `PASS`。

**达标检查**：每个 focus 都有 ≥2 个 `FOCUS_VALID` ✓（13 个 focus 为 3/3，`fifo_repayment` 为 2/3，其中 1 次是 Compiler 返回非法 JSON）；不存在"30 个 case 只有几个唯一场景" ✓（39/42 各不相同）；重复率显著下降 ✓。

---

## 10. 重复率

| | Stage 1 | 本次 |
| --- | --- | --- |
| 命中案例数 | 0（无契约） | 41 |
| 重复案例数 | 29/30（96.7%） | 2（4.9%） |
| 不同业务场景 | 3 / 30 | 39 / 42 |

仅剩的两组重复是 `aa_rounding` 与 `negative_expense` 在 seed 间的形状碰撞——这两个 focus 的可变维度天生较少（`aa_rounding` 人数被数学锁死在 3、金额形态只有 `non_divisible`）。增加 seed 或补充维度即可分开。

---

## 11. 疑似业务 Bug

**本次未发现新的 `SUSPECTED_BUSINESS_BUG`。** 42 个案例全部 `FAIL=0 / UNCERTAIN=0`；对 4 个代表性新形状（`aa_rounding` 多付款人+尾差、`prepayment_before_debt`、`void_transfer`、`linked_refund`）做了独立复核（每例 2 个视角 + 1 个链路审核 + 对抗性反驳，共 13 个 agent、0 错误）：8/8 视角 PASS，0 条违规声明，全部场景确认**真的命中**了声明的 focus，Compiler 未改变 plan 意图。

### 11.1 已知缺陷复测：`multi_payer_aa` 原币债务覆盖 **已修复**

`findings/multi_payer_aa.md` 记录的缺陷（AA 原币债务被 `normalize_expense_debt_currency` 按已舍入 base 反推覆盖）**在当前 migration 集上不再复现**：

```
py -3.12 -m shared_ledger_verifier run scenarios/regression/multi_payer_aa_original_currency.json
→ runs/20260925T064152Z-cec3fe93
  expense_debt C->A orig=26.6666 base=26.7      # 缺陷记录中为 26.7000
  expense_debt C->B orig=6.6667  base=6.6       # 缺陷记录中为 6.6333
  activity.total_debt = 33.3                     # 与正确债务总量一致
```

规则推导值（100.0 CNY，A 付 60 / B 付 40，三人 AA → 原币分摊 33.3334/33.3333/33.3333）正是 `26.6666` 与 `6.6667`，与观测**逐位一致**。

根因已由 `supabase/migrations/20260924020249_fix_aa_original_currency_debt_preservation.sql` 修复——该 migration 的标题即 "fix AA original currency debt preservation"，替换了 `private.normalize_expense_debt_currency`，且提交时间晚于缺陷文档。本次新框架首次生成出多付款人 + 尾差的 AA 场景，才把这条路径重新跑通。

建议：由 Codex 复测确认后在 `findings/multi_payer_aa.md` 标记为已修复（该文件属业务结论，本报告不代改）。

### 11.2 框架缺陷（已修复）

**F1 — `return_prepayment` 缺少 behalf，导致 42501。** 3/3 次 `prepayment_return` 在 `return_prepayment` 步骤被数据库以 `42501 creator must be party or act on behalf` 拒绝。§4 规定：新建预存"任一 Member 可选择两名 Participant，**不支持 behalf**"，但 **Prepayment Return 走普通资金记录的认领 / Creator behalf 规则**，方向固定 Custodian→Owner。Runner 对两种操作都传 `on_behalf_of_participant_id = None`，对 Return 是错的。

修复：`runner.py` 对 `ReturnPrepayment` 传 custodian（实际出钱方，对应 settlement 传 `from_participant` 的既有做法）。数据库行为符合 §4，属于测试框架缺陷，不修改任何业务代码。

验证：用**同一个失败 plan（seed 1）**与新 seed 4 各重跑一次 —— `Loader=VALID | Focus=FOCUS_VALID | Runner=EXECUTED | Judge=PASS`。3 个失败案例目录保留未动，作为证据。

---

## 12. 覆盖率的已知边界（复核发现，非缺陷）

独立复核同时记录了契约**证明不了**的事情，供后续阶段参考：

1. **契约证明形状，不证明数据库真的那样做了。** Runner 只落 `state_final.json`，没有逐步快照。`void_transfer` 的"作废撤销了当前资金效果"是从终态**推断**的——一个"登记了还款但从未真正结算"的实现会产生同样的终态并且同样 `FOCUS_VALID`。若要真正验证 void 语义，需要记录作废前后的状态快照。
2. **尾差只覆盖最小单位。** 现有 plan 的余数恒为 0.0001 / 0.1 一单位，多单位逐个分配的顺序路径未被触及。
3. **若干部位分支不可达**：预存账户被完全耗尽、退款的累计上限边界、同一对参与者之间的退款方向反转、二次作废被拒、作废 TARGETED 分配、作废预存转账。
4. **`prepayment_before_debt` 与 `prepayment_after_debt` 的终态可能相同**：usage 的投影与预存创建的先后顺序无关，只有 RPC 返回的 `new_prepayment_balance` 与 Runner 合成的时间线能区分两者。
5. 这些是**覆盖面**问题，不是正确性问题；上面 §10 的"不同场景数"应当与这些边界一起阅读。

---

## 13. UI / Dashboard

新增（不改 Web 架构）：

- 覆盖 KPI 条：生成尝试 / 命中声明 Focus / `FOCUS_MISMATCH` / `DUPLICATE_CASE` / 唯一有效覆盖（后者高亮，副标题显示 PASS 率分母）
- 案例列表新增**覆盖状态徽章**（`唯一有效覆盖` / `DUPLICATE_CASE → canonical` / `FOCUS_MISMATCH`（悬停显示原因）/ 覆盖状态未知），并在 focus 名下显示 `seed`
- 新增**覆盖筛选**下拉；场景下拉改为从 `/api/config/info` 的注册表动态加载（16 个 focus + tier 标注）
- 批次结束的 SSE 事件与流水线日志输出覆盖统计

同时修复了 Stage 1 报告的三个 Dashboard 缺陷：

- **D1 首事件丢失** → `WorkflowOrchestrator` 为每个批次保留有界事件历史，`subscribe()` 先回放；实测迟到订阅者能收到 `batch_started` 与第 1 个 `case_started`
- **D2 已完成/未知批次永不结束** → 未知批次返回 **404**，已完成批次靠重放的历史事件立即收到 `batch_completed` 并关闭
- **D3 前端不对账** → 批次号写入 `sessionStorage`，页面刷新后自动重连并重放错过的进度

---

## 14. 产物与复现

```powershell
cd D:\project\Android\shared-ledger\verification

# 全部离线测试
py -3.12 -m pytest -q                      # 137 passed

# 单例（带 ScenarioPlan）
py -3.12 -m shared_ledger_verifier run-generated-case --focus multi_payer_aa --seed 3

# 覆盖批次
py -3.12 -m shared_ledger_verifier coverage-run --per-focus 3 --seed-base 1

# 控制台
py -3.12 -m shared_ledger_verifier web --port 8000
#   GET /api/coverage                      唯一有效覆盖计数
#   GET /api/cases?coverage=DUPLICATE      覆盖筛选

# 已知缺陷回归复测（§11.1）
py -3.12 -m shared_ledger_verifier run scenarios/regression/multi_payer_aa_original_currency.json
```

- 覆盖报告：`verification/local_llm_probe/coverage_reports/coverage_20260925T063853Z.json`
- 每个案例新增 `plan.json`；`result.json` 新增 `plan_seed` / `plan_fingerprint` / `focus_result` / `focus_error` / `scenario_fingerprint` / `raw_case_fingerprint`
- 失败与修复证据保留：3 个 `prepayment_return` 失败目录未删除；修复后重跑为独立新目录（未覆盖任何旧 run）
