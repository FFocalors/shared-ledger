# MASS500-001 修复记录

## 结果

`0.3 CNY / 5 人 AA` 的合法 Expense 先前因末条 base 债务补差为负而被拒绝。新 migration `20260925133211_fix_negative_expense_base_debt_allocation.sql` 在此类溢出时，按原币债务权重分配确定的 base 总额，以 `0.1` 为单位按最大余数补足，余数相同时使用既有 pair 顺序。原币债务的金额与方向不变，base 债务非负且守恒。旧补差非负时逐条保留原结果。

没有批量回填。既有投影重建仍跳过 financially locked Expense，历史 Transfer allocation 快照保持不可变；本次未修改该保护路径。

## 验证

- 从零应用全部 43 条 migration 的隔离本地数据库：30 个 pgTAP 文件、223 条断言通过，包含 6 个并发测试文件。
- 新增 `mass500_micro_aa_debt_allocation.sql` 的 8 条断言：`0.3 / 5` 生成四条 `0.0600` 原币债务，base 为 `0.1、0.1、0、0`，重复重建稳定；旧合法 `1.2 / 5` 分配保持不变。
- 既有 `aa_original_currency_debt_contract.sql` 通过，原币债务历史回归未破坏。
- verification 离线测试：162 passed、1691 subtests passed。
- Android：`testDebugUnitTest assembleDebug lintDebug` 通过。
- 原 MASS500-001 Scenario 在新建、完整的本地隔离 Supabase 栈重放一次：run `20260925T134146Z-8d36f68b`，Runner `EXECUTED`，`create_expense` 成功；`state_final` 的四条原币债务均为 `0.0600 CNY`，base 分别为 `0.1、0.1、0.0、0.0`。未调用 Judge。

原 MASS500-001 的失败 run 保留。隔离栈的服务已停止。临时项目目录位于 `D:\computer\Hermes\temp\shared-ledger-dbtests-79113b0586`；递归清理由自动审批策略拒绝，目录仍在磁盘，未再次尝试删除。

## 其他候选

- MASS500-002：裁定为规则文档歧义，不属于已确认业务 Bug。单条 debt base 不要求逐人等于 Split base/net；原币正确、base 非负且合计守恒是约束。旧合法 `1.2 / 5` 分配保持不变，规则已写入 `BUSINESS_LOGIC.md` §7–8。
- MASS500-003：`transfer_allocations.amount` 是 base currency 金额；字段单位已在 `BUSINESS_LOGIC.md` §5 明确，无资金计算修复。
- MASS500-004：`total_prepayment` 的四位小数是账户余额汇总的数值表示；`0.0000` 不表示四位有效 base 资金金额，已在 `BUSINESS_LOGIC.md` §18 明确。
