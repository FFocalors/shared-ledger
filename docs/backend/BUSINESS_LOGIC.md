# 多人活动记账软件：正式业务逻辑基线

> 状态：当前产品业务逻辑唯一基线
> 更新日期：2026-09-23
> 适用范围：当前财务业务及其产品边界。本文件不记录历史过程；数据库、RPC、Android 与测试必须遵循本基线。

## 1. 产品范围

产品为熟人共同活动提供共享账本，不是银行或支付清算服务，不计算汇兑损益。

| 状态 | 能力 |
| --- | --- |
| 已实现 | 普通/大型活动、参与人、Expense、Payment/Split、AA、服务端汇率快照、FIFO/TARGETED 还款、Activity 级预存和返还、负 Expense 退款、Final Settlement、归档、争议与图片附件。 |
| 不支持 | 无现金多人债务环路冲销、跨币种日常债务抵销、LedgerUnit 级预存、任意 FX 客户端写入、手动完成/自动归档、Expense/Transfer 恢复、数学上全局最少转账笔数保证。 |
| 未实现 | 子活动独立 Participant 名单、LedgerUnit 备注、任意文件/URL 附件、银行转账对账、汇兑损益。 |

图片附件只支持产品限定的图像类型；附件不表示任意文件或链接能力。

## 2. Activity 与 LedgerUnit

Activity 是财务边界，分普通和大型。普通 Activity 使用一个 root LedgerUnit；大型 Activity 有一个 root 和多个 sub-activity LedgerUnit。

大型 Activity 的 root 是 Activity 级公共账目单元，可记录共同消费、退款、调整及不属于具体子活动的支出，不限于退款或调整。Expense 仍遵循普通 Payment、Split 和金额规则。参加人属于 Activity 总名单，子活动不设独立名单，Expense 从同 Activity 有效 Participant 中选择。

大型 Activity 的 sub-activity 可由成员软删除或恢复；存在真实 Transfer 来源历史时不能改变删除状态。root 不作为 sub-activity 删除。LedgerUnit 级备注和预存不支持。

实现依据：[Activity/LedgerUnit](../../supabase/migrations/20260830105311_activity_lifecycle_rpc.sql)、[子活动生命周期](../../supabase/migrations/20260913112306_sub_activity_delete_restore.sql)、[转账来源历史保护](../../supabase/migrations/20260920142942_immutable_transfer_delete_restore_contract.sql)。
## 3. Participant 与 User

Participant 是账本中的人，User 是登录账号；访问成员 ActivityMember 与身份认领 ParticipantClaim 分离。无账号 Participant 也能参与账本。

每个 Activity 只有一份 Participant 总名单。同 Activity 一个 User 最多认领一个 Participant，一个 Participant 最多绑定一个 User。首个 Expense 或首个 sub-activity 写入时锁定名单；锁定后不得新增或删除 Participant，但仍可认领/解除认领已有 Participant。Expense、Transfer、预存涉及的 Participant 必须是同 Activity 的有效 Participant。

实现依据：[Participant 表](../../supabase/migrations/20260830100426_ledger_units_and_participants.sql)、[名单锁定和认领 RPC](../../supabase/migrations/20260901124212_backend_finalization_integration_readiness.sql)。

## 4. 权限

Activity Creator 同时是成员，但仅有明确授予的管理权限。非成员及匿名用户不能写入财务事实。

| 操作 | 权限 |
| --- | --- |
| Expense 创建/可编辑更新/展示更新 | Activity Member；受财务锁、版本和金额规则限制。 |
| Expense 删除 | Expense 创建者或 Activity Creator；已锁定/已有 Refund 历史时拒绝。 |
| Participant 增删 | Activity Member；名单锁定后拒绝，已认领或已有财务引用者不可删。 |
| 普通 FIFO/TARGETED settlement | Member 使用自己认领且为 Transfer 一方的 Participant；Creator 可代表未认领一方，非 Creator 不可代记。 |
| 新 Prepayment | 任一 Activity Member 可选择两名不同有效 Participant，不要求认领，不支持 behalf。 |
| Prepayment Return | Activity Member 按普通资金记录认领/Creator behalf 规则操作，方向固定为 Custodian→Owner。 |
| Final Settlement | 任一 Activity Member 可提交当前服务端建议，不要求认领双方。 |
| Void Transfer | 记录该 Transfer 的 Member 或 Activity Creator；必须填写理由，重复作废失败。 |
| Archive/Unarchive、成员管理、Activity 删除 | Activity Creator。归档后只读。 |
| Transfer dispute | Activity Member；只记争议，不改变资金和 completed。 |

实现依据：[角色校验](../../supabase/migrations/20260831055425_backend_prepayment.sql)、[预存/最终结算权限](../../supabase/migrations/20260923022250_business_logic_finalization.sql)。
## 5. 金额与币种

金额以精确十进制存储。Expense 原币金额和外币原币分摊最多 4 位小数；Activity base currency 金额使用 1 位小数。FX snapshot 使用服务端汇率和观察时间；base amount 由该 snapshot 计算，再按 0.1 单位归一。

Expense 创建和编辑必须满足：原币金额非零、币种是三位大写代码、汇率为正；Payment 与 Split 各自合计等于 Expense 原币金额；每个 Participant 在一份 Payment/Split 中至多出现一次；金额符号须与 Expense 符号相同；base currency 金额符合 1 位小数精度。自动汇率只能由服务端快照解析，客户端没有生产手工 FX 写入口。

base amount 舍入不得抹掉非零原币债务或改变债务双方。Transfer 不按发生日做 ECB 重估；其分配事实引用来源 ExpenseDebt 的原币、base 金额和历史 FX。当前贡献投影 `transfer_allocations.amount` 以 Activity base currency 计价；来源原币金额见 `original_amount`，真实 Transfer 的支付币种金额见不可变来源记录 `transfer_expense_allocations.payment_amount`，不得把这三个字段视为同一币种金额。

实现依据：[base 金额归一](../../supabase/migrations/20260830151327_base_amount_normalization.sql)、[FX snapshot 与债务重建](../../supabase/migrations/20260923022250_business_logic_finalization.sql)、[自动 FX 和 Refund 快照约束](../../supabase/migrations/20260923032928_refund_limits_and_legacy_rpc_permissions.sql)。

## 6. Expense、Payment 与 Split

Expense 是消费、退款或调整事实。正 Expense 通常代表消费；负 Expense 表示退款/调整。负金额本身不会自动关联原账单；只有填写 original_expense_id 才是 linked refund，详见第 13 节。

Payment 记录实际付款人，Split 记录最终承担人。两者独立表达，可使用多付款人和多人分摊。AA 平分用户选出的 Activity Participant；手动分摊由调用者提供各人金额。退款 Payment 可表示实际收款人，Split 可表示退款受益者。

零债务 Expense 仍是有效消费事实。例如总额 100 由 A 全额支付、全额由 A 承担，系统保存 Expense、Payment 和 Split，但不创建 ExpenseDebt。不得因为没有债务而拒绝 Expense。

实现依据：[Expense 写入及 Payment/Split 校验](../../supabase/migrations/20260830115402_expense_core_rpc.sql)、[零债务与归一回归](../../supabase/tests/database/phase2c_base_amount_normalization.sql)。

## 7. AA

AA 原币金额在所选 Participant 间等分，以原币 4 位小数保存。这里的 base amount 尾差规则适用于 Split：按 participant_order、id 稳定顺序逐个分配最小单位，正负金额对称处理；尾差不全部压给最后一人。ExpenseDebt 的 base 分配另见第 8 节。

例如 base 金额 100.0 由 3 人 AA，base 分别为 33.4、33.3、33.3，合计 100.0。外币 AA 先保持原币守恒，再独立归一 base amount。手动分摊由调用者明确提供原币金额；base rounding 不改写原币分摊。

实现依据：[公平 base 尾差分配](../../supabase/migrations/20260910133739_fair_aa_base_allocation.sql)、[公平 AA 与最终结算回归](../../supabase/tests/database/phase9_fair_aa_final_settlement.sql)。
## 8. Debt

每笔 Expense 独立生成 ExpenseDebt，再形成当前 BilateralDebt。债务由 Payment 与 Split 的原币差额决定。正向债务表示承担人欠实际付款人。Participant pair 与币种共同决定债务维度；不同币种不互相抵销。

ExpenseDebt 保留原币净额确定的 debtor、creditor、original_amount 和 Expense 的历史 FX；base_amount 是这些债务的独立折算与尾差分配结果，不要求某一条债务的 base_amount 等于同一 Participant 的 Split base 金额或 base net。债务 base 金额均不得为负，合计等于该 Expense 各债权人正向 Payment−Split base net 的合计。正常情况下，按稳定 pair 顺序逐条折算，末条承接总额尾差；若这样会使末条为负，则以原币债务金额为权重，把既定 base 总额按 0.1 最小单位分配给各 pair，并以稳定 pair 顺序处理同余数。该分配不改写原币债务或历史资金事实。

base amount 不能重新决定 debtor/creditor。原币非零但 base 舍入为零的外币 Debt 仍须保留、参与完成判定，并可按原币清偿。例如 JPY 0.01 折算后 base 为 0.0，仍是一笔有效的 0.01 JPY 债务。

不进行无现金多人环路冲销。若 A 欠 B、B 欠 C、C 欠 A，即使每人净额为零，三条 BilateralDebt 仍存在；系统不创建虚假 Transfer 或 Allocation，Activity 保持 active。

实现依据：[原币债务与投影重建](../../supabase/migrations/20260923022250_business_logic_finalization.sql)、[负补差的非负分配修复](../../supabase/migrations/20260925133211_fix_negative_expense_base_debt_allocation.sql)、[原币/零 base 分配边界](../../supabase/tests/database/phase12_multi_currency_allocation_invariants.sql)、[小额 AA 回归](../../supabase/tests/database/mass500_micro_aa_debt_allocation.sql)。

## 9. Settlement

Settlement 是 Participant 间已经真实发生的付款。普通还款只能清偿当前债务，金额不得超过该付款方向可结清的债务。当前提供 FIFO 和 TARGETED 两种来源选择；TARGETED 必须选择有效候选 Expense。Transfer 登记真实金额、付款币种、双方、时间、记录人及债务来源分配。

预览只显示候选，不预留额度。提交时服务端在一个事务中重新确认 Activity 财务版本、债务来源、金额、角色和限额；并发冲突或过期计划失败且不留下部分 Transfer。

历史外币债务可以继续按原币还款，不因 Activity 后来关闭新外币开关而被冻结。普通日常还款不执行三人以上债务路径净额化。

实现依据：[TARGETED/FIFO 还款合同](../../supabase/migrations/20260921051720_targeted_expense_repayment_contract.sql)、[还款并发测试](../../supabase/tests/database/critical_financial_concurrency.sql)。

## 10. 指定账单还款

TARGETED 还款只对服务端列出的当前有效 ExpenseDebt 候选生效。请求金额、币种、付款双方、目标 Expense、时间、behalf 和 expected financial version 一并进入服务端校验。已结算债务、Refund 后形成的新债务和多币种账单按各自当前原币投影处理。

提交成功后保存不可重排的实际分配；重建不会把同一笔付款挪到其他 Expense。退款可形成新债务，其方向由退款的负 Payment/Split 原币净额决定；之后能通过新的 TARGETED/FIFO 真实付款清偿。作废会移除 Transfer 的当前效果，但不抹掉其分配/来源历史，也不解除已触及 Expense 的财务锁。

实现依据：[候选、预览、提交与不可变分配](../../supabase/migrations/20260921051720_targeted_expense_repayment_contract.sql)、[目标还款回归](../../supabase/tests/database/targeted_expense_repayment.sql)、[多币种目标还款回归](../../supabase/tests/database/targeted_expense_repayment_multicurrency.sql)。
## 11. Transfer

Transfer 是实际资金事实，分为 settlement、prepayment、prepayment_return、final_settlement。TransferComponent 表达其中清偿或预存部分，组件合计等于 Transfer 的真实金额。Transfer 记录付款币种，不按发生日重新做 ECB 估值。

Transfer 创建后资金字段和来源历史不可修改。生命周期只有 active→voided。作废必须填写原因；历史行保留，但从当前资金投影和可执行方案移除。voided 不可恢复，也不能再次作废。相关还款分配、final path 和预存事实保留为历史。

Expense 与 Transfer 均不提供恢复 RPC。Expense 逻辑删除受创建者/Activity Creator 权限、Refund 来源和真实 Transfer 来源约束；Transfer 只能通过正式 void RPC 撤销当前效果。sub-activity 删除/恢复是组织结构生命周期，不恢复 Expense 或 Transfer。

实现依据：[Transfer lifecycle 与恢复撤权](../../supabase/migrations/20260920142942_immutable_transfer_delete_restore_contract.sql)、[作废实现](../../supabase/migrations/20260923022250_business_logic_finalization.sql)、[恢复授权契约](../../supabase/tests/database/transfer_restore_contract.sql)。

## 12. Prepayment

Prepayment 是 Activity 级账户，维度为 Activity、Owner、Custodian、币种；普通与大型 Activity 共用，不支持 LedgerUnit 级预存。创建预存代表 Owner 向 Custodian 实际付款。

新预存先清偿 Owner 当前欠 Custodian 且可按付款币种结清的债务，剩余资金才进入预存账户。base 币付款按债务历史 base valuation 清偿；外币账户清偿同币外债。投影先扣有效真实 Settlement/Final allocation，再对同币反向债务抵销，之后才应用预存 Usage。相反方向的未结债务不能提前消费另一方向的预存。

Usage 中同币外币账户优先；base 账户可按账单历史 FX 覆盖外币债务；一种外币预存不能清偿另一种外币债务。Refund 或债务变化可释放 Usage 并恢复账户余额。

Prepayment Return 是 Custodian 实际返还 Owner 的钱，方向与原存入相反，使用账户原币，不作为普通债务抵销。只可返还当前可用余额。创建 Prepayment 和 Return 均要求 request_id 与 expected financial version。任一 Activity Member 可创建 Prepayment；Return 遵守第 4 节的 Participant actor 权限。

作废预存来源前，服务端检查仍有效的 Return。若作废会使有效返还超过其他仍有效的同 Owner/Custodian/币种来源资金，则拒绝；先作废对应 Return 再作废来源。作废结果保留 Transfer 历史。

实现依据：[多币种预存与返还](../../supabase/migrations/20260920142845_multi_currency_prepayment_final_settlement_core.sql)、[投影顺序及来源作废保护](../../supabase/migrations/20260923022250_business_logic_finalization.sql)、[预存边界测试](../../supabase/tests/database/phase5_prepayment_extended.sql)。

## 13. Refund

Refund 使用负 Expense 表示，不另建 Refund 账本。未关联 original_expense_id 的负 Expense 是普通负向调整；linked refund 必须满足以下条件：

- 原 Expense 当前有效、原币金额为正，并属于同一 Activity。
- Refund 本身为负 Expense；不能关联另一笔 Refund、失效 Expense 或跨 Activity Expense。
- Refund 币种须与原 Expense 相同，并继承其完整 FX snapshot（汇率、来源、观察时间）。
- 同一原 Expense 的当前有效 linked refund 原币绝对金额合计不得超过 original_expense.original_amount。
- Payment/Split 各自守恒，但退款接收人与受益人不必按原 Expense 比例复制。

上限只统计当前未逻辑删除的 Refund；删除退款会释放可用额度。只要曾经存在 linked refund，原 Expense 财务锁不会解除，即使退款后来全部删除。标题、备注和图标可经 presentation-only 更新；金额、币种、汇率、Payment、Split、LedgerUnit、时间及其他财务事实不可重写。

还款发生后再产生 linked refund 时，已发生的真实 Transfer 保留、不被退款冲销。Refund 依据负 Payment/Split 的原币净额建立新债务；方向取决于实际退款接收人与受益人，可能与原债务同向或反向。

实现依据：[Refund 来源、上限、永久锁和 FX 继承](../../supabase/migrations/20260923032928_refund_limits_and_legacy_rpc_permissions.sql)、[Refund 合同](../../supabase/tests/database/linked_refund_contract.sql)、[关闭多币种后的历史 Refund](../../supabase/tests/database/u03_historical_foreign_currency.sql)、[结算后退款排序](../../supabase/tests/database/critical_financial_ordering.sql)。

## 14. Final Settlement

Final Settlement 适用于普通和大型 Activity 的完整 Activity 范围，不按 sub-activity 分段选择。服务端依据当前投影生成建议；预览不写事实，提交必须匹配当前建议、Activity financial_version 与 request_id。一次只执行一个完整建议项，不接受自行部分执行；每次成功后重新预览剩余计划。

base_unified 将普通 Debt 按 Activity base currency 结算，来源分配仍引用原 ExpenseDebt 的原币金额和历史 FX。original_currency 按各自原币种结算，外币 micro debt 不依赖 base rounding。

预存返还始终按账户币种 Custodian→Owner，不折算为 base currency。普通 Final Debt 和预存返还只有方向、双方、币种相同时才可合并展示；方向相反的两笔真实资金不能互相抵销。合并展示不合并底层 TransferComponent。

Final Settlement 可用多跳路径将当前债务转为参与人之间的端点付款。算法确定且可重建，可减少付款步骤，但不保证数学上全局最少笔数。纯债务环路不会自动创建 Transfer；Activity 保持 active。

作废 Final Transfer 保留历史，并将当前付款容量释放回建议；若仍有债务，可按新 financial_version 创建新 Transfer。作废 path 不再占可执行额度。任一 Activity Member 可提交当前建议，无需认领转账双方。

实现依据：[Final Settlement v2 计划与执行](../../supabase/migrations/20260920142845_multi_currency_prepayment_final_settlement_core.sql)、[void 重执行、环路与 Usage 排序](../../supabase/tests/database/critical_financial_ordering.sql)、[Final Settlement 测试](../../supabase/tests/database/phase6_final_settlement.sql)。
## 15. Multi Currency

multi_currency_enabled 表示是否允许创建新的外币财务事实，不代表能否处理已存在的外币历史。开关关闭时，新建外币 Expense 和新建外币 Prepayment 被拒绝；linked refund 继承原 Expense 的币种和完整 FX snapshot。历史外币 Debt 仍可 FIFO/TARGETED 清偿，已有外币预存仍可按账户币种返还；final、void 和 projection rebuild 继续按既有事实处理。

不做外币间直接债务抵销，不重新估值旧 Expense，不计算汇兑损益。base_unified 普通 Final Debt 使用 base currency；original_currency 使用 Debt 原币。Prepayment Return 始终使用账户币种。

新外币 Expense 只有在 Activity 允许外币且有可用服务端 FX snapshot 时才能创建；同币编辑保留原 snapshot。Transfer 和 Prepayment 保存真实收付币种，不把汇率 1 或相同数字的 base placeholder 解释为真实折算。

实现依据：[汇率 snapshot 解析](../../supabase/migrations/20260923022250_business_logic_finalization.sql)、[关闭多币种后的历史外币路径](../../supabase/tests/database/u03_historical_foreign_currency.sql)、[历史外币结算](../../supabase/tests/database/phase11_multi_currency_settlement.sql)、[排序与分币种状态](../../supabase/tests/database/critical_financial_ordering.sql)。

## 16. 历史不可变

Expense、Payment、Split、Transfer、Transfer 的 source/allocation/path、Prepayment Return 与 Refund 来源标记是原始事实。Debt、Allocation、Usage、Account、Final plan 和 completed 状态是从事实重建的投影。

Expense 在尚无真实 Transfer 来源或 linked refund 历史时，可按权限及当前版本修改财务字段。普通 Settlement、TARGETED allocation、真实 Prepayment Settlement Transfer 来源或 Final path 触及 Expense，或 Expense 成为 linked refund 来源后，其财务字段及 Payment/Split 永久锁定；Transfer 后来 void 也不解除该锁。后续投影生成的 PrepaymentUsage 本身不是真实 Transfer 来源，不会单独设置 `financial_locked`。锁定后仅允许 title、note、icon_key 等展示字段经 presentation-only RPC 修改。

Transfer 资金字段、request_id 和来源历史不可修改或删除。Transfer void 保留真实发生记录和历史 allocations，不恢复为 active。Append-only 来源表阻止直接重写财务历史。

实现依据：[Transfer source 与 append-only trigger](../../supabase/migrations/20260920142942_immutable_transfer_delete_restore_contract.sql)、[Expense presentation-only 更新](../../supabase/migrations/20260921043414_expense_financial_lock_presentation_update.sql)、[Refund 来源永久锁](../../supabase/migrations/20260923032928_refund_limits_and_legacy_rpc_permissions.sql)。

## 17. Delete 与 Void

Expense 删除为逻辑删除；只有 Expense 创建者或 Activity Creator 可以删除未锁定 Expense。有真实 Transfer 来源、linked refund 或永久 Refund 来源历史的 Expense 不可删除。Expense 不提供恢复入口；直接把 is_deleted 改回 false 也被数据库 guard 拒绝。

Transfer 不删除、不恢复。成员或 Creator 对有效 Transfer 执行一次 void，并填写理由；voided Transfer 保留全部历史，当前财务效果退出投影。再次 void 或将 voided 改回 active 均被拒绝。

大型 Activity 的 sub-activity 可由 Activity Member 逻辑删除或恢复；若该 LedgerUnit 已有真实 Transfer 来源历史，删除状态不可改变。Activity 删除由 Creator 通过软删除执行，不清除历史账务；归档 Activity 为只读。

实现依据：[Expense/Transfer 生命周期与恢复撤权](../../supabase/migrations/20260920142942_immutable_transfer_delete_restore_contract.sql)、[sub-activity 生命周期](../../supabase/migrations/20260913112306_sub_activity_delete_restore.sql)、[Expense 删除权限](../../supabase/migrations/20260830191659_backend_debt_projection.sql)。

## 18. completed 与 archive

Activity completed 是自动计算值：不存在任何非零原币 BilateralDebt，且不存在任何币种的正预存余额。是否还有 Final plan 不是独立完成条件；真实债务环路只要仍有非零 BilateralDebt，Activity 就保持 active。Dispute 不改变 completed。

activity_financial_status 的 has_unsettled_debt 按任意币种原币 Debt 是否非零判断。total_debt 仅作 base currency 金额参考。total_prepayment 只统计 base currency 账户；不得把多币余额相加伪装成 base 总额。该汇总字段沿用账户余额的四位小数数值表示，因而可显示为 `0.0000`；尾随零不代表出现四位有效的 base currency 资金金额。prepayment_by_currency 输出正余额行，结构为 [{currency, balance}]，按币种排序。

participant_financial_status 的 receivable/payable/net_balance 是 base currency 兼容汇总。balance_by_currency 输出各币种原币 Debt 与同币 Prepayment 的 receivable、payable、net_balance，按币种排序。完成状态不依赖可能互相抵销的 base numeric 合计。

Activity Creator 可手动 archive/unarchive；归档可以带未结债务或预存，并通过 warning 表明尚未结清。归档后财务写入只读，解除归档后继续按实时投影显示；系统不自动归档。

实现依据：[多币种财务状态 view 与 archive summary](../../supabase/migrations/20260923022250_business_logic_finalization.sql)、[多币种状态与纯环债回归](../../supabase/tests/database/critical_financial_ordering.sql)、[纯环债保持 active 验收](../../supabase/tests/database/phase6_final_settlement.sql)。
## 19. 并发

财务写操作在数据库事务内完成；核心 Activity 写入按 Activity 级 advisory lock 和 Activity/来源行锁串行化。服务端在锁内读取最新财务版本和来源额度，再写入事实、分配、投影与版本。校验失败时整个事务回滚，不留下部分付款、组件或投影。

预览不是余额保留。客户端带服务端返回的 expected_financial_version；版本变化时必须刷新并重算。并发 Refund 创建须在同一 Activity 序列化域重查累计上限；Settlement、Prepayment、Return、Final 执行和 void 也须重读当前有效额度。

实现依据：[Activity 财务锁、重建与版本检查](../../supabase/migrations/20260923022250_business_logic_finalization.sql)、[财务写并发回归](../../supabase/tests/database/critical_financial_concurrency.sql)、[Settlement 并发回归](../../supabase/tests/database/phase4_settlement_transfer_concurrency.sql)。

## 20. 幂等

需要重放安全的 v2 还款、预存、预存返还和最终结算必须提供 request_id 与 expected_financial_version。幂等身份由 Activity、authenticated User、operation、归一化资金 payload 和 request_id 组成。

服务端在 stale-version、archive 和后续生命周期校验前查询该 Activity 下的 request_id。若 Transfer 的 actor、类型、operation 和完整规范化 payload 均匹配，返回首次成功保存的 request_result；成功重试使用首次请求携带的原 expected_financial_version。Activity 后来归档或软删除也不能改变成功请求的原重放结果。

payload 至少包含 Activity、双方或 Owner/Custodian、金额、归一币种、模式、规范化目标 ID、occurred_at、behalf 及 expected_financial_version。跨 User、跨 operation、修改金额/币种/时间/目标/代理或其他资金语义参数后复用同一 request_id 都必须拒绝。客户端必须持久化原 request_id 与原 payload/version，不得以改变语义的新请求替代网络重试。

普通 Expense 写入和 Transfer void 不采用上述 request_id 合约；void 是单向生命周期动作，重复作废报错。不能把 v2 幂等规则泛化到所有 RPC。

实现依据：[v2 payload/actor/replay 检查](../../supabase/migrations/20260923022250_business_logic_finalization.sql)、[跨用户与生命周期重试回归](../../supabase/tests/database/idempotency_request_replay_contract.sql)、[RPC 与 legacy ACL 测试](../../supabase/tests/database/rpc_client_contract.sql)、[指定账单重试回归](../../supabase/tests/database/targeted_expense_repayment.sql)。

## 21. 原始事实与 Projection

Expense、Payment、Split、Transfer、TransferComponent、Refund source、Transfer source allocation/path 记录原始输入或已发生资金动作。ExpenseDebt、TransferAllocation 当前贡献、PrepaymentUsage、PrepaymentAccount、BilateralDebt、Final preview 与 financial status 是基于这些事实重建的结果。

重建必须稳定保留真实 Transfer 的债务来源与金额；只能让 voided Transfer 退出当前资金效果，不可删除或改写来源历史。Expense 删除、Refund 创建/删除、Transfer 登记/作废等操作触发必要投影更新。服务端内部可执行 Activity 全量重建；客户端不能直接写投影表。

实现依据：[债务/分配/预存/双边重建](../../supabase/migrations/20260923022250_business_logic_finalization.sql)、[真实分配历史](../../supabase/migrations/20260921051720_targeted_expense_repayment_contract.sql)、[全量重建一致性测试](../../supabase/tests/database/phase5_prepayment_extended.sql)。
## 22. RPC 业务契约

客户端不得调用手工 FX Expense 或旧语义财务写 RPC。当前公开财务接口如下；括号内为输入名，SQL 中 numeric typmod 以函数定义为准。

| 用途 | 当前公开 RPC |
| --- | --- |
| Expense 创建/编辑 | create_expense_auto_rate(ledger_unit_id, title, original_amount, original_currency, split_method, payments, manual_splits, aa_participant_ids, occurred_at, note, original_expense_id, icon_key)；update_expense_auto_rate(expense_id, ledger_unit_id, title, original_amount, original_currency, split_method, payments, manual_splits, aa_participant_ids, occurred_at, note, original_expense_id, icon_key) |
| Expense 展示字段/删除 | update_expense_presentation(expense_id, title, note, icon_key, expected_version)；delete_expense(expense_id) |
| 普通/指定账单还款 | list_transfer_expense_candidates(activity_id, from_participant_id, to_participant_id, currency)；preview_expense_repayment(activity_id, from_participant_id, to_participant_id, amount, currency, mode, target_expense_ids, expected_financial_version)；create_expense_repayment_v2(activity_id, from_participant_id, to_participant_id, amount, currency, mode, target_expense_ids, occurred_at, on_behalf_of_participant_id, expected_financial_version, request_id)；get_expense_repayment_progress(p_activity_id, p_expense_id) |
| Prepayment | preview_prepayment(p_activity_id, p_owner_participant_id, p_custodian_participant_id, p_amount, p_currency)；create_prepayment_v2(activity_id, owner_participant_id, custodian_participant_id, amount, currency, occurred_at, on_behalf_of_participant_id, expected_financial_version, request_id) |
| Prepayment Return | create_prepayment_return_v2(activity_id, owner_participant_id, custodian_participant_id, amount, currency, occurred_at, on_behalf_of_participant_id, expected_financial_version, request_id) |
| Final Settlement preview/read | preview_final_settlement_v2(p_activity_id, p_mode)；get_final_settlement_plan_v2(p_activity_id, p_mode) |
| Final Settlement execute | execute_final_settlement_v2(activity_id, from_participant_id, to_participant_id, amount, currency, mode, expected_financial_version, request_id, occurred_at, on_behalf_of_participant_id) |
| Transfer lifecycle | void_settlement_transfer(transfer_id, void_reason)；void_prepayment_transfer(transfer_id, void_reason) |

create_final_settlement_v2(activity_id, from_participant_id, to_participant_id, amount, currency, mode, expected_financial_version, request_id, occurred_at, on_behalf_of_participant_id) 是同一服务端 execute v2 语义的 wrapper；当前 Android 使用 execute_final_settlement_v2。只读 final plan helper 不改变事实。

手工 FX create_expense/update_expense overload、create_settlement_transfer、legacy create_prepayment/create_prepayment_return、legacy create/execute_final_settlement 和 execute_final_settlement_item 不属于 authenticated/anon 客户端契约。当前权限迁移撤销这些旧写 overload 的 PUBLIC、anon 和 authenticated EXECUTE；仅保留此前已有权限的可信 service_role 路径。生产客户端不使用 fixture adapter。

其他 Activity、Participant、Sub-activity、汇率查询、附件和 Dispute 操作由 ActivityRepository、ExchangeRateRepository、AttachmentRepository 与 FinancialRemoteDataSource 对应 RPC 处理；finance write 权限边界不开放表的直接 DML 作为替代写入口。

实现依据：[公开 finance RPC 签名和 ACL 检查](../../supabase/tests/database/rpc_client_contract.sql)、[legacy 权限撤销与正式入口 grants](../../supabase/migrations/20260923032928_refund_limits_and_legacy_rpc_permissions.sql)、[Android Expense 调用](../../app/src/main/java/com/ffocalors/sharedledger/data/expense/ExpenseRepository.kt)、[Android Transfer 调用](../../app/src/main/java/com/ffocalors/sharedledger/data/transfer/TransferRepository.kt)、[Android Financial 调用](../../app/src/main/java/com/ffocalors/sharedledger/data/financial/FinancialRemoteDataSource.kt)。
## 23. 验收示例

1. A 为 B 付款 100、B 承担 100。先登记 B 向 A 的 100 真实还款，再关联 100 退款并由 B 收款、A 受益。已发生还款必须保留；B 收到归 A 所有的退款，形成新的 B→A 100 债务。若改由 A 收款、B 受益，才形成 A→B 的反向债务。
2. A 在 B 处预存 100；同时有 A→B 100 与 B→A 100 的同币 ExpenseDebt。反向债务抵销后不生成 PrepaymentUsage，账户仍有 100。
3. 原 Expense 1000 可关联 200、300、500 三笔有效 Refund；再退任意正精度金额都失败。删除其中一笔可释放额度，但原 Expense 永久财务锁继续存在。
4. 单人自付自担的 100 Expense 保存 Expense、Payment、Split，不生成 ExpenseDebt。多付款/分摊时两组各自守恒。
5. Final 建议为 100 并执行后 void：Transfer 保留且标记 voided，当前建议重新显示 100；新版本执行只由新 Transfer 贡献当前清偿。
6. 三人 A→B、B→C、C→A 各欠 100 时，不伪造一个收敛 Transfer；债务保留，Activity active。
7. 0.01 JPY Expense 折算为 base 0.0 时，Debt 仍按 JPY 保留并可用 original_currency 显示、清偿。
8. base 100.0 由三人 AA 时，base 分配为 33.4、33.3、33.3，原币与 base 合计各自守恒。
9. 成功的 v2 还款/预存/返还/final 使用相同 Activity、User、operation、payload、request_id 和原版本重试，应返回原结果且不重复写入，即使 Activity 后来归档或软删除。改 payload、换 User 或改 operation 后复用 request_id 必须拒绝。
10. 多币种账户状态按币种排序返回；不能将 USD 与 JPY 相加后标为 base currency。completed 依据原币债务和各账户有效余额计算。
11. 已记录 USD Expense 和 USD Prepayment 后关闭多币种开关：新的 USD Expense/Prepayment 被拒绝；历史 USD FIFO/TARGETED、Final、Return、linked Refund、void 和投影重建仍按既有资金事实处理。

可追踪验收证据见[数据库测试状态](../../supabase/tests/database/TEST_STATUS.md)、[关键事务排序回归](../../supabase/tests/database/critical_financial_ordering.sql)、[关键并发回归](../../supabase/tests/database/critical_financial_concurrency.sql)。

## 24. 硬约束

1. 本文件定义唯一现行业务基线；数据库 RPC、约束、Android 和验收不得实现矛盾规则。
2. authenticated 用户必须是有效 Activity Member；财务动作按第 4 节单独授权。
3. Activity 是 Participant 名单和财务边界；sub-activity 不设独立名单，大型 root 可记 Activity 级共同消费。
4. Expense 原币 Payment、Split 各自守恒；AA 与手动分摊不能用 base rounding 改写原币事实。
5. 债务拓扑由原币 Expense facts 得出；不同币种不互相抵销，base 为零也不能删除非零原币 Debt。
6. 新外币事实使用服务端 FX，客户端不得提交任意 FX；历史外币 settlement、返还、refund 和 rebuild 不因创建开关关闭而失效。
7. Transfer/Refund 资金含义不能被投影重建抹除。投影可以重算，已发生事实不能编辑、删除或恢复。
8. 普通 Debt settlement 指向当前可清偿债务；Final 执行必须匹配当前服务端 plan。
9. Prepayment Usage 遵守同币债务净抵、有效真实 allocation 和账户币种规则；Return 不进入普通 Debt graph。
10. linked Refund 必须引用正 Expense，满足同 Activity/币种、累计有效原币上限和完整 FX snapshot 继承。
11. Activity completed 逐币判断非零原币 Debt 与预存余额；base numeric summary 不代替完成状态。
12. 需要重放安全的 v2 写入验证 request_id、actor、operation 和规范化 payload，再执行新操作的 stale-version/lifecycle 校验。
13. 财务事务在服务端锁内重校验、原子提交并推进版本；不开放客户端直接 DML、部分成功或预览额度预留。
14. 作废不等于删除或恢复；只产生单向 lifecycle 变化并退出有效投影。
15. Activity Creator 手动管理归档；归档后 Activity 只读，系统不得自动归档。
16. 纯债务环路不自动清零；仍有真实未结债务时不得 completed。
17. 预存 summary 保留 currency 维度；不得将不同币种相加并标成 base currency。
18. 每项 accepted behavior 对应具体实现和可追踪验收证据；当前有效/退役测试见 TEST_STATUS.md。
