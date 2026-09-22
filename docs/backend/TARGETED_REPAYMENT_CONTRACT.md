# Targeted expense repayment contract

The transfer page uses the following authenticated Supabase RPCs. All amount
values use the bill's original currency unless the field name says `base` or
`payment`. A successful write increments `activities.financial_version`.

## Candidate bills

```text
list_transfer_expense_candidates(
  activity_id uuid,
  from_participant_id uuid,
  to_participant_id uuid,
  currency character(3)
) returns rows {
  expense_id uuid,
  ledger_unit_id uuid,
  ledger_unit_name text,
  title text,
  occurred_at timestamptz,
  debtor_participant_id uuid,
  creditor_participant_id uuid,
  debt_currency character(3),
  debt_original_amount numeric(20,4),
  debt_base_amount numeric(20,1),
  offset_original_amount numeric(20,4),
  settled_original_amount numeric(20,4),
  prepayment_original_amount numeric(20,4),
  remaining_original_amount numeric(20,4),
  remaining_base_amount numeric(20,1),
  payment_currency_amount numeric(20,4),
  financial_version bigint
}
```

Rows are ordered by bill occurrence time, creation time, expense id, and debt
row id. Base-currency candidates include every bill currency; an external
payment currency includes only bills with that original currency. Remaining
amounts already exclude reverse offsets, effective settlement allocations, and
prepayment usage.

## Preview

```text
preview_expense_repayment(
  activity_id uuid,
  from_participant_id uuid,
  to_participant_id uuid,
  amount numeric(20,4),
  currency character(3),
  mode text,                         -- FIFO or TARGETED
  target_expense_ids uuid[],
  expected_financial_version bigint
) returns rows {
  expense_id uuid,
  ledger_unit_id uuid,
  allocation_mode text,
  payment_currency character(3),
  payment_amount numeric(20,4),
  original_currency character(3),
  original_amount numeric(20,4),
  base_amount numeric(20,1),
  fx_rate numeric(20,10),
  remaining_original_amount numeric(20,4),
  remaining_base_amount numeric(20,1),
  source_financial_version bigint
}
```

`FIFO` ignores `target_expense_ids` and uses all eligible bills. `TARGETED`
requires one or more ids and only allocates inside that set, in FIFO order.
The amount must fit both the selected residual and the current bilateral net
debt. The preview raises `40001` when the supplied version is stale.

## Commit

```text
create_expense_repayment_v2(
  activity_id uuid,
  from_participant_id uuid,
  to_participant_id uuid,
  amount numeric(20,4),
  currency character(3),
  mode text default 'FIFO',
  target_expense_ids uuid[] default null,
  occurred_at timestamptz default now(),
  on_behalf_of_participant_id uuid default null,
  expected_financial_version bigint default null,
  request_id uuid default null
) returns {
  transfer_id uuid,
  amount numeric(20,4),
  currency character(3),
  mode text,
  financial_version bigint
}
```

`request_id` is required for this RPC. Repeating the exact payload returns the
original result before checking the supplied version; reusing an id with a
different payload raises `23505`. A stale version raises `40001`. The transfer
stores `settlement_mode` and `target_expense_ids`; each actual bill allocation
is immutable in `transfer_expense_allocations` with `allocation_mode` `FIFO`,
`TARGETED`, or `FINAL_SETTLEMENT` and payment/original/base snapshots.

## Expense repayment progress

```text
get_expense_repayment_progress(
  p_activity_id uuid,
  p_expense_id uuid
) returns rows {
  expense_id uuid,
  debtor_participant_id uuid,
  creditor_participant_id uuid,
  debt_currency character(3),
  debt_original_amount numeric(20,4),
  debt_base_amount numeric(20,1),
  settled_original_amount numeric(20,4),
  settled_base_amount numeric(20,1),
  prepayment_original_amount numeric(20,4),
  prepayment_base_amount numeric(20,1),
  offset_original_amount numeric(20,4),
  offset_base_amount numeric(20,1),
  remaining_original_amount numeric(20,4),
  remaining_base_amount numeric(20,1),
  financial_version bigint
}
```

Settlement includes ordinary targeted/FIFO allocations and final-settlement
source allocations. Final settlement hops are aggregated once per source debt
and never counted once per route hop. Voided transfers contribute zero while
their source history still keeps the expense financially locked.
