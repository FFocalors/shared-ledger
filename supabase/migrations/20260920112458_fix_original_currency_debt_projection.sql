begin;

-- `expense_debts.amount` remains the authoritative base-currency projection.
-- Reconstruct the original-currency debt from the original payment/split facts
-- instead of dividing the rounded base amount by fx_rate.  The latter loses
-- information whenever payments and AA splits were rounded independently.
create or replace function private.normalize_expense_debt_currency(p_expense_id uuid)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_activity_id uuid;
  v_original_currency character(3);
  v_fx_rate numeric(20,10);
begin
  select lu.activity_id, e.original_currency, e.fx_rate
    into v_activity_id, v_original_currency, v_fx_rate
  from public.expenses e
  join public.ledger_units lu on lu.id = e.ledger_unit_id
  where e.id = p_expense_id;

  if not found then
    raise exception using errcode = 'P0002', message = 'expense was not found for currency normalization';
  end if;

  -- The existing expense-debt rebuild matches base-currency creditor/debtor
  -- queues in participant order. Recreate that FIFO match in original units
  -- using interval overlap, so every current expense_debts pair receives the
  -- exact original net amount for the same pair. A caller may invoke this
  -- before rebuilding an expense; stale pairs are therefore intentionally left
  -- untouched and will be replaced by rebuild_expense_debts_locked immediately.
  drop table if exists pg_temp.fix_original_currency_debt_matches;
  create temporary table fix_original_currency_debt_matches (
    debtor_participant_id uuid not null,
    creditor_participant_id uuid not null,
    original_amount numeric(20,4) not null check (original_amount > 0),
    primary key (debtor_participant_id, creditor_participant_id)
  ) on commit drop;

  insert into pg_temp.fix_original_currency_debt_matches(
    debtor_participant_id,
    creditor_participant_id,
    original_amount
  )
  with participant_nets as (
    select
      p.id as participant_id,
      p.participant_order,
      (
        coalesce(pay.paid, 0::numeric)
        - coalesce(split.owed, 0::numeric)
      )::numeric(20,4) as net_original
    from public.participants p
    left join (
      select participant_id, pg_catalog.sum(amount) as paid
      from public.payments
      where expense_id = p_expense_id
      group by participant_id
    ) pay on pay.participant_id = p.id
    left join (
      select participant_id, pg_catalog.sum(amount) as owed
      from public.splits
      where expense_id = p_expense_id
      group by participant_id
    ) split on split.participant_id = p.id
    where p.activity_id = v_activity_id
      and (pay.participant_id is not null or split.participant_id is not null)
  ),
  creditors as (
    select participant_id, participant_order, net_original
    from participant_nets
    where net_original > 0
  ),
  debtors as (
    select participant_id, participant_order, -net_original as owed_original
    from participant_nets
    where net_original < 0
  ),
  creditor_ranges as (
    select
      participant_id,
      coalesce(pg_catalog.sum(net_original) over (
        order by participant_order, participant_id
        rows between unbounded preceding and 1 preceding
      ), 0::numeric)::numeric(20,4) as range_start,
      pg_catalog.sum(net_original) over (
        order by participant_order, participant_id
        rows between unbounded preceding and current row
      )::numeric(20,4) as range_end
    from creditors
  ),
  debtor_ranges as (
    select
      participant_id,
      coalesce(pg_catalog.sum(owed_original) over (
        order by participant_order, participant_id
        rows between unbounded preceding and 1 preceding
      ), 0::numeric)::numeric(20,4) as range_start,
      pg_catalog.sum(owed_original) over (
        order by participant_order, participant_id
        rows between unbounded preceding and current row
      )::numeric(20,4) as range_end
    from debtors
  )
  select
    d.participant_id,
    c.participant_id,
    (
      least(c.range_end, d.range_end)
      - greatest(c.range_start, d.range_start)
    )::numeric(20,4)
  from debtor_ranges d
  cross join creditor_ranges c
  where least(c.range_end, d.range_end) > greatest(c.range_start, d.range_start);

  update public.expense_debts ed
  set original_amount = m.original_amount,
      original_currency = v_original_currency,
      fx_rate = v_fx_rate
  from pg_temp.fix_original_currency_debt_matches m
  where ed.expense_id = p_expense_id
    and ed.debtor_participant_id = m.debtor_participant_id
    and ed.creditor_participant_id = m.creditor_participant_id;
end;
$function$;

revoke all on function private.normalize_expense_debt_currency(uuid)
  from public, anon, authenticated;

-- Rebuild all non-deleted activities so existing expense_debts, allocations,
-- prepayment projections, and bilateral rows are regenerated under the fixed
-- original-currency projection. The rebuild order preserves the established
-- transfer/prepayment/final-settlement contracts.
do $backfill$
declare
  v_activity_id uuid;
begin
  for v_activity_id in
    select id
    from public.activities
    where not is_deleted
    order by id
  loop
    perform private.rebuild_activity_debt_projection(v_activity_id);
  end loop;
end;
$backfill$;

commit;
