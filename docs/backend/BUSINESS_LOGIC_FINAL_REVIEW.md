# Business Logic 最终反向审计

> 首次审计日期：2026-09-23；冻结后 AA 修复复核：2026-09-24。
> 首次冻结判定：**BUSINESS LOGIC FREEZE v1.0: READY**。以下第 1–11 节保留首次收口的历史脉络，最新测试数据与 v1.1 状态以第 12 节为准。
> v1.1 判定：**BUSINESS LOGIC FREEZE v1.1: READY**。AA 修复、最小规则澄清、全套回归及基于新基线的六项 Judge 均已完成。

## 1. 最终业务基线状态

[BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) 已重写为 24 节现行业务基线，覆盖产品范围、账本与参与人、逐操作权限、原币与 FX、Expense/Payment/Split、AA、债务、还款、预存、退款、Final Settlement、完成状态、并发、幂等、RPC 和验收规则。正文描述当前应有的行为，不保留旧业务承诺或开发过程。U03 的 true→false 行为和 C09 生命周期重试已加入验收例。

首次冻结时尚未实现 Business Logic Verification Workflow；随后已实现轻量 v0.1 Runner 和 v0.2 DeepSeek Judge。旧审计与首次冻结结论保留为历史资料，冻结后的复核结果记录于第 12 节。

## 2. 本次修复列表

- `20260923022250_business_logic_finalization.sql` 收口 FX snapshot、债务与预存投影顺序、Transfer void、Final path、完成状态、多币种 read model 和 v2 request replay。
- `20260923032928_refund_limits_and_legacy_rpc_permissions.sql` 加入 linked Refund 来源、累计限额、永久来源锁、FX 继承与旧客户端写权限撤销。
- Android 财务数据层切换到 auto-rate/v2 RPC，持久化原始 `request_id`/payload/version，并按币种解析财务状态；保留用户既有 UI 修改。
- 数据库回归整理新增 U03 历史外币开关、C09 request replay、Refund 来源、客户端 RPC ACL 等合同测试；旧 Transfer restore 正向行为明确 RETIRED。C02 Refund fixture 增加固定发生时间，确保 TARGETED 目标集合随 Expense UUID 稳定。
- BUSINESS_LOGIC.md 改写为唯一现行基线；本文件记录实现、测试与 Freeze 反向审计。

2026-09-24 的 AA 原币债务修复使用新增 `20260924020249_fix_aa_original_currency_debt_preservation.sql`；没有修改上述历史 migration 或 `BUSINESS_LOGIC.md`。详见第 12 节。

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

[TEST_STATUS.md](../../supabase/tests/database/TEST_STATUS.md) 按文件列出 PASS/RETIRED 状态；`legacy_rpc_fixture_adapters.sql` 仅作被 include 的 fixture。首次冻结 clean-reset 隔离运行 **28 files / 185 pgTAP tests PASS**；2026-09-24 新增 AA 专项后，从零应用 42 个 migration 的最新全套为 **29 files / 213 pgTAP tests PASS**，`phase8_transfer_restore.sql` 仍 RETIRED。C02 Refund fixture 已设置确定发生时间。Windows Supabase CLI 的 bind-mount 缺陷由 runner 回退到隔离数据库网络内的 `pg_prove` 3.36。

## 8. 并发测试结果

并发测试文件均通过：`critical_financial_concurrency.sql`、`phase3_debt_projection_concurrency.sql`、`phase4_settlement_transfer_concurrency.sql`、`phase5_prepayment_concurrency.sql`、`phase6_final_settlement_concurrency.sql`、`phase7_finalization_concurrency.sql`。它们检查并发 Settlement、退款限额、Return 和 Final 执行最终等价于合法串行结果且不超额。

## 9. Android 测试结果

Android 验证于首次冻结和本次 AA 修复后均通过：`testDebugUnitTest`（264 tests）、`assembleDebug`、`lintDebug`。临时 JDK 为 `C:\Users\zhy20\.jdks\openjdk-21.0.2`，未修改共享项目配置。Lint 无错误；已有仓库警告未阻断构建。

## 10. 已知限制

- 本次验证不包含生产/远端 Supabase、真实 Auth gateway、设备上的端到端流程或外部汇率服务连通性测试；数据库 FX 测试使用确定性缓存 fixture。
- 产品不做银行转账对账、汇兑损益、任意文件/URL 附件、LedgerUnit 级预存、跨币种日常债务抵销或无现金多人债务环路冲销。
- Final Settlement 是确定性建议，不承诺数学上全局最少付款笔数。

## 11. 首次 Business Logic Freeze 判断（2026-09-23 历史结论）

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

首次审计完成后，Business Logic Verification Workflow 已在该冻结基线上实现轻量 Runner 与 Judge。冻结后发现的 AA 缺陷及当前 v1.1 门槛见第 12 节。

## 12. 冻结后 AA 原币债务修复与 v1.1 复核（2026-09-24）

### 发现与根因

v0.2 Judge 在旧 run `20260923T103210Z-560a671e` 中发现 `multi_payer_aa`：A、B 原币分别付款 60、40，三人 AA 原币 Split 为 33.3334、33.3333、33.3333，故 C 对 A、B 的原币债务应为 26.6666、6.6667。旧投影记录为 26.7000、6.6333；base 值 26.7、6.6 本身符合一位小数尾差分配。[原始 finding](../../verification/findings/multi_payer_aa.md)和旧 FAIL run 保留不变。

首次污染发生在旧 `private.normalize_expense_debt_currency`：`private.rebuild_expense_debts_locked` 已从原币 Payment−Split 生成正确 pair，随后 normalizer 用 `round(ed.amount / fx_rate, 4)` 将已舍入 base 反算回非末行 `original_amount`，末行吸收原币总量尾差。`private.rebuild_bilateral_debts_locked` 再读取这些受污染的原币债务。因此这是实现缺陷，不是业务规则变更。

### 修复与边界

新增 [AA 原币债务修复 migration](../../supabase/migrations/20260924020249_fix_aa_original_currency_debt_preservation.sql)，不改历史 migration：normalizer 重新依据 Payment−Split 的逐人原币净额匹配债务双方和金额，只归一原币 pair，不用 base 反推原币；base 仍由原有独立尾差规则确定。双边投影对同一 FX snapshot 的反向债务使用来源行已保存的 base 尾差，防止 AA 负账抵销留下 0.1 虚影；不同历史 FX snapshot 时保留旧合同的原债汇率估值。原币剩余为零时不保留孤立 base 余额。

迁移只回填当前未归档且未财务锁定的有效 Expense 投影；真实 Transfer/Final 来源保护的锁定历史行及归档历史快照不自动改写。因此既往已经锁定且受旧 normalizer 污染的历史数据不在本次自动修复范围内，需单独审计。没有修改 Expense、Settlement、Refund、Prepayment、Final、Android 或 Judge 的业务写入行为，也没有部署远端 Production。

### 回归结果

- 从零应用全部 **42 个 migration** 的隔离 Supabase 全套：**29 个有效文件 / 213 个 pgTAP 断言 PASS**；其中新增 [AA 原币债务专项](../../supabase/tests/database/aa_original_currency_debt_contract.sql)为 28/28，六个现有并发测试文件全部 PASS。`phase8_transfer_restore.sql` 继续 RETIRED。详细状态见 [TEST_STATUS.md](../../supabase/tests/database/TEST_STATUS.md)。
- Android：`testDebugUnitTest` 264 项、`assembleDebug`、`lintDebug` 通过。Workflow 单元测试：32/32 通过。
- 永久保留 [Multi-Payer AA 回归场景](../../verification/scenarios/regression/multi_payer_aa_original_currency.json)，不依赖数据库 UUID；原 Smoke 场景没有删改。
- 另一个从零迁移的本地 API/Auth 隔离项目，在最终规则澄清提交后重新运行原有 6 个 Smoke，全部 `EXECUTED`；六项 Runner/Judge 的 `business_logic_commit` 均为 `12fc5401f6e7f25ce9e110b47d9feda2722795cf`。其中 `multi_payer_aa` 新状态为 C→A 26.6666/base 26.7、C→B 6.6667/base 6.6。相同 `deepseek-v4.1-flash` Judge 最终 **6 PASS / 0 FAIL / 0 UNCERTAIN / 0 JUDGE_ERROR**。

| Smoke 场景 | 新 run_id | Runner | 最新 Judge |
| --- | --- | --- | --- |
| `basic_single_payment` | `20260924T072905Z-15792760` | EXECUTED | PASS |
| `linked_refund_after_settlement` | `20260924T072905Z-5ba8cbda` | EXECUTED | PASS |
| `multi_payer_aa` | `20260924T072906Z-af9584bb` | EXECUTED | PASS |
| `multiple_repayments` | `20260924T072906Z-04cb55f8` | EXECUTED | PASS |
| `prepayment_before_debt` | `20260924T072907Z-9c847e18` | EXECUTED | PASS |
| `targeted_partial_repayment` | `20260924T072907Z-ab422f11` | EXECUTED | PASS |

### 首轮 Judge 分歧、业务裁决与已知限制

首轮新 run 的 `prepayment_before_debt` 资金投影正确：先 B→A 预存 200，再生成 B→A 账单 100，`PrepaymentUsage` 用去 100，余额 100，当前 BilateralDebt 为零而 Activity 仍 active。Judge 首轮 FAIL 理由是 Expense `financial_locked=false`。`20260923032928_refund_limits_and_legacy_rpc_permissions.sql` 的列注释及锁定触发器明确规定 Usage 单独存在不触发永久锁；该场景没有触及账单的真实 Prepayment Settlement 来源。现已在 `BUSINESS_LOGIC.md` §16 明确区分两者，最终新 run 判 PASS；首轮 `judge.previous_fail.json` 仍保存。

首轮 `linked_refund_after_settlement` 先出现网络 `API_ERROR`，重试后 Judge 判 FAIL，要求 A→B；但旧、新 run 的资金状态相同，均为负 Payment B 100、负 Split A 100，按原币 Payment−Split 产生 B→A 100。用户明确裁决“B 收款、A 受益；B 再付 A”。因此仅澄清 `BUSINESS_LOGIC.md` §10/§13/§23：退款债务方向由实际负 Payment/Split 决定，本例 B→A；若 A 收款、B 受益才是 A→B。最终新 run 判 PASS。首次网络错误的 `judge.previous_error.json` 和首轮 FAIL 保留为历史；原旧 PASS run 与原 AA FAIL run 也未修改。

**BUSINESS LOGIC FREEZE v1.1: READY**，范围是已验证的本地业务实现与训练前规则基线。实现修复提交为 `663b12f27db390998a350897004f8e5e064c09b0`；用户裁决后的业务文档基线提交为 `12fc5401f6e7f25ce9e110b47d9feda2722795cf`。未改 Judge Prompt、DeepSeek Client、Smoke 输入或旧运行记录。远端 Production 尚未部署；可能受旧 normalizer 影响且已财务锁定的历史数据须在后续单独审计，不能把本地 fresh-run PASS 当作远端存量数据已回填的证明。
