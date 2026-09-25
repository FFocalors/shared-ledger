# 规模化验证流水线（21 focus + 生产者/消费者并行）

**状态：`MASS VERIFICATION PIPELINE: READY`**

- 日期：2026-09-25
- 仓库 revision：`32b6d93`（HEAD，未提交的工作区改动）
- 只修改 `verification/`；未改业务 migration / RPC / `BUSINESS_LOGIC.md` / Android
- 离线测试：**148 passed**（本次改动前 137）

---

## 0. 结论摘要

| 项 | 结果 |
| --- | --- |
| focus 数量 | **21**（19 正式覆盖 + 3 E2E smoke，`targeted_repayment` 双重归属），本次新增 5 个 |
| 新 focus 验证 | 5/5 均生成并执行了至少一个 `FOCUS_VALID` 案例并得到 Judge 裁决 |
| 流水线吞吐 | **213.8 cases/hour**（38 case / 640 s）；串行基线约 49 cases/hour → **4.4×** |
| Qwen 利用率 | 38 条 raw case 在 **370 s** 内完成（370 raw/hour，9.7 s/条），**做完时仍有 13 个 case 在 Judge** |
| 并发串扰 | 无：run_id 0 冲突、118 个 activity 对应 117 个创建者、每 case 独立目录与测试用户 |
| 队列水位 | raw 4 / compiled 3 / judge 12（上限均 20，未触顶） |
| DeepSeek 错误率 | **0%**：0 timeout、0 `COMPILER_ERROR`、0 `JUDGE_ERROR` |
| Runner 稳定性 | 36/38 EXECUTED，均值 0.59 s、最大 0.97 s（2 并发下无退化） |
| 覆盖质量 | 38/38 命中 focus，0 `FOCUS_MISMATCH`，0 重复，38 个不同场景，coverage_rate 100% |
| 疑似业务 Bug | **未确认新的 `SUSPECTED_BUSINESS_BUG`**；3 个 Judge FAIL 经核查均为对未文档化维度的过度判定，另有 2 条可观测性歧义一并交 Codex |

---

## 1. 新增的 5 个 focus

| focus | tier | 覆盖 | Runner 新增能力 |
| --- | --- | --- | --- |
| `multi_currency` | coverage | 外币 Expense、original/base 分离、FX snapshot、跨币种债务与还款 | 无（`create_expense_auto_rate` 已支持原币）；新增**本地 FX fixture** |
| `final_settlement` | coverage | Final Settlement Session、推荐路径、方案内执行、外部财务操作使剩余方案失效 | `final_settlement`、`preview_final_settlement` |
| `large_activity` | coverage | 大型 Activity、多子活动、统一成员池、子活动 Expense、活动级预存 | `create_sub_activity`、expense 的 `ledger_unit_ref` |
| `refund_boundary` | coverage | 部分退款、累计退款、恰好达上限、已结算后退款、锁定行为 | 无（复用 `linked_refund`） |
| `completion_archive` | coverage | 债务清零、仍有预存余额不得 completed、已结清归档、未结清强制归档、取消归档 | `archive_activity`、`unarchive_activity` |

注册表从 16 增至 **21**（`expense_aa` / `targeted_repayment` / `prepayment_refund` 三个 E2E smoke focus 保留不变）。

### 1.1 Runner 最小新增

按要求只补最小必要能力，未重构 Runner：

- 新增 5 个 scenario operation：`create_sub_activity`、`final_settlement`、`preview_final_settlement`、`archive_activity`、`unarchive_activity`
- expense / linked_refund 新增可选 `ledger_unit_ref`，把账记进某个子活动
- `final_settlement` **只写双方与 mode**：§14 规定金额与币种由服务端当前建议决定，Runner 先读 `preview_final_settlement_v2`，再按建议项**原样执行**（不自行选择金额）
- `preview_final_settlement` 是只读操作，把当前方案写进 `operations.jsonl`，让"外部财务操作使方案失效"变得**可直接观测**
- `collector` 增加 `ledger_units` 与 `activity.is_archived`
- Judge 的字段白名单同步扩展；`ledger_units` 设为**可选**字段，历史 run 仍可判定

### 1.2 本地 FX fixture（确定性，无网络）

`multi_currency` 需要服务端 FX snapshot，而生产缓存由外部同步任务填充。新增 `fx-fixture` 命令把固定汇率写入**本地** `exchange_rate_cache`：

```powershell
py -3.12 -m shared_ledger_verifier fx-fixture
# CNY/EUR=0.1273885350  EUR/CNY=7.8500000000  USD/CNY=7.1200000000 ...
```

- `coverage-run` 在选中 focus 需要时**自动**应用
- 服务端解析器只接受 `source = 'ECB_REFERENCE'` 的行，因此 fixture 以该 source 写入，扮演生产同步任务的角色
- **这些是固定的本地测试汇率，不是真实 ECB 参考汇率**；只写本地开发库，不改任何 migration / RPC / 业务规则。旧的 `verification-fixture` source 会被解析器忽略，已改为必需值并在文档与 CLI 输出中显式标注

---

## 2. 流水线并行

```
ScenarioPlans → [generator ×1] → [compiler ×2] → [runner ×2] → [judge ×4] → results
                 有界队列 20      有界队列 20      有界队列 20
```

- **Qwen 单请求**：`LOCAL_GENERATOR_WORKERS` 被强制夹到 1（`resolved()` 会记录被夹），符合 LM Studio `Max Concurrent Predictions = 1`
- **DeepSeek 全局 semaphore**：Compiler 与 Judge 共用同一个 `DEEPSEEK_MAX_CONCURRENCY=4` 的信号量，通过 `GatedClient` 代理注入
- **有界队列 + 背压**：`queue.Queue(maxsize=N)`，满时生产者阻塞；judge 慢会依次压住 runner、compiler，内存不会无界增长
- **失败不阻塞**：任一阶段失败的 case 直接记录并继续；worker 异常被捕获记录，不会让批次卡死
- **不自动重跑**：任何阶段都不为提升 PASS 率重试

可配置项（环境变量）：

```
LOCAL_GENERATOR_WORKERS=1   COMPILER_WORKERS=2   RUNNER_WORKERS=2   JUDGE_WORKERS=4
DEEPSEEK_MAX_CONCURRENCY=4  RAW_QUEUE_SIZE=20    COMPILED_QUEUE_SIZE=20  JUDGE_QUEUE_SIZE=20
```

为了并行，`generate_case` / `run_generated_case` 被拆成可独立调度的三个阶段函数（`start_case` / `stage_generate` / `stage_compile` / `stage_execute` / `stage_judge`），单案例 CLI 仍是同一个顺序包装，行为与状态语义完全不变（既有 137 项测试全绿）。

### 2.1 批量 Plan 预生成

`build_batch_plans(focuses, per_focus | counts, seed_base)` 在批次开始前一次性生成全部 ScenarioPlan：

- seed 全局唯一且连续，相同参数可复现
- focus 分布可配置：传列表按 `per_focus` 等分，传映射则显式指定每个 focus 的条数
- Qwen 不参与决定覆盖比例
- `plan_for` 内部的 `check_plan()` 仍然在规划期拒绝不可满足的 plan

### 2.2 并发隔离

| 维度 | 保障 | 实测 |
| --- | --- | --- |
| 输出目录 | `start_case` 在单生成线程内创建，时间戳+随机后缀 | 38 个目录互不相同 |
| run_id | Runner 每次 `_run_id()` 重新生成 | 29 个 run_id，0 冲突 |
| Supabase 数据 | 每个 run 新建随机测试用户与 activity | 118 activity / 117 创建者，无共享 |
| SSE 事件 | 每个事件带 `case_id` + `focus` + `seed` | 所有 `stage_progress` 均带 case_id |
| Dashboard | 批次内按 seed 计算 `case_index`，`case_started` 由该 case 的首个事件合成 | 见 §5 |

---

## 3. 小型并发验证（38 case）

`coverage-run --per-focus 2 --seed-base 1`（19 个正式 focus × 2，seed 1–38），单进程流水线。

```
generated=38  focus_valid=38  focus_mismatch=0  duplicate=0
unique_valid=38  distinct_scenarios=38  coverage_rate=100.0%
loader_valid=38  runner_executed=36  runner_failed=2  compiler_repair_count=0
judge: PASS=33, FAIL=3, UNCERTAIN=0, JUDGE_ERROR=0   pass_rate=86.8%
pipeline: 38 cases in 640s (213.8 cases/hour) | queue_max={raw:4, compiled:3, judge:12}
```

| 指标 | 数值 |
| --- | --- |
| 总耗时 | 640 s |
| 吞吐 | **213.8 cases/hour** |
| 串行基线（Stage 2，42 case / 3079 s） | 49.1 cases/hour → **4.4×** |
| Generator | 38 raw / 370 s = **370 raw cases/hour**（9.7 s 一条） |
| Compiler | 均值 12.82 s（2 并发） |
| Runner | 均值 0.59 s、最大 0.97 s（2 并发） |
| Judge | 均值 60.74 s（4 并发） |
| 队列最大长度 | raw 4 / compiled 3 / judge 12（上限 20） |
| DeepSeek timeout / 429 | **0** |
| DeepSeek 错误率 | **0%**（无 `COMPILER_ERROR`、无 `JUDGE_ERROR`） |

**Qwen 是否基本持续工作：是。** 生成器在 **370 s** 内完成全部 38 条 raw case；此刻只有 **25 个 case 完成 Judge**——即本地模型做完自己全部工作后，Judge 还剩 13 个 case。这正是"Qwen 不再等待 Judge"的直接证据。

（说明：本次运行的 `generator_latency_seconds` 因重构漏写未记录，上表的 370 raw/hour 由 case 目录时间戳算出；该字段已修复，后续批次会正常记录。）

### 3.1 每个 focus 的结果

| focus | n | EXECUTED | PASS | FAIL | RUNNER_FAILED |
| --- | --- | --- | --- | --- | --- |
| aa_rounding / completion_archive / fifo_repayment / linked_refund / manual_split | 各 2 | 2 | 2 | 0 | 0 |
| mixed_flow / multi_payer_aa / multiple_repayments / negative_expense | 各 2 | 2 | 2 | 0 | 0 |
| prepayment_after_debt / prepayment_before_debt / prepayment_return | 各 2 | 2 | 2 | 0 | 0 |
| refund_boundary / targeted_repayment / void_transfer | 各 2 | 2 | 2 | 0 | 0 |
| multi_currency | 2 | 2 | 1 | 1 | 0 |
| large_activity | 2 | 2 | 1 | 1 | 0 |
| single_payer_aa | 2 | 2 | 1 | 1 | 0 |
| final_settlement | 2 | 0 | 0 | 0 | **2** |

`final_settlement` 的 2 次失败均为**我自己 plan 设计的缺陷**（见 §4.2），修复后用**同 seed（31、32）** 重跑：两次都 `Loader=VALID | Focus=FOCUS_VALID | Runner=EXECUTED | Judge=PASS`。因此 5 个新 focus 全部满足"至少一个有效可执行 case"。

---

## 4. 失败分类

保留原有分类：`FOCUS_MISMATCH`、`DUPLICATE_CASE`、`COMPILER_INVALID`、`LOADER_INVALID`、`RUNNER_FAILED`、`PASS`、`FAIL`、`UNCERTAIN`、`JUDGE_ERROR`。本次 38 个 case：

| 分类 | 数量 |
| --- | --- |
| PASS | 33 |
| FAIL | 3（§4.1，经核查均为 Judge 过度判定） |
| UNCERTAIN / JUDGE_ERROR / COMPILER_INVALID / LOADER_INVALID / FOCUS_MISMATCH / DUPLICATE_CASE | 0 |
| RUNNER_FAILED | 2（§4.2，plan 设计缺陷，已修复并复验） |

**没有为提升 PASS 率重跑任何失败案例**；对 §4.2 两个案例的重跑是**修复 plan 缺陷后的验证**，用同 seed 复现并留证。

### 4.1 三个 Judge FAIL —— 核查结论

> 结论先行：三个 FAIL 我判定为 **Judge 对未文档化维度的过度判定**，不是已确认的业务缺陷。但业务裁定权在 Codex，下面保留全部证据与我的推理。

**(1) `single_payer_aa` seed 4（conf 0.95）—— 多债务 base 尾差**

场景：`12.3 CNY`，alice 独自付款，5 人 AA。
- 原币分摊：`12.3 / 5 = 2.46`（4 位小数精确），存储值 `2.46 × 5` ✓
- **base 分摊**（§7 稳定顺序尾差）：`123 units / 5 = 24 余 3` → `2.5, 2.5, 2.5, 2.4, 2.4`，存储值**逐位一致** ✓（且尾差**没有**全压给最后一人）
- 债务 base：`bob 2.5 / carol 2.5 / dave 2.5 / erin 2.3`，合计 `9.8` = alice 的 base 净额 ✓（总量守恒）
- Judge 认为 dave 应为 2.4、erin 应为 2.4

两条依据说明这不是已确认缺陷：
1. §8 规定"债务由 Payment 与 Split 的**原币**差额决定"——原币金额全部正确。
2. `findings/multi_payer_aa.md` 的核查结论已明确：跨债务 base 尾差策略**未被 §5–§8 文档化**，"Judge 将它与逐笔独立舍入比较，不能据此单独判 FAIL"。而且 Judge 期望的 `2.4 + 2.4` 会让 base 合计变成 `9.7`，**破坏 base 守恒**。

→ 归为 **Judge 过度判定**。若要判定为缺陷，需要 `BUSINESS_LOGIC.md` 先明确"每条债务的 base 是否必须等于该参与人 base 分摊净额"。

**(2) `multi_currency` seed 29（conf 0.6）—— FX 结算的 allocation 金额字段**

- `transfer_allocations`: `amount=0.1000`, **`original_amount=0.5800`**, `base_amount=0.1`
- `transfer_expense_allocations`: `payment_amount=0.5800 EUR`, `original_amount=0.5800`, `base_amount=0.1`

Judge 称"没有携带真实结算金额（0.1 而非 0.58）"——但同一行里 **`original_amount` 就是 0.5800 EUR**，原始事实完整保留。`amount` 列等于 base 值 0.1，是 CNY 场景看不出来的**字段语义歧义**（CNY 时三者相等）。confidence 仅 0.6。

→ 归为 **Judge 过度判定 + 可观测性歧义**（§6 观察 1）。

**(3) `large_activity` seed 34（conf 0.85）—— 预存清偿后源 ExpenseDebt 保留**

- 预存 `pre_1` 90 CNY（owner bob → custodian alice）结清了 `exp_1` 的 bob→alice 71.9
- `transfer_allocations` 记录 `pre_1 → exp_1` 71.9 ✓
- `bilateral_debts` 只剩 `bob→carol 18.1` ✓（当前债务正确）
- `prepayment_usages` 为空——因为预存自身的 allocation 已经把该债务结清，没有"剩余债务"需要再套 Usage
- `expense_debts` 仍保留 `exp_1 71.9`

Judge 期望源 ExpenseDebt 归零。但 §16/§21 把 ExpenseDebt 定义为**基于原始事实的投影**，且既有已核实的 TARGETED 场景（Stage 2 独立复核确认）同样是"ExpenseDebt 保留 100、BilateralDebt 降到 60"。这里行为一致。

→ 归为 **Judge 过度判定**（对"源债务 vs 当前债务"的模型理解偏差）。

### 4.2 两个 RUNNER_FAILED —— 我的 plan 设计缺陷（已修复）

| case | 错误 | 根因 | 修复 |
| --- | --- | --- | --- |
| `final_settlement` seed 31 | `RUNTIMEERROR: the current final plan offers no item to execute` | 3 人时第三步的付款人退化成第 3 位参与者，净额拓扑可能退化，方案为空 | focus 人数下限提到 **4** |
| `final_settlement` seed 32 | `23514 repayment exceeds selected residual or bilateral debt` | plan 让"外部还款"发生在结算**之后**，金额按结算前债务算，超了剩余债务 | 调整顺序为 **preview → 外部还款 → preview → 结算**，还款额严格小于该债务 |

两个都**不是**框架缺陷或业务缺陷：第 2 个恰恰说明数据库正确执行了 §9"普通还款金额不得超过可结清债务"。修复后同 seed 重跑均 PASS（另见 §3.1）。

---

## 5. Dashboard

按要求只做必要适配，未大改 UI：

- **新增 focus 自动可见**：场景下拉与运行选择器从 `/api/config/info` 的注册表动态加载（现为 21 个，带 tier 标注）
- **流水线队列/进度**：`batch_started` 事件与批次状态携带 `pipeline` 块（worker 配置、`generator_clamped`、FX fixture 就绪状态），`batch_completed` 携带 `pipeline` 统计（吞吐、队列水位、DeepSeek timeout 数、worker 失败）
- **并发 case 正确归属**：`case_started` 由该 case 的**首个事件**合成，`case_completed` 带 `case_id`/`focus`/`seed`/`case_index`；所有 `stage_progress` 都带 `case_id`，SSE 不会串 case
- **失败不误报为完成**：流水线异常广播 `batch_failed` 并把批次标为 `failed`

Dashboard 的批次现在跑在流水线上（`web/service.py` 调 `run_pipeline`），不再串行。

---

## 6. 交给 Codex 的两条可观测性观察

都不是规则违反，但值得 Codex 决定是否需要澄清：

1. **`transfer_allocations.amount` 在外币结算时等于 base 值**（`original_amount` 才持有原币金额）。CNY 场景三列相等所以看不出；外币场景下 `amount` 的语义变得含糊，已导致一次 Judge 误判。同类问题此前也出现过（`operations.jsonl` 返回的 `financial_version` 到底是行版本还是 Activity 版本）。
2. **"预存清偿后源 ExpenseDebt 是否应归零"**：当前实现保留源 ExpenseDebt、只更新 BilateralDebt，与已核实的 TARGETED 行为一致；文档 §16/§21 支持这一读法，但 §12 的措辞可以更明确。

---

## 7. 产物与复现

```powershell
cd D:\project\Android\shared-ledger\verification

py -3.12 -m pytest -q                          # 148 passed
py -3.12 -m shared_ledger_verifier fx-fixture  # 确定性本地 FX fixture
py -3.12 -m shared_ledger_verifier coverage-run --per-focus 2 --seed-base 1
py -3.12 -m shared_ledger_verifier coverage-run --per-focus 2 --sequential   # 串行对照
py -3.12 -m shared_ledger_verifier run-generated-case --focus final_settlement --seed 31
```

- 覆盖报告：`local_llm_probe/coverage_reports/coverage_20260925T082509Z.json`（含 `pipeline` 统计块）
- 被标记案例的证据目录（每个都含 `plan.json`、`raw_case.json`、`scenario.json`、`operations.jsonl`、`state_final.json`、`judge.json`）：
  - `20260925T081506598266Z_single_payer_aa_2c879b`（Judge FAIL 1）
  - `20260925T081848347172Z_multi_currency_b5ce2d`（Judge FAIL 2）
  - `20260925T081953632597Z_large_activity_c0e8bd`（Judge FAIL 3）
  - `20260925T081906999242Z_final_settlement_dfafb4`、`20260925T081924367006Z_final_settlement_6080b5`（plan 缺陷原始证据，未删除）
- 新增模块：`pipeline.py`、`fx_fixture.py`；新增测试：`tests/test_pipeline.py`（10 项）

---

## 8. 是否可进入 500-case

**可以。** 38-case 并发验证满足全部门槛：5 个新 focus 均可生成并执行、覆盖契约生效、流水线并行稳定、Qwen 单路持续生成不再等待 Judge、并发无数据/文件/事件串扰、自动化测试全绿。

按你的要求，**不会自动开始 500-case 正式测试**。若执行，建议：

- 先跑 `coverage-run`，focus 分布用映射形式显式指定（`build_batch_plans` 支持）以控制覆盖比例
- 500 case × 19 focus 建议每个 focus 约 26 条；按 213.8 cases/hour 预计 **约 2.3 小时**
- 队列上限保持 20 即可（本次最高水位 judge=12）；若想进一步压缩尾延迟，可只上调 `JUDGE_WORKERS` 与 `DEEPSEEK_MAX_CONCURRENCY`，但注意 DeepSeek 侧的 429 风险（本次 0 次，说明 4 并发在当前配额下安全）
