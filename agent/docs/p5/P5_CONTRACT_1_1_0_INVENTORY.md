# P5 契约 1.1.0：交给 App 线的增量清单

快照：`agent/contracts/v1.1.0/`（新）；`agent/contracts/v1.0.0/` 保留为历史，不再更新。
导出一致性：`python -m agent.app.export_contracts --check` 退出码 0；回归测试见 `agent/tests/test_contract_snapshot.py`。

## 版本

| 版本 | 1.0.0 | 1.1.0 | 说明 |
|---|---|---|---|
| `api` | 1.0.0 | **1.1.0** | wire 字段 `api_version` / `ProtocolVersions.api` 全部改为 1.1.0 |
| `semantic` | 1.0.0 | 1.0.0 | 未变 |
| `operations` | 1.0.0 | 1.0.0 | 未变（模型可见的写操作集合没有扩展） |
| `trajectory` | 1.0.0 | 1.0.0 | 未变 |

**App 必须同步**：所有请求体与响应体的 `api_version` 由 `1.0.0` 改为 `1.1.0`；
服务端按 Literal 严格校验，旧的 `1.0.0` 请求会被 422 拒绝。

## 新增 operation（22 个，全部在 `ProposalOperation` 中）

- `expense.delete` → intent `ExpenseDeleteIntent` / command `FixedExpenseDeleteCommand` / preview `ExpensePreview`
- `settlement.repayment` → intent `RepaymentIntent` / command `FixedRepaymentCommand` / preview `RepaymentPreview`
- `transfer.void` → intent `VoidTransferIntent` / command `FixedVoidTransferCommand` / preview `TransferVoidPreview`
- `prepayment.create` → intent `PrepaymentIntent` / command `FixedPrepaymentCommand` / preview `PrepaymentPreview`
- `prepayment.return` → intent `PrepaymentReturnIntent` / command `FixedPrepaymentReturnCommand` / preview `PrepaymentReturnPreview`
- `settlement.final` → intent `FinalSettlementIntent` / command `FixedFinalSettlementCommand` / preview `FinalSettlementPreview`
- `expense.refund` → intent `ExpenseRefundIntent` / command `FixedExpenseRefundCommand` / preview `RefundPreview`
- `expense.negative_adjustment` → intent `NegativeAdjustmentIntent` / command `FixedNegativeAdjustmentCommand` / preview `NegativeAdjustmentPreview`
- `activity.create` → intent `ActivityCreateIntent` / command `FixedActivityCreateCommand` / preview `ManagementPreview`
- `activity.join` → intent `ActivityJoinIntent` / command `FixedActivityJoinCommand` / preview `ManagementPreview`
- `participant.create` → intent `ParticipantCreateIntent` / command `FixedParticipantCreateCommand` / preview `ManagementPreview`
- `participant.delete` → intent `ParticipantDeleteIntent` / command `FixedParticipantDeleteCommand` / preview `ManagementPreview`
- `participant.claim` → intent `ParticipantClaimIntent` / command `FixedParticipantClaimCommand` / preview `ManagementPreview`
- `participant.unclaim` → intent `ParticipantUnclaimIntent` / command `FixedParticipantUnclaimCommand` / preview `ManagementPreview`
- `subactivity.create` → intent `SubActivityCreateIntent` / command `FixedSubActivityCreateCommand` / preview `ManagementPreview`
- `subactivity.delete` → intent `SubActivityDeleteIntent` / command `FixedSubActivityDeleteCommand` / preview `ManagementPreview`
- `subactivity.restore` → intent `SubActivityRestoreIntent` / command `FixedSubActivityRestoreCommand` / preview `ManagementPreview`
- `activity.member.remove` → intent `ActivityMemberRemoveIntent` / command `FixedActivityMemberRemoveCommand` / preview `ManagementPreview`
- `activity.creator.transfer` → intent `ActivityCreatorTransferIntent` / command `FixedActivityCreatorTransferCommand` / preview `ManagementPreview`
- `activity.archive` → intent `ActivityArchiveIntent` / command `FixedActivityArchiveCommand` / preview `ManagementPreview`
- `activity.unarchive` → intent `ActivityUnarchiveIntent` / command `FixedActivityUnarchiveCommand` / preview `ManagementPreview`
- `activity.delete` → intent `ActivityDeleteIntent` / command `FixedActivityDeleteCommand` / preview `ManagementPreview`

1.0.0 已有的三个：`expense.create`、`expense.update`、`expense.presentation.update`。

## 新增 preview kind（8 个）

- `RepaymentPreview` — `kind = "repayment"`
- `TransferVoidPreview` — `kind = "transfer_void"`
- `PrepaymentPreview` — `kind = "prepayment"`
- `PrepaymentReturnPreview` — `kind = "prepayment_return"`
- `FinalSettlementPreview` — `kind = "final_settlement"`
- `RefundPreview` — `kind = "refund"`
- `NegativeAdjustmentPreview` — `kind = "negative_adjustment"`
- `ManagementPreview` — `kind = "management"`

`ProposalPreview` 是按 `kind` 判别的联合；1.0.0 只有 `ExpensePreview`（`kind="expense"`）。

## 既有模型上的加法字段

- `ExpenseSnapshot.is_deleted`（`bool`，P5.3 新增）——预览里表达“已删除”。
- `ExpenseDeletedChange`（`field="is_deleted"` 的变更项，P5.3 新增）。
- `PreconditionSnapshot.activity_id` 现在可空：`activity.create` / `activity.join` 在活动存在之前发生。
- `ProposalRecord` / 卡片的 `preview` 联合新增 8 个 kind；`operation` 联合新增 22 个值。

## 字段明细

### `ExpenseDeleteIntent`

- `kind`（必填）: `const 'expense.delete'`
- `expense_ref`（必填）: `enum ['expense_selected', 'expense_1', 'expense_2', ... 17 values]`

### `FixedExpenseDeleteCommand`

- `operation`（必填）: `const 'expense.delete'`
- `activity_id`（必填）: `string(uuid)`
- `expense_id`（必填）: `string(uuid)`
- `expected_expense_version`（必填）: `string(signed-bigint 1..9223372036854775807)`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `expected_is_deleted`（可选）: `boolean`

### `ExpensePreview`

- `kind`（必填）: `const 'expense'`
- `summary`（必填）: `string(max 240)`
- `before`（可选）: `ExpenseSnapshot | null`
- `after`（必填）: `ExpenseSnapshot`
- `changes`（必填）: `array<ExpenseTitleChange | ExpenseAmountChange | ExpenseCurrencyChange | ExpenseLedgerUnitChange | ExpensePaymentsChange | ExpenseSplitChange | ExpenseNoteChange | ExpenseOccurredAtChange | ExpenseIconChange | ExpenseFxChange | ExpenseDeletedChange>`
- `activity_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `generated_at`（必填）: `string(date-time)`
- `simulation`（必填）: `boolean`

### `RepaymentIntent`

- `kind`（必填）: `const 'settlement.repayment'`
- `activity_id`（必填）: `string(uuid)`
- `from_participant_id`（必填）: `string(uuid)`
- `to_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `mode`（必填）: `enum ['FIFO', 'TARGETED']`
- `target_expense_ids`（可选）: `array<string(uuid)>`

### `FixedRepaymentCommand`

- `operation`（必填）: `const 'settlement.repayment'`
- `activity_id`（必填）: `string(uuid)`
- `from_participant_id`（必填）: `string(uuid)`
- `to_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `mode`（必填）: `enum ['FIFO', 'TARGETED']`
- `target_expense_ids`（可选）: `array<string(uuid)>`
- `occurred_at`（必填）: `string(date-time)`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`

### `RepaymentPreview`

- `kind`（必填）: `const 'repayment'`
- `summary`（必填）: `string(max 240)`
- `activity_id`（必填）: `string(uuid)`
- `from_participant_id`（必填）: `string(uuid)`
- `to_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `mode`（必填）: `enum ['FIFO', 'TARGETED']`
- `target_expense_ids`（可选）: `array<string(uuid)>`
- `allocations`（必填）: `array<RepaymentAllocation>`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `generated_at`（必填）: `string(date-time)`
- `simulation`（必填）: `boolean`

### `VoidTransferIntent`

- `kind`（必填）: `const 'transfer.void'`
- `transfer_id`（必填）: `string(uuid)`
- `void_reason`（必填）: `string(max 240)`

### `FixedVoidTransferCommand`

- `operation`（必填）: `const 'transfer.void'`
- `activity_id`（必填）: `string(uuid)`
- `transfer_id`（必填）: `string(uuid)`
- `transfer_type`（必填）: `enum ['settlement', 'prepayment', 'prepayment_return', 'final_settlement']`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `expected_is_voided`（可选）: `boolean`
- `expected_recorded_by`（必填）: `string(uuid)`
- `expected_activity_archived`（可选）: `boolean`
- `expected_activity_deleted`（可选）: `boolean`
- `void_reason`（必填）: `string(max 240)`

### `TransferVoidPreview`

- `kind`（必填）: `const 'transfer_void'`
- `summary`（必填）: `string(max 240)`
- `activity_id`（必填）: `string(uuid)`
- `transfer_id`（必填）: `string(uuid)`
- `transfer_type`（必填）: `enum ['settlement', 'prepayment', 'prepayment_return', 'final_settlement']`
- `from_participant_id`（必填）: `string(uuid)`
- `to_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `void_reason`（必填）: `string(max 240)`
- `is_voided`（必填）: `boolean`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `generated_at`（必填）: `string(date-time)`
- `simulation`（必填）: `boolean`

### `PrepaymentIntent`

- `kind`（必填）: `const 'prepayment.create'`
- `activity_id`（必填）: `string(uuid)`
- `owner_participant_id`（必填）: `string(uuid)`
- `custodian_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`

### `FixedPrepaymentCommand`

- `operation`（必填）: `const 'prepayment.create'`
- `activity_id`（必填）: `string(uuid)`
- `owner_participant_id`（必填）: `string(uuid)`
- `custodian_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `occurred_at`（必填）: `string(date-time)`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `expected_settlement_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `expected_prepayment_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `expected_new_balance`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `on_behalf_of_participant_id`（可选）: `const None`

### `PrepaymentPreview`

- `kind`（必填）: `const 'prepayment'`
- `summary`（必填）: `string(max 240)`
- `activity_id`（必填）: `string(uuid)`
- `owner_participant_id`（必填）: `string(uuid)`
- `custodian_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `settlement_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `prepayment_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `new_balance`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `generated_at`（必填）: `string(date-time)`
- `simulation`（必填）: `boolean`

### `PrepaymentReturnIntent`

- `kind`（必填）: `const 'prepayment.return'`
- `activity_id`（必填）: `string(uuid)`
- `owner_participant_id`（必填）: `string(uuid)`
- `custodian_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`

### `FixedPrepaymentReturnCommand`

- `operation`（必填）: `const 'prepayment.return'`
- `activity_id`（必填）: `string(uuid)`
- `owner_participant_id`（必填）: `string(uuid)`
- `custodian_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `occurred_at`（必填）: `string(date-time)`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `expected_current_balance`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `on_behalf_of_participant_id`（可选）: `const None`

### `PrepaymentReturnPreview`

- `kind`（必填）: `const 'prepayment_return'`
- `summary`（必填）: `string(max 240)`
- `activity_id`（必填）: `string(uuid)`
- `owner_participant_id`（必填）: `string(uuid)`
- `custodian_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `current_balance`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `post_balance_note`（可选）: `const '返还后余额以服务端执行结果为准'`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `generated_at`（必填）: `string(date-time)`
- `simulation`（必填）: `boolean`

### `FinalSettlementIntent`

- `kind`（必填）: `const 'settlement.final'`
- `activity_id`（必填）: `string(uuid)`
- `from_participant_id`（必填）: `string(uuid)`
- `to_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `mode`（必填）: `enum ['base_unified', 'original_currency']`

### `FixedFinalSettlementCommand`

- `operation`（必填）: `const 'settlement.final'`
- `activity_id`（必填）: `string(uuid)`
- `from_participant_id`（必填）: `string(uuid)`
- `to_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `mode`（必填）: `enum ['base_unified', 'original_currency']`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `expected_activity_type`（必填）: `enum ['normal', 'large']`
- `expected_ordinary_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `expected_prepayment_return_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `occurred_at`（必填）: `string(date-time)`
- `on_behalf_of_participant_id`（可选）: `const None`

### `FinalSettlementPreview`

- `kind`（必填）: `const 'final_settlement'`
- `summary`（必填）: `string(max 2000)`
- `activity_id`（必填）: `string(uuid)`
- `mode`（必填）: `enum ['base_unified', 'original_currency']`
- `from_participant_id`（必填）: `string(uuid)`
- `to_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `ordinary_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `prepayment_return_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `is_prepayment_return`（必填）: `boolean`
- `plan`（必填）: `array<FinalSettlementPlanItem>`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `generated_at`（必填）: `string(date-time)`
- `simulation`（必填）: `boolean`

### `ExpenseRefundIntent`

- `kind`（必填）: `const 'expense.refund'`
- `original_expense_ref`（必填）: `enum ['expense_selected', 'expense_1', 'expense_2', ... 17 values]`
- `title`（必填）: `string(max 120)`
- `original_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `payment_allocations`（必填）: `array<PaymentAllocation>`
- `split`（必填）: `EqualSplitIntent | ManualSplitIntent`
- `occurred_at`（可选）: `string(date-time) | null`
- `note`（可选）: `string(max 1000) | null`

### `FixedExpenseRefundCommand`

- `operation`（必填）: `const 'expense.refund'`
- `activity_id`（必填）: `string(uuid)`
- `original_expense_id`（必填）: `string(uuid)`
- `ledger_unit_id`（必填）: `string(uuid)`
- `title`（必填）: `string(max 120)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `payment_allocations`（必填）: `array<CanonicalPayment>`
- `split`（必填）: `CanonicalEqualSplit | CanonicalManualSplit`
- `occurred_at`（必填）: `string(date-time)`
- `note`（可选）: `string(max 1000) | null`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `expected_original_version`（必填）: `string(signed-bigint 1..9223372036854775807)`
- `expected_original_financial_locked`（必填）: `boolean`
- `expected_refunded_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `expected_original_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`

### `RefundPreview`

- `kind`（必填）: `const 'refund'`
- `summary`（必填）: `string(max 600)`
- `activity_id`（必填）: `string(uuid)`
- `original_expense_id`（必填）: `string(uuid)`
- `original_title`（必填）: `string(max 120)`
- `refund_title`（必填）: `string(max 120)`
- `original_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `refunded_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `refund_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `remaining_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `expected_original_version`（必填）: `string(signed-bigint 1..9223372036854775807)`
- `expected_original_financial_locked`（必填）: `boolean`
- `generated_at`（必填）: `string(date-time)`
- `simulation`（必填）: `boolean`

### `NegativeAdjustmentIntent`

- `kind`（必填）: `const 'expense.negative_adjustment'`
- `ledger_unit_ref`（必填）: `enum ['ledger_unit_selected', 'ledger_unit_1', 'ledger_unit_2', ... 17 values]`
- `title`（必填）: `string(max 120)`
- `original_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `original_currency`（必填）: `string /^[A-Z]{3}$/`
- `payment_allocations`（必填）: `array<PaymentAllocation>`
- `split`（必填）: `EqualSplitIntent | ManualSplitIntent`
- `occurred_at`（可选）: `string(date-time) | null`
- `note`（可选）: `string(max 1000) | null`

### `FixedNegativeAdjustmentCommand`

- `operation`（必填）: `const 'expense.negative_adjustment'`
- `activity_id`（必填）: `string(uuid)`
- `ledger_unit_id`（必填）: `string(uuid)`
- `title`（必填）: `string(max 120)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `payment_allocations`（必填）: `array<CanonicalPayment>`
- `split`（必填）: `CanonicalEqualSplit | CanonicalManualSplit`
- `occurred_at`（必填）: `string(date-time)`
- `note`（可选）: `string(max 1000) | null`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`

### `NegativeAdjustmentPreview`

- `kind`（必填）: `const 'negative_adjustment'`
- `summary`（必填）: `string(max 600)`
- `activity_id`（必填）: `string(uuid)`
- `title`（必填）: `string(max 120)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `generated_at`（必填）: `string(date-time)`
- `simulation`（必填）: `boolean`

### `ActivityCreateIntent`

- `kind`（必填）: `const 'activity.create'`
- `name`（必填）: `string(max 120)`
- `activity_type`（必填）: `enum ['normal', 'large']`
- `base_currency`（必填）: `string /^[A-Z]{3}$/`
- `multi_currency_enabled`（可选）: `boolean`

### `FixedActivityCreateCommand`

- `operation`（必填）: `const 'activity.create'`
- `name`（必填）: `string(max 120)`
- `activity_type`（必填）: `enum ['normal', 'large']`
- `base_currency`（必填）: `string /^[A-Z]{3}$/`
- `multi_currency_enabled`（可选）: `boolean`

### `ManagementPreview`

- `kind`（必填）: `const 'management'`
- `summary`（必填）: `string(max 600)`
- `operation`（必填）: `enum ['activity.create', 'activity.join', 'participant.create', ... 14 values]`
- `activity_id`（可选）: `string(uuid) | null`
- `activity_name`（可选）: `string(max 120) | null`
- `activity_type`（可选）: `enum ['normal', 'large'] | null`
- `base_currency`（可选）: `string /^[A-Z]{3}$/ | null`
- `multi_currency_enabled`（可选）: `boolean | null`
- `join_code`（可选）: `string /^[0-9]{8}$/ | null`
- `participant_id`（可选）: `string(uuid) | null`
- `participant_name`（可选）: `string(max 120) | null`
- `participant_order`（可选）: `integer[0..] | null`
- `participant_names`（可选）: `array<string(max 120)>`
- `sub_activity_id`（可选）: `string(uuid) | null`
- `sub_activity_name`（可选）: `string(max 120) | null`
- `target_user_ref`（可选）: `string(max 40) | null`
- `unsettled`（可选）: `boolean | null`
- `financial_summary`（可选）: `string(max 240) | null`
- `generated_at`（必填）: `string(date-time)`
- `simulation`（必填）: `boolean`

### `ActivityJoinIntent`

- `kind`（必填）: `const 'activity.join'`
- `join_code`（必填）: `string /^[0-9]{8}$/`

### `FixedActivityJoinCommand`

- `operation`（必填）: `const 'activity.join'`
- `join_code`（必填）: `string /^[0-9]{8}$/`

### `ParticipantCreateIntent`

- `kind`（必填）: `const 'participant.create'`
- `activity_id`（必填）: `string(uuid)`
- `name`（必填）: `string(max 120)`
- `participant_order`（可选）: `integer[0..] | null`

### `FixedParticipantCreateCommand`

- `operation`（必填）: `const 'participant.create'`
- `activity_id`（必填）: `string(uuid)`
- `name`（必填）: `string(max 120)`
- `participant_order`（可选）: `integer[0..] | null`
- `expected_participants_locked`（可选）: `boolean`
- `expected_activity_archived`（可选）: `boolean`
- `expected_activity_deleted`（可选）: `boolean`

### `ParticipantDeleteIntent`

- `kind`（必填）: `const 'participant.delete'`
- `activity_id`（必填）: `string(uuid)`
- `participant_id`（必填）: `string(uuid)`

### `FixedParticipantDeleteCommand`

- `operation`（必填）: `const 'participant.delete'`
- `activity_id`（必填）: `string(uuid)`
- `participant_id`（必填）: `string(uuid)`
- `expected_participant_name`（必填）: `string(max 120)`
- `expected_participant_deleted`（可选）: `boolean`
- `expected_claimed_or_used`（可选）: `boolean`
- `expected_participants_locked`（可选）: `boolean`
- `expected_activity_archived`（可选）: `boolean`
- `expected_activity_deleted`（可选）: `boolean`

### `ParticipantClaimIntent`

- `kind`（必填）: `const 'participant.claim'`
- `activity_id`（必填）: `string(uuid)`
- `participant_id`（必填）: `string(uuid)`

### `FixedParticipantClaimCommand`

- `operation`（必填）: `const 'participant.claim'`
- `activity_id`（必填）: `string(uuid)`
- `participant_id`（必填）: `string(uuid)`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `expected_activity_archived`（可选）: `boolean`
- `expected_claim_state`（可选）: `enum ['none', 'mine']`

### `ParticipantUnclaimIntent`

- `kind`（必填）: `const 'participant.unclaim'`
- `activity_id`（必填）: `string(uuid)`

### `FixedParticipantUnclaimCommand`

- `operation`（必填）: `const 'participant.unclaim'`
- `activity_id`（必填）: `string(uuid)`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `expected_activity_archived`（可选）: `boolean`
- `expected_claim_participant_id`（必填）: `string(uuid)`

### `SubActivityCreateIntent`

- `kind`（必填）: `const 'subactivity.create'`
- `activity_id`（必填）: `string(uuid)`
- `name`（必填）: `string(max 120)`
- `participant_ids`（必填）: `array<string(uuid)>`

### `FixedSubActivityCreateCommand`

- `operation`（必填）: `const 'subactivity.create'`
- `activity_id`（必填）: `string(uuid)`
- `name`（必填）: `string(max 120)`
- `participant_ids`（必填）: `array<string(uuid)>`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `expected_activity_type`（必填）: `enum ['normal', 'large']`
- `expected_activity_archived`（可选）: `boolean`

### `SubActivityDeleteIntent`

- `kind`（必填）: `const 'subactivity.delete'`
- `activity_id`（必填）: `string(uuid)`
- `sub_activity_id`（必填）: `string(uuid)`

### `FixedSubActivityDeleteCommand`

- `operation`（必填）: `const 'subactivity.delete'`
- `activity_id`（必填）: `string(uuid)`
- `sub_activity_id`（必填）: `string(uuid)`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `expected_is_deleted`（必填）: `boolean`
- `expected_activity_type`（必填）: `enum ['normal', 'large']`
- `expected_activity_archived`（可选）: `boolean`

### `SubActivityRestoreIntent`

- `kind`（必填）: `const 'subactivity.restore'`
- `activity_id`（必填）: `string(uuid)`
- `sub_activity_id`（必填）: `string(uuid)`

### `FixedSubActivityRestoreCommand`

- `operation`（必填）: `const 'subactivity.restore'`
- `activity_id`（必填）: `string(uuid)`
- `sub_activity_id`（必填）: `string(uuid)`
- `expected_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`
- `expected_is_deleted`（必填）: `boolean`
- `expected_activity_type`（必填）: `enum ['normal', 'large']`
- `expected_activity_archived`（可选）: `boolean`

### `ActivityMemberRemoveIntent`

- `kind`（必填）: `const 'activity.member.remove'`
- `activity_id`（必填）: `string(uuid)`
- `user_id`（必填）: `string(uuid)`

### `FixedActivityMemberRemoveCommand`

- `operation`（必填）: `const 'activity.member.remove'`
- `activity_id`（必填）: `string(uuid)`
- `user_id`（必填）: `string(uuid)`
- `expected_creator_user_id`（必填）: `string(uuid)`
- `expected_archived`（可选）: `boolean`
- `expected_members_digest`（必填）: `string /^[0-9a-f]{64}$/`

### `ActivityCreatorTransferIntent`

- `kind`（必填）: `const 'activity.creator.transfer'`
- `activity_id`（必填）: `string(uuid)`
- `new_creator_user_id`（必填）: `string(uuid)`

### `FixedActivityCreatorTransferCommand`

- `operation`（必填）: `const 'activity.creator.transfer'`
- `activity_id`（必填）: `string(uuid)`
- `new_creator_user_id`（必填）: `string(uuid)`
- `expected_creator_user_id`（必填）: `string(uuid)`
- `expected_archived`（可选）: `boolean`
- `expected_members_digest`（必填）: `string /^[0-9a-f]{64}$/`

### `ActivityArchiveIntent`

- `kind`（必填）: `const 'activity.archive'`
- `activity_id`（必填）: `string(uuid)`

### `FixedActivityArchiveCommand`

- `operation`（必填）: `const 'activity.archive'`
- `activity_id`（必填）: `string(uuid)`
- `expected_creator_user_id`（必填）: `string(uuid)`
- `expected_archived`（必填）: `boolean`

### `ActivityUnarchiveIntent`

- `kind`（必填）: `const 'activity.unarchive'`
- `activity_id`（必填）: `string(uuid)`

### `FixedActivityUnarchiveCommand`

- `operation`（必填）: `const 'activity.unarchive'`
- `activity_id`（必填）: `string(uuid)`
- `expected_creator_user_id`（必填）: `string(uuid)`
- `expected_archived`（必填）: `boolean`

### `ActivityDeleteIntent`

- `kind`（必填）: `const 'activity.delete'`
- `activity_id`（必填）: `string(uuid)`

### `FixedActivityDeleteCommand`

- `operation`（必填）: `const 'activity.delete'`
- `activity_id`（必填）: `string(uuid)`
- `expected_creator_user_id`（必填）: `string(uuid)`
- `expected_archived`（可选）: `boolean`
- `expected_is_deleted`（可选）: `boolean`

## 共享支撑模型（P5 新增）

### `RepaymentAllocation`

- `expense_id`（必填）: `string(uuid)`
- `ledger_unit_id`（必填）: `string(uuid)`
- `allocation_mode`（必填）: `enum ['FIFO', 'TARGETED']`
- `payment_currency`（必填）: `string /^[A-Z]{3}$/`
- `payment_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `original_currency`（必填）: `string /^[A-Z]{3}$/`
- `original_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `base_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `fx_rate`（必填）: `string /^(0|[1-9][0-9]{0,19})(\.[0-9]{1,10})?$/`
- `remaining_original_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `remaining_base_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `source_financial_version`（必填）: `string(signed-bigint 0..9223372036854775807)`

### `FinalSettlementPlanItem`

- `from_participant_id`（必填）: `string(uuid)`
- `to_participant_id`（必填）: `string(uuid)`
- `amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `ordinary_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `prepayment_return_amount`（必填）: `string /^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/`
- `currency`（必填）: `string /^[A-Z]{3}$/`
- `is_prepayment_return`（必填）: `boolean`

## 相对 1.0.0 的变更形态（加法核对）

- 32 个文件内容变化，0 个新增文件（P5 模型以 `$defs` 合并进已有根 schema）。
- `ProposalOperation` 枚举 3 → 25；`ProposalPreview` 联合 1 → 9 个 kind。
- `ExpenseSnapshot` 新增 `is_deleted`；`ExpensePreview.changes` 新增 `ExpenseDeletedChange`（10 → 11 个成员）。
- `PreconditionSnapshot.activity_id` 从必填变为可空（`anyOf` + `default`），`required` 5 → 4。
- 所有 `api_version` / `versions.api` 常量由 `1.0.0` 改为 `1.1.0`。
- 没有任何字段被删除或改名；唯一的“移除”是单成员联合的 `$ref` 被多成员联合的
  `oneOf` + `discriminator` 取代（JSON Schema 表示形态变化，不是契约删除）。

## 快照位置

- 每个根模型：`schemas/<Model>.schema.json`（48 个 schema 文件，与 1.0.0 同名同集合）。
- P5 新增模型以 `$defs` 形式出现在 `schemas/ProposalRecord.schema.json`、
  `schemas/ConfirmableProposalCard.schema.json`、`schemas/InactiveProposalCard.schema.json`；
  App 线可以从这些 `$defs` 直接抽取，或按本清单的字段表生成类型。
- OpenAPI：`openapi.json`，`info.version = 1.1.0`；`components.schemas` 含全部模型。
- 能力注册表 / 状态机 / 校验分层：`capability-registry.json`、`state-transitions.json`、
  `validation-layers.json`。
- 清单与指纹：`manifest.json`（`api_version=1.1.0`，源文件与生成文件 SHA-256）。

## App 线改造要点

1. 全局把 `api_version` 常量改为 `1.1.0`。
2. `ProposalOperation` 枚举补齐 22 个新值；未知值要能安全忽略而不是崩溃。
3. `ProposalPreview` 按 `kind` 分派，补齐 8 个新 kind；渲染字段以本清单为准。
4. 卡片确认只依赖 `command_digest` + `confirmation_nonce`，命令体本身不需要 App 构造。
5. 判断管理类动作时先用 operation，再用 `ManagementPreview.operation` 细分具体动作。
