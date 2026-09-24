# multi_payer_aa — 已核实的原币债务投影缺陷

- **状态：** 已核实的实现缺陷；保留 FAIL，尚未修复
- **scenario_id：** `multi_payer_aa`
- **run_id：** `20260923T103210Z-560a671e`
- **verdict：** `FAIL`（Judge，confidence 0.95）

## 规则依据

- `docs/backend/BUSINESS_LOGIC.md` §5：base amount 根据 FX snapshot 计算并按 0.1 归一；base 舍入不得抹掉非零原币债务或改变债务双方。
- §6：Payment 表示实际付款人，Split 表示最终承担人，两者独立表达并支持多付款人与多人分摊。
- §7：AA 原币金额在所选参与人间等分并以 4 位小数保存；base rounding 不改写原币分摊。
- §8：每笔 Expense 独立生成债务；债务由 Payment 与 Split 的原币差额决定，base amount 不能重新决定 debtor/creditor。

## 预期、实际与差异

该场景为 CNY 100.0000，FX 为 1。A、B 分别支付 60.0000、40.0000；AA 原币分摊为 A 33.3334、B 33.3333、C 33.3333。因此按 Payment 与 Split 的原币差额，A 的净额为 +26.6666，B 的净额为 +6.6667，C 的净额为 −33.3333：

| 项目 | 预期原币债务 | 实际原币债务 | 差异 |
| --- | --- | --- | --- |
| C→A ExpenseDebt / BilateralDebt | 26.6666 CNY | 26.7000 CNY | 多 0.0334 |
| C→B ExpenseDebt / BilateralDebt | 6.6667 CNY | 6.6333 CNY | 少 0.0334 |

Expense 金额、payments、splits 及各自合计与场景相符。上述原币债务差异直接违反 §8 所述“债务由 Payment 与 Split 的原币差额决定”。

**Base 尾差备注：** `state_final.json` 中 C→A 和 C→B 的 base amounts 分别为 26.7、6.6。当前实现要求所有债务 base 合计等于正 participant base nets 合计，并由最后一条债务吸收尾差，所以 6.6 可由代码完整解释。Judge 将它与逐笔独立舍入的 6.7 比较，不能据此单独判 FAIL；文档 §5–§8 没有明确展开这一跨债务尾差策略。有效 FAIL 依据是原币金额被改写，不能把文档的 base 尾差缺口等同于这个已核实缺陷。

## 实现核查（2026-09-23）

结论：**原币 FAIL 成立，属于数据库投影实现缺陷，不是模型误判或 Collector 字段混淆。** 无需修改业务规则即可解释根因：新重建函数先按原币净额生成正确债务，随后仍运行的旧归一流程又从已舍入 base 金额反推原币，覆盖了正确结果。

1. Runner 使用 `create_expense_auto_rate`（`verification/src/shared_ledger_verifier/runner.py:364`）。`private.create_expense_auto_rate_impl` 调用 `private.create_expense_projected_impl`（`20260913112419_ecb_exchange_rate_expense_snapshots.sql:449`），后者调用 `private.rebuild_expense_and_bilateral_debts`（`20260830191659_backend_debt_projection.sql:477`）。迁移路径均位于 `supabase/migrations/`。
2. 当前 `private.rebuild_expense_and_bilateral_debts` 在 `20260919164707_multi_currency_settlement.sql:106` 起依次执行 AA base 重分配、旧债务归一、债务重建、**新债务再次归一**、Transfer/Prepayment/Bilateral 投影。因此 normalizer 不只用于迁移旧数据。
3. 当前 `private.rebuild_expense_debts_locked`（`20260923022250_business_logic_finalization.sql:295`、`:323`、`:409`、`:418`）计算原币 participant nets，按原币范围配对，并写入正确的 `original_amount`。其 base 总额是 `max(60−33.4,0)+max(40−33.3,0)=26.6+6.7=33.3`。第一行 base 为 `round(26.6666×1,1)=26.7`；末行 base 为 `33.3−26.7=6.6`。此刻两行 `(original,base)` 应为 `(26.6666,26.7)`、`(6.6667,6.6)`。
4. INSERT trigger 当前定义已在 `20260920120259_fix_multi_currency_allocation_invariants.sql:7` 修正，`:24` 起使用 `coalesce(new.original_amount,round(...))` 保留显式原币值；该 migration 注释也明确防止由 rounded base 重建错误 pair amount。因此触发器不是本次覆盖来源。
5. 当前 `private.normalize_expense_debt_currency`（`20260923022250_business_logic_finalization.sql:440`）在 `:447` 保存原币总量 `33.3333`，但在 `:449`、`:459`–`:461` 将非末行改为 `round(ed.amount/fx,4)`，并将末行设为原币总量减前行反推合计。于是第一行变为 `26.7000`，末行为 `33.3333−26.7000=6.6333`，**精确复现 run 的两个金额**。只守住债务总量，没有守住每位债权人的原币净额。
6. `private.rebuild_bilateral_debts_locked`（同一 finalization migration `:949`，`:962` 读取 `ed.original_amount`）继续投影错误原币数值。本场景没有 Transfer、Prepayment 或反向债务，因而 BilateralDebt 原样继承该差异。Collector 在 `verification/src/shared_ledger_verifier/collector.py:157`、`:174` 优先读取数据库 `original_amount`，base 单独读取，未互换字段。
7. 全活动重建同样在 `20260921051720_targeted_expense_repayment_contract.sql:240`–`:241` 重建后运行 normalizer；简单重建不能消除该缺陷。

### 现有测试为什么没有解释掉此 FAIL

- `supabase/tests/database/phase2c_base_amount_normalization.sql:294` 检查 AA 原币 splits 的 `33.3334/33.3333/33.3333`；`:306` 起检查 base splits。它们并非本场景各债权人原币债务的断言。
- `supabase/tests/database/phase12_multi_currency_allocation_invariants.sql` 的 `47.2 EUR keeps 23.4 original debt and 179.5 base debt` 只有一条债务，normalizer 末行等于原总量，不暴露非末行覆盖。
- 同文件 `four-party original topology has two debts and no C-to-B ghost row` 检查行数与不存在的 pair，未断言两条原币债务金额是否各自守恒。
- `phase9_fair_aa_final_settlement.sql` 主要相关断言检查 base split、base bilateral 和 plan；base 守恒不能证明原币 participant nets 守恒。

本轮使用现有 Smoke 状态、当前有效函数定义、精确手算和测试断言核查；未运行全库测试，也未修改 migration、RPC、业务规则或原始 `judge.json`。修复及新增覆盖本缺陷的数据库回归属于后续独立业务修复，不在 v0.2 Judge 收口中自动执行。

## 证据文件

- `verification/runs/20260923T103210Z-560a671e/scenario.json`
- `verification/runs/20260923T103210Z-560a671e/state_final.json`
- `verification/runs/20260923T103210Z-560a671e/judge.json`
- `docs/backend/BUSINESS_LOGIC.md` §5–§8
