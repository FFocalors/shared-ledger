# Business Logic 最终反向审计

> 审计日期：2026-09-23  
> 审计范围：当前业务基线、两份收口 migration、有效数据库测试、Android 客户端契约及指定构建结果。  
> 判定：**BUSINESS LOGIC FREEZE: READY**。最终 clean-reset 数据库套件、Android 验证与文档反向一致性检查均通过。

## 1. 最终业务基线状态

[BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) 已重写为 24 节现行业务基线，覆盖产品范围、账本与参与人、逐操作权限、原币与 FX、Expense/Payment/Split、AA、债务、还款、预存、退款、Final Settlement、完成状态、并发、幂等、RPC 和验收规则。正文描述当前应有的行为，不保留旧业务承诺或开发过程。U03 的 true→false 行为和 C09 生命周期重试已加入验收例。

本次未实现 Business Logic Verification Workflow。旧审计保留为历史审计资料；本文件与 BUSINESS_LOGIC.md 构成当前反向审计和业务基线。

## 2. 本次修复列表

- `20260923022250_business_logic_finalization.sql` 收口 FX snapshot、债务与预存投影顺序、Transfer void、Final path、完成状态、多币种 read model 和 v2 request replay。
- `20260923032928_refund_limits_and_legacy_rpc_permissions.sql` 加入 linked Refund 来源、累计限额、永久来源锁、FX 继承与旧客户端写权限撤销。
- Android 财务数据层切换到 auto-rate/v2 RPC，持久化原始 `request_id`/payload/version，并按币种解析财务状态；保留用户既有 UI 修改。
- 数据库回归整理新增 U03 历史外币开关、C09 request replay、Refund 来源、客户端 RPC ACL 等合同测试；旧 Transfer restore 正向行为明确 RETIRED。C02 Refund fixture 增加固定发生时间，确保 TARGETED 目标集合随 Expense UUID 稳定。
- BUSINESS_LOGIC.md 改写为唯一现行基线；本文件记录实现、测试与 Freeze 反向审计。

## 3. C01–C11 处理结果

| 项目 | 结果 |
| --- | --- |
| C01 FX snapshot | `resolve_expense_fx_snapshot` 使用与行锁一致的 volatility；同币编辑保留 snapshot，linked Refund 继承完整 snapshot。`exchange_rate_expense_snapshots.sql` 覆盖相关合同。 |
| C02 结算后退款 | 重建保留真实 Settlement/Final 来源并形成反向债务。最初全套测试暴露 Refund fixture 时间相同、UUID tie-break 不稳定，可能选中已被 reverse-net 清零的 TARGETED 目标。测试现显式设置 -60 Refund 先于 -40；单文件连续 3 次及最终全套均通过。数据库负责人核对认为这是 fixture 顺序问题，不是资金算法缺陷。 |
| C03 PrepaymentUsage | 同币反向债务与有效真实 Allocation/Final path 先计入可用额度，Usage 不重复消费已抵销或已结清债务；退款可释放相应 Usage。`critical_financial_ordering.sql` 与 `phase5_prepayment_extended.sql` 的最新全套断言通过。 |
| C04 Final void | voided Final path 保留历史但退出当前执行容量；重算后可按新版本重新执行。由 `critical_financial_ordering.sql` 和 `phase6_final_settlement.sql` 覆盖。 |
| C05 零债 Expense | 合法自付自担事实可保存而不生成 Debt；由 `phase2c_base_amount_normalization.sql` 覆盖。 |
| C06 手工 FX 旧 RPC | 客户端无 authenticated/anon 任意 FX 写入口；由权限 migration 和 `rpc_client_contract.sql` 覆盖。 |
| C07 资金级 FX | Transfer/Prepayment 保留实际金额和付款币种，不作 Transfer 日期 ECB 重估；Allocation/Usage 引用来源 Expense 历史 FX，新 Prepayment Return 的占位折算值不解释为实际 FX。 |
| C08 多币种状态 | `has_unsettled_debt` 按原币 Debt 判定；Activity 与 Participant view 提供排序后的逐币种 JSON，兼容汇总只表示 base currency。由 `critical_financial_ordering.sql` 覆盖。 |
| C09 幂等重试 | actor、operation、类型与规范化 payload 一致时，在 stale-version/lifecycle 检查前返回原结果；原 expected version 重试不重复写入。跨用户、跨操作、改 payload、归档后及软删除后重放由 `idempotency_request_replay_contract.sql` 定向覆盖。 |
| C10 预存来源作废 | 若仍有效返还会超过作废后的剩余同账户资金来源，拒绝作废来源；先作废返还后可继续作废来源。由 `phase5_prepayment_extended.sql` 覆盖。 |
| C11 base=0 微额 | 非零原币 Debt 即使 base amount 为零也保留，按原币参与清偿与完成判定；由 `phase12_multi_currency_allocation_invariants.sql` 覆盖。 |

## 4. U01–U05 最终裁决

| 项目 | 最终规则与实现 |
| --- | --- |
| U01 Participant 名单 | Activity 只有一份有效 Participant 总名单；子活动不设独立名单。大型 Activity root 是可记普通共同消费的公共 LedgerUnit。 |
| U02 linked Refund | 只能关联同 Activity 当前有效的正 Expense；有效 Refund 原币合计不得超过来源金额；继承来源 FX；永久来源记录使原 Expense 财务锁不因退款删除而解除。 |
| U03 关闭多币种 | 开关限制新外币 Expense/Prepayment。已有外币 FIFO/TARGETED、Final、Return、Refund、void 和 projection rebuild 按历史事实继续工作。`u03_historical_foreign_currency.sql` 最新定向 14/14 PASS。 |
| U04 纯债务环路 | MVP 不做无现金多人环路冲销；不创建虚假 Transfer/Allocation，仍有原币债务时 Activity 保持 active。 |
| U05 Legacy RPC | Android 使用 auto-rate Expense 与 v2 财务写入口；列出的手工 FX、旧 settlement/prepayment/final 写 overload 撤销客户端执行权。 |

## 5. Legacy RPC 处理结果

`20260923032928_refund_limits_and_legacy_rpc_permissions.sql` 撤销旧手工 FX `create_expense`/`update_expense`、`create_settlement_transfer`、legacy `create_prepayment`/`create_prepayment_return`、旧 final-settlement 写 overload 与 `execute_final_settlement_item` 的 PUBLIC、anon、authenticated EXECUTE。正式入口 grants 由 ACL block 明确授予；只保留此前已授予的可信服务端路径。`rpc_client_contract.sql` 检查客户端权限。

`phase8_transfer_restore.sql` 因与 Transfer 资金事实不可恢复规则冲突而标为 RETIRED；替代授权合同由 `transfer_restore_contract.sql` 验证。`legacy_rpc_fixture_adapters.sql` 是 transaction-local fixture helper，不是生产入口或独立测试。

## 6. 正式客户端 RPC

当前公开财务接口及参数名以 [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) 第 22 节为准：

- Expense：`create_expense_auto_rate`、`update_expense_auto_rate`、`update_expense_presentation`、`delete_expense`。
- FIFO/TARGETED：`list_transfer_expense_candidates`、`preview_expense_repayment`、`create_expense_repayment_v2`、`get_expense_repayment_progress`。
- Prepayment：`preview_prepayment`、`create_prepayment_v2`、`create_prepayment_return_v2`。
- Final：`preview_final_settlement_v2`、`get_final_settlement_plan_v2`、`execute_final_settlement_v2`。`create_final_settlement_v2` 是相同 execute 语义 wrapper；当前 Android 调用 execute 入口。
- Lifecycle：`void_settlement_transfer`、`void_prepayment_transfer`。

客户端不能以手工 FX RPC、旧写 overload 或投影表直接 DML 绕过正式契约。

## 7. 当前数据库测试结果

[TEST_STATUS.md](../../supabase/tests/database/TEST_STATUS.md) 按文件列出 PASS/RETIRED 状态；`legacy_rpc_fixture_adapters.sql` 仅作被 include 的 fixture。最新 clean-reset 隔离运行 **28 files / 185 pgTAP tests PASS**，所有当前有效测试通过，`phase8_transfer_restore.sql` 明确 RETIRED。C02 Refund fixture 已设置确定发生时间；该 C02 文件曾连续 3 次定向通过，最终全套也通过。U03 历史外币重建专项 14/14、C09 request replay（含 archive 与 soft-delete）专项 11/11 通过。Windows Supabase CLI 的 bind-mount 缺陷由 runner 回退到隔离数据库网络内的 `pg_prove` 3.36；全套在 clean/reset 数据库上完成。

## 8. 并发测试结果

并发测试文件均通过：`critical_financial_concurrency.sql`、`phase3_debt_projection_concurrency.sql`、`phase4_settlement_transfer_concurrency.sql`、`phase5_prepayment_concurrency.sql`、`phase6_final_settlement_concurrency.sql`、`phase7_finalization_concurrency.sql`。它们检查并发 Settlement、退款限额、Return 和 Final 执行最终等价于合法串行结果且不超额。

## 9. Android 测试结果

当前 Android 验证通过：`testDebugUnitTest`（264 tests）、`assembleDebug`、`lintDebug`。临时 JDK 为 `C:\Users\zhy20\.jdks\openjdk-21.0.2`，未修改共享项目配置。Lint 无错误；已有仓库警告未阻断构建。

## 10. 已知限制

- 本次验证不包含生产/远端 Supabase、真实 Auth gateway、设备上的端到端流程或外部汇率服务连通性测试；数据库 FX 测试使用确定性缓存 fixture。
- 产品不做银行转账对账、汇兑损益、任意文件/URL 附件、LedgerUnit 级预存、跨币种日常债务抵销或无现金多人债务环路冲销。
- Final Settlement 是确定性建议，不承诺数学上全局最少付款笔数。

## 11. Business Logic Freeze 判断

**BUSINESS LOGIC FREEZE: READY**

13 项 Freeze 条件均满足。最新 clean reset 全套 28/185 PASS，C02 fixture 的确定性修正由全套覆盖；U03/C09 专项及 Android 测试通过，24 节基线与最终 migration、RPC 和测试结论一致。

| Freeze 条件 | 状态 |
| --- | --- |
| 1. C01–C11 有明确处理结果 | PASS |
| 2. 无已知资金含义丢失 bug | PASS：C02 失败源自 Refund fixture 顺序不稳定；核对数据后确认 target 已无剩余债务，固定顺序后全套通过 |
| 3. U01–U05 按裁决落实 | PASS |
| 4. 当前有效数据库测试全部通过 | PASS：28 files / 185 pgTAP tests；没有有效测试 FAIL |
| 5. 旧契约测试明确 RETIRED | PASS：Transfer restore 旧正向契约 RETIRED 并有替代 ACL 测试 |
| 6. 指定账单还款联合场景验证 | PASS：Settlement→linked Refund→reverse debt→TARGETED 清偿通过 |
| 7. Refund/Prepayment/Final 联合路径通过 | PASS：排序、返还、Final path 和 projection rebuild 联合回归通过 |
| 8. 多币种原币残值不丢失 | PASS：U03 true→false 重建、C11 零 base 与 multi-currency allocation 回归 |
| 9. completed 判定正确 | PASS：原币 Debt、逐币种余额及纯环债回归 |
| 10. request_id 重试及跨用户规则正确 | PASS：exact/payload/actor/operation/archive/soft-delete 重放专项 11/11 |
| 11. migrations 从零完整重放 | PASS：clean reset 从零应用所有 migrations 成功 |
| 12. Android 单元测试完整通过 | PASS：264 tests；build/lint 同过 |
| 13. BUSINESS_LOGIC.md 与实现一致 | PASS：24 节业务规则、正式 RPC、view 字段和最新数据库测试相符；所有引用链接可解析 |

最终审计完成；Business Logic Verification Workflow 可以在此冻结基线上开始独立设计。
