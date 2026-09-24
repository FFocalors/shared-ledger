begin;

-- The expense-debt rebuild already inserts original_amount from the exact
-- Payment - Split net. Never derive that amount from the separately rounded
-- base debt. The normalizer is retained for older rows and reconstructs the
-- original amount for an existing pair from the same original-unit nets.
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
    raise exception using errcode = 'P0002',
      message = 'expense was not found for currency normalization';
  end if;

  with participant_nets as (
    select
      p.id as participant_id,
      p.participant_order,
      (coalesce(pay.paid, 0) - coalesce(split.owed, 0))::numeric(20,4)
        as net_original
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
  creditor_ranges as (
    select participant_id,
      coalesce(pg_catalog.sum(net_original) over (
        order by participant_order, participant_id
        rows between unbounded preceding and 1 preceding
      ), 0)::numeric(20,4) as range_start,
      pg_catalog.sum(net_original) over (
        order by participant_order, participant_id
        rows between unbounded preceding and current row
      )::numeric(20,4) as range_end
    from participant_nets
    where net_original > 0
  ),
  debtor_ranges as (
    select participant_id,
      coalesce(pg_catalog.sum(-net_original) over (
        order by participant_order, participant_id
        rows between unbounded preceding and 1 preceding
      ), 0)::numeric(20,4) as range_start,
      pg_catalog.sum(-net_original) over (
        order by participant_order, participant_id
        rows between unbounded preceding and current row
      )::numeric(20,4) as range_end
    from participant_nets
    where net_original < 0
  ),
  original_pairs as (
    select d.participant_id as debtor_participant_id,
      c.participant_id as creditor_participant_id,
      (least(c.range_end, d.range_end)
        - greatest(c.range_start, d.range_start))::numeric(20,4)
        as original_amount
    from debtor_ranges d
    cross join creditor_ranges c
    where least(c.range_end, d.range_end)
      > greatest(c.range_start, d.range_start)
  )
  update public.expense_debts ed
  set original_amount = pair.original_amount,
      original_currency = v_original_currency,
      fx_rate = v_fx_rate
  from original_pairs pair
  where ed.expense_id = p_expense_id
    and ed.debtor_participant_id = pair.debtor_participant_id
    and ed.creditor_participant_id = pair.creditor_participant_id
    and (ed.original_amount is distinct from pair.original_amount
      or ed.original_currency is distinct from v_original_currency
      or ed.fx_rate is distinct from v_fx_rate);
end;
$function$;

revoke all on function private.normalize_expense_debt_currency(uuid)
  from public, anon, authenticated;

-- At the same FX snapshot, reverse-debt cancellation consumes the reverse
-- source rows' persisted base values, including AA tails. Across different
-- snapshots, retain the forward debt's FX valuation of cancelled original
-- units so a later reverse bill cannot revalue an older debt.
create or replace function private.rebuild_bilateral_debts_locked(p_activity_id uuid)
returns void language plpgsql volatile security definer set search_path = ''
as $function$
begin
  delete from public.bilateral_debts where activity_id=p_activity_id;
  insert into public.bilateral_debts(
    activity_id,debtor_participant_id,creditor_participant_id,amount,
    original_amount,currency,base_amount
  )
  with raw as (
    select ed.id expense_debt_id,ed.expense_id,ed.activity_id,
      ed.debtor_participant_id,ed.creditor_participant_id,
      coalesce(ed.original_currency,a.base_currency)::character(3) currency,
      coalesce(ed.original_amount,ed.amount)::numeric(20,4) gross_original,
      ed.amount::numeric(20,1) gross_base,
      coalesce(ed.fx_rate,1)::numeric(20,10) fx_rate,
      e.occurred_at,e.created_at,e.id expense_order
    from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
    join public.ledger_units lu on lu.id=e.ledger_unit_id
    join public.activities a on a.id=lu.activity_id
    where ed.activity_id=p_activity_id and not e.is_deleted and not lu.is_deleted
  ), paid as (
    select r.*,
      greatest(r.gross_original
        -coalesce((select sum(coalesce(ta.original_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=r.expense_debt_id),0)
        -coalesce((select sum(coalesce(f.original_amount,f.amount)) from public.final_settlement_paths f join public.transfers t on t.id=f.transfer_id
          where f.activity_id=p_activity_id and f.component_type='settlement' and not t.is_voided
            and f.from_participant_id=r.debtor_participant_id and f.to_participant_id=r.creditor_participant_id
            and (f.source_expense_debt_id=r.expense_debt_id or (f.source_expense_debt_id is null and f.source_expense_id=r.expense_id))),0),0)::numeric(20,4) unpaid_original,
      greatest(r.gross_base
        -coalesce((select sum(coalesce(ta.base_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=r.expense_debt_id),0)
        -coalesce((select sum(coalesce(f.base_amount,f.amount)) from public.final_settlement_paths f join public.transfers t on t.id=f.transfer_id
          where f.activity_id=p_activity_id and f.component_type='settlement' and not t.is_voided
            and f.from_participant_id=r.debtor_participant_id and f.to_participant_id=r.creditor_participant_id
            and (f.source_expense_debt_id=r.expense_debt_id or (f.source_expense_debt_id is null and f.source_expense_id=r.expense_id))),0),0)::numeric(20,1) unpaid_base
    from raw r
  ), dir as (
    select r.*,coalesce(sum(r.unpaid_original) over (
      partition by r.debtor_participant_id,r.creditor_participant_id,r.currency
      order by r.occurred_at,r.created_at,r.expense_order,r.expense_debt_id
      rows between unbounded preceding and 1 preceding),0) prior_original,
      coalesce((select sum(x.unpaid_original) from paid x where
        x.debtor_participant_id=r.creditor_participant_id and x.creditor_participant_id=r.debtor_participant_id
        and x.currency=r.currency),0) reverse_original
    from paid r
  ), original_offsets as (
    select d.*,
      least(d.unpaid_original,greatest(d.reverse_original-d.prior_original,0))::numeric(20,4) offset_original
    from dir d
  ), offsets as (
    select d.*,
      case when exists (
        select 1 from dir r
        where r.debtor_participant_id=d.creditor_participant_id
          and r.creditor_participant_id=d.debtor_participant_id
          and r.currency=d.currency and r.unpaid_original>0
          and r.fx_rate is distinct from d.fx_rate
          and least(d.prior_original+d.unpaid_original,r.prior_original+r.unpaid_original)
            > greatest(d.prior_original,r.prior_original)
      ) then pg_catalog.round(d.offset_original*d.fx_rate,1)
      else coalesce((
        select sum(
          pg_catalog.round(r.unpaid_base *
            (least(d.prior_original+d.unpaid_original,r.prior_original+r.unpaid_original)
              -r.prior_original)/r.unpaid_original,1)
          -pg_catalog.round(r.unpaid_base *
            (greatest(d.prior_original,r.prior_original)-r.prior_original)
              /r.unpaid_original,1)
        )
        from dir r
        where r.debtor_participant_id=d.creditor_participant_id
          and r.creditor_participant_id=d.debtor_participant_id
          and r.currency=d.currency and r.unpaid_original>0
          and least(d.prior_original+d.unpaid_original,r.prior_original+r.unpaid_original)
            > greatest(d.prior_original,r.prior_original)
      ),0) end::numeric(20,1) offset_base
    from original_offsets d
  ), debt_rows as (
    select d.*,
      greatest(d.unpaid_original-d.offset_original
        -coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu where pu.expense_debt_id=d.expense_debt_id),0)
        ,0)::numeric(20,4) original_residual,
      case when d.unpaid_original-d.offset_original
        -coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu where pu.expense_debt_id=d.expense_debt_id),0) <= 0
        then 0::numeric(20,1)
        else greatest(d.unpaid_base-d.offset_base
          -coalesce((select sum(pu.base_amount) from public.prepayment_usages pu where pu.expense_debt_id=d.expense_debt_id),0)
          ,0)::numeric(20,1) end base_residual
    from offsets d
  ), grouped as (
    select activity_id,least(debtor_participant_id,creditor_participant_id) low_id,
      greatest(debtor_participant_id,creditor_participant_id) high_id,currency,
      sum(case when debtor_participant_id<creditor_participant_id then original_residual else -original_residual end) signed_original,
      sum(case when debtor_participant_id<creditor_participant_id then base_residual else -base_residual end) signed_base
    from debt_rows group by activity_id,least(debtor_participant_id,creditor_participant_id),greatest(debtor_participant_id,creditor_participant_id),currency
  )
  select g.activity_id,
    case when g.signed_original>0 then g.low_id else g.high_id end,
    case when g.signed_original>0 then g.high_id else g.low_id end,
    greatest(abs(g.signed_base),0)::numeric(20,1),abs(g.signed_original)::numeric(20,4),g.currency,
    greatest(abs(g.signed_base),0)::numeric(20,1)
  from grouped g where g.signed_original>0 or g.signed_original<0;
end;
$function$;

-- Regenerate existing unlocked expense projections through the established
-- rebuild path. Financially locked rows and archived activities remain
-- historical snapshots; neither is edited by this backfill.
do $backfill$
declare
  v_activity_id uuid;
begin
  for v_activity_id in
    select distinct lu.activity_id
    from public.expenses e
    join public.ledger_units lu on lu.id = e.ledger_unit_id
    join public.activities a on a.id = lu.activity_id
    where not a.is_deleted and a.archived_at is null
      and not lu.is_deleted and not e.is_deleted
      and not e.financial_locked
    order by lu.activity_id
  loop
    perform private.rebuild_activity_debt_projection(v_activity_id);
  end loop;
end;
$backfill$;

commit;
