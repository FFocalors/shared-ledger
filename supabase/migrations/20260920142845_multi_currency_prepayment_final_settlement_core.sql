begin;

-- Multi-currency prepayments and final settlement share the existing immutable
-- transfer facts.  This migration widens projection amounts (external
-- currencies retain four decimal places) and records the currency/FX facts
-- used when a projection row is rebuilt.
alter table public.transfer_components
  alter column amount type numeric(20,4);
alter table public.transfers
  alter column amount type numeric(20,4);
alter table public.transfer_allocations
  alter column amount type numeric(20,4);
alter table public.transfer_allocations
  alter column original_amount type numeric(20,4);
alter table public.transfer_allocations
  alter column base_amount type numeric(20,1);
-- PostgreSQL cannot change a column type while a view's rule depends on it.
-- Recreate the two security-invoker status views after widening balances.
drop view if exists public.participant_financial_status;
drop view if exists public.activity_financial_status;
alter table public.prepayment_accounts
  add column if not exists currency character(3);
alter table public.prepayment_accounts
  alter column balance type numeric(20,4);
alter table public.prepayment_accounts
  add constraint prepayment_accounts_currency_valid
  check (currency ~ '^[A-Z]{3}$');
update public.prepayment_accounts pa
set currency = a.base_currency
from public.activities a
where pa.activity_id = a.id and pa.currency is null;
alter table public.prepayment_accounts alter column currency set not null;
alter table public.prepayment_accounts
  drop constraint if exists prepayment_accounts_activity_id_owner_participant_id_custodian_participant_id_key;
create unique index if not exists prepayment_accounts_activity_owner_custodian_currency_key
  on public.prepayment_accounts(activity_id, owner_participant_id, custodian_participant_id, currency);

alter table public.prepayment_usages
  alter column gross_amount type numeric(20,4),
  alter column amount type numeric(20,4);
alter table public.prepayment_usages
  add column if not exists prepayment_currency character(3),
  add column if not exists prepayment_amount numeric(20,4),
  add column if not exists debt_currency character(3),
  add column if not exists debt_amount numeric(20,4),
  add column if not exists base_amount numeric(20,1),
  add column if not exists bill_fx_rate numeric(20,10),
  add column if not exists bill_occurred_at timestamptz;
update public.prepayment_usages pu
set prepayment_currency = coalesce(pa.currency, a.base_currency),
    prepayment_amount = pu.amount,
    debt_currency = coalesce(ed.original_currency, a.base_currency),
    debt_amount = coalesce(ed.original_amount, ed.amount),
    base_amount = pu.amount,
    bill_fx_rate = coalesce(ed.fx_rate, 1),
    bill_occurred_at = e.occurred_at
from public.prepayment_accounts pa
join public.activities a on a.id = pa.activity_id,
     public.expense_debts ed,
     public.expenses e
where pu.account_id = pa.id and ed.id = pu.expense_debt_id and e.id = ed.expense_id;
alter table public.prepayment_usages
  alter column prepayment_currency set not null,
  alter column prepayment_amount set not null,
  alter column debt_currency set not null,
  alter column debt_amount set not null,
  alter column base_amount set not null,
  alter column bill_fx_rate set not null,
  alter column bill_occurred_at set not null;
alter table public.prepayment_usages
  add constraint prepayment_usages_currency_valid
  check (prepayment_currency ~ '^[A-Z]{3}$' and debt_currency ~ '^[A-Z]{3}$'),
  add constraint prepayment_usages_audit_amounts_positive
  check (prepayment_amount > 0 and debt_amount > 0 and base_amount > 0 and bill_fx_rate > 0);
create index if not exists prepayment_usages_activity_currency_fifo_idx
  on public.prepayment_usages(activity_id, prepayment_currency, bill_occurred_at, expense_debt_id);

create or replace view public.activity_financial_status
with (security_invoker = true) as
select a.id as activity_id,a.type,a.financial_version,a.archived_at,
  case when coalesce(d.total_debt,0)=0 and coalesce(p.total_prepayment,0)=0 then 'completed' else 'active' end financial_status,
  (coalesce(d.total_debt,0)=0 and coalesce(p.total_prepayment,0)=0) completed,
  coalesce(d.total_debt,0)::numeric(20,1) total_debt,
  coalesce(p.total_prepayment,0)::numeric(20,4) total_prepayment
from public.activities a
left join (select activity_id,sum(amount)::numeric(20,1) total_debt from public.bilateral_debts group by activity_id) d on d.activity_id=a.id
left join (select activity_id,sum(balance)::numeric(20,4) total_prepayment from public.prepayment_accounts group by activity_id) p on p.activity_id=a.id
where not a.is_deleted;
create or replace view public.participant_financial_status
with (security_invoker = true) as
with debt as (select p.activity_id,p.id participant_id,coalesce(sum(case when b.creditor_participant_id=p.id then b.amount else 0 end),0)::numeric(20,1) receivable,coalesce(sum(case when b.debtor_participant_id=p.id then b.amount else 0 end),0)::numeric(20,1) payable from public.participants p left join public.bilateral_debts b on b.activity_id=p.activity_id and (b.creditor_participant_id=p.id or b.debtor_participant_id=p.id) where not p.is_deleted group by p.activity_id,p.id), prepayment as (select activity_id,owner_participant_id participant_id,coalesce(sum(balance),0)::numeric(20,4) receivable,0::numeric(20,4) payable from public.prepayment_accounts group by activity_id,owner_participant_id union all select activity_id,custodian_participant_id,0::numeric(20,4),coalesce(sum(balance),0)::numeric(20,4) from public.prepayment_accounts group by activity_id,custodian_participant_id), all_balances as (select * from debt union all select * from prepayment), totals as (select activity_id,participant_id,sum(receivable)::numeric(20,4) receivable,sum(payable)::numeric(20,4) payable from all_balances group by activity_id,participant_id)
select p.activity_id,p.id participant_id,p.participant_order,coalesce(t.receivable,0)::numeric(20,4) receivable,coalesce(t.payable,0)::numeric(20,4) payable,(coalesce(t.receivable,0)-coalesce(t.payable,0))::numeric(20,4) net_balance,case when coalesce(t.receivable,0)=0 and coalesce(t.payable,0)=0 then 'completed' else 'active' end financial_status,(coalesce(t.receivable,0)=0 and coalesce(t.payable,0)=0) completed
from public.participants p left join totals t on t.activity_id=p.activity_id and t.participant_id=p.id where not p.is_deleted;
revoke all on public.activity_financial_status,public.participant_financial_status from public,anon,authenticated;
grant select on public.activity_financial_status,public.participant_financial_status to authenticated;

alter table public.transfers
  add column if not exists request_payload jsonb,
  add column if not exists request_result jsonb;
create index if not exists transfers_activity_request_id_idx
  on public.transfers(activity_id, request_id)
  where request_id is not null;

alter table public.final_settlement_paths
  alter column amount type numeric(20,4);
alter table public.final_settlement_paths
  add column if not exists mode text,
  add column if not exists path_currency character(3),
  add column if not exists source_expense_debt_id uuid,
  add column if not exists original_amount numeric(20,4),
  add column if not exists base_amount numeric(20,1),
  add column if not exists fx_rate numeric(20,10);
update public.final_settlement_paths f
set mode = 'base_unified', path_currency = coalesce(t.currency, a.base_currency),
    original_amount = f.amount, base_amount = f.amount,
    fx_rate = 1
from public.transfers t
join public.activities a on a.id = t.activity_id
where f.transfer_id = t.id and (f.mode is null or f.path_currency is null);
alter table public.final_settlement_paths
  alter column mode set default 'base_unified',
  alter column mode set not null,
  alter column path_currency drop not null,
  alter column original_amount drop not null,
  alter column base_amount drop not null,
  alter column fx_rate drop not null;
alter table public.final_settlement_paths
  add constraint final_settlement_paths_mode_valid
  check (mode in ('base_unified','original_currency')),
  add constraint final_settlement_paths_currency_valid
  check (path_currency ~ '^[A-Z]{3}$' and fx_rate > 0 and original_amount > 0 and base_amount > 0);

-- Ordinary settlement allocation is currency-aware.  A base-currency payment
-- consumes the global bill-time FIFO (using each bill's immutable FX
-- snapshot); an external-currency payment consumes only that currency's FIFO.
create or replace function private.rebuild_transfer_allocations_locked(p_activity_id uuid)
returns void language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_transfer record;
  v_debt record;
  v_base_currency character(3);
  v_remaining numeric(20,4);
  v_allocate_original numeric(20,4);
  v_allocate_base numeric(20,1);
begin
  select a.base_currency into v_base_currency
  from public.activities a where a.id = p_activity_id;
  delete from public.transfer_allocations where activity_id = p_activity_id;

  for v_transfer in
    select t.id, t.from_participant_id, t.to_participant_id, t.currency,
           c.id component_id, c.amount component_amount
    from public.transfers t
    join public.transfer_components c
      on c.transfer_id = t.id and c.activity_id = t.activity_id
    where t.activity_id = p_activity_id and not t.is_voided
      and t.type <> 'final_settlement'::public.transfer_type
      and c.component_type = 'settlement'
    order by t.occurred_at, t.created_at, t.id
  loop
    v_remaining := v_transfer.component_amount;
    for v_debt in
      with raw as (
        select ed.id, ed.amount debt_base,
               coalesce(ed.original_amount, ed.amount)::numeric(20,4) debt_original,
               coalesce(ed.original_currency, v_base_currency)::character(3) debt_currency,
               coalesce(ed.fx_rate,1)::numeric(20,10) debt_fx,
               e.occurred_at, e.created_at, e.id expense_id,
               coalesce(sum(coalesce(ed.original_amount,ed.amount)) over (
                 partition by ed.debtor_participant_id,ed.creditor_participant_id,
                   coalesce(ed.original_currency,v_base_currency)
                 order by e.occurred_at,e.created_at,e.id,ed.id
                 rows between unbounded preceding and 1 preceding),0) prior_original,
               coalesce((select sum(coalesce(x.original_amount,x.amount))
                 from public.expense_debts x
                 where x.activity_id=p_activity_id
                   and x.debtor_participant_id=v_transfer.to_participant_id
                   and x.creditor_participant_id=v_transfer.from_participant_id
                   and coalesce(x.original_currency,v_base_currency)=coalesce(ed.original_currency,v_base_currency)),0) reverse_original
        from public.expense_debts ed
        join public.expenses e on e.id=ed.expense_id
        where ed.activity_id=p_activity_id
          and ed.debtor_participant_id=v_transfer.from_participant_id
          and ed.creditor_participant_id=v_transfer.to_participant_id
          and not e.is_deleted
      ), residual as (
        select r.*,
          least(r.debt_original,greatest(r.reverse_original-r.prior_original,0)) cancelled_original
        from raw r
      )
      select r.*,
        greatest(r.debt_original-r.cancelled_original
          - coalesce((select sum(coalesce(ta.original_amount,ta.amount))
              from public.transfer_allocations ta where ta.expense_debt_id=r.id),0)
          - coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu
              where pu.expense_debt_id=r.id),0),0)::numeric(20,4) available_original,
        greatest(r.debt_base-pg_catalog.round(r.cancelled_original*r.debt_fx,1)
          - coalesce((select sum(coalesce(ta.base_amount,ta.amount))
              from public.transfer_allocations ta where ta.expense_debt_id=r.id),0)
          - coalesce((select sum(pu.base_amount) from public.prepayment_usages pu
              where pu.expense_debt_id=r.id),0),0)::numeric(20,1) available_base
      from residual r
      where v_transfer.currency=v_base_currency or r.debt_currency=v_transfer.currency
      order by r.occurred_at,r.created_at,r.expense_id,r.id
    loop
      exit when v_remaining <= 0;
      if v_transfer.currency = v_base_currency then
        if v_debt.available_base <= 0 then continue; end if;
        v_allocate_base := least(v_remaining,v_debt.available_base)::numeric(20,1);
        v_allocate_original := least(v_debt.available_original,
          pg_catalog.round(v_allocate_base/nullif(v_debt.debt_fx,0),4))::numeric(20,4);
        if v_allocate_original <= 0 then continue; end if;
      else
        if v_debt.available_original <= 0 then continue; end if;
        v_allocate_original := least(v_remaining,v_debt.available_original)::numeric(20,4);
        v_allocate_base := pg_catalog.round(v_allocate_original*v_debt.debt_fx,1)::numeric(20,1);
        if v_allocate_base <= 0 then continue; end if;
      end if;
      insert into public.transfer_allocations(
        activity_id,transfer_id,settlement_component_id,expense_debt_id,
        amount,original_amount,base_amount
      ) values (
        p_activity_id,v_transfer.id,v_transfer.component_id,v_debt.id,
        v_allocate_base,v_allocate_original,v_allocate_base
      );
      v_remaining := v_remaining - case when v_transfer.currency=v_base_currency
        then v_allocate_base else v_allocate_original end;
    end loop;
    if v_remaining > 0 then
      raise exception using errcode='23514', message=pg_catalog.format(
        'settlement transfer %s has %s unallocated %s',v_transfer.id,v_remaining,v_transfer.currency);
    end if;
  end loop;
end;
$function$;

-- Rebuild the prepayment projection from immutable funding/return facts.  The
-- account currency is part of the identity.  Base-currency accounts can pay
-- any debt bucket in bill-time FIFO; external accounts can pay only the same
-- original currency bucket.
create or replace function private.rebuild_prepayment_projections_locked(p_activity_id uuid)
returns void language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_base_currency character(3);
  v_account record;
  v_debt record;
  v_account_id uuid;
  v_left numeric(20,4);
  v_take_original numeric(20,4);
  v_take_base numeric(20,1);
  v_funded numeric(20,4);
  v_take numeric(20,4);
  v_pre_take numeric(20,4);
begin
  select a.base_currency into v_base_currency from public.activities a where a.id=p_activity_id;
  delete from public.prepayment_usages where activity_id=p_activity_id;
  delete from public.prepayment_accounts where activity_id=p_activity_id;

  for v_account in
    with facts as (
      select t.from_participant_id owner_participant_id,t.to_participant_id custodian_participant_id,
             t.currency, c.amount delta
      from public.transfers t join public.transfer_components c on c.transfer_id=t.id
      where t.activity_id=p_activity_id and not t.is_voided and c.component_type='prepayment'
      union all
      select t.to_participant_id,t.from_participant_id,t.currency,-c.amount
      from public.transfers t join public.transfer_components c on c.transfer_id=t.id
      where t.activity_id=p_activity_id and not t.is_voided and c.component_type='prepayment_return'
    )
    select owner_participant_id,custodian_participant_id,currency,
           sum(delta)::numeric(20,4) funded
    from facts group by owner_participant_id,custodian_participant_id,currency
    having sum(delta) >= 0
    order by owner_participant_id,custodian_participant_id,currency
  loop
    v_funded := v_account.funded;
    insert into public.prepayment_accounts(
      activity_id,owner_participant_id,custodian_participant_id,currency,balance
    ) values (
      p_activity_id,v_account.owner_participant_id,v_account.custodian_participant_id,
      v_account.currency,v_funded
    ) returning id into v_account_id;
    v_left := v_funded;
    for v_debt in
      select ed.id, ed.amount debt_base,
        coalesce(ed.original_amount,ed.amount)::numeric(20,4) debt_original,
        coalesce(ed.original_currency,v_base_currency)::character(3) debt_currency,
        coalesce(ed.fx_rate,1)::numeric(20,10) debt_fx,
        e.occurred_at,e.created_at,e.id expense_id,
        greatest(coalesce(ed.original_amount,ed.amount)-coalesce((select sum(coalesce(ta.original_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=ed.id),0),0)::numeric(20,4) available_original,
        greatest(ed.amount-coalesce((select sum(coalesce(ta.base_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=ed.id),0),0)::numeric(20,1) available_base
      from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
      where ed.activity_id=p_activity_id
        and ed.debtor_participant_id=v_account.owner_participant_id
        and ed.creditor_participant_id=v_account.custodian_participant_id
        and not e.is_deleted
        and (v_account.currency=v_base_currency or coalesce(ed.original_currency,v_base_currency)=v_account.currency)
      order by e.occurred_at,e.created_at,e.id,ed.id
    loop
      exit when v_left <= 0;
      if v_account.currency=v_base_currency then
        if v_debt.available_base <= 0 then continue; end if;
        v_take_base := least(v_left,v_debt.available_base)::numeric(20,1);
        v_take_original := case when v_debt.debt_currency=v_base_currency
          then v_take_base
          else pg_catalog.round(v_take_base/nullif(v_debt.debt_fx,0),4) end;
        if v_take_original <= 0 then continue; end if;
      else
        if v_debt.debt_currency<>v_account.currency or v_debt.available_original<=0 then continue; end if;
        v_take_original := least(v_left,v_debt.available_original)::numeric(20,4);
        v_take_base := pg_catalog.round(v_take_original*v_debt.debt_fx,1)::numeric(20,1);
        if v_take_base<=0 then continue; end if;
      end if;
      insert into public.prepayment_usages(
        activity_id,account_id,expense_debt_id,gross_amount,amount,
        prepayment_currency,prepayment_amount,debt_currency,debt_amount,
        base_amount,bill_fx_rate,bill_occurred_at
      ) values (
        p_activity_id,v_account_id,v_debt.id,v_take_original,v_take_original,
        v_account.currency,case when v_account.currency=v_base_currency then v_take_base else v_take_original end,
        v_debt.debt_currency,v_take_original,
        v_take_base,v_debt.debt_fx,v_debt.occurred_at
      );
      v_left := v_left - case when v_account.currency=v_base_currency then v_take_base else v_take_original end;
    end loop;
    update public.prepayment_accounts set balance = greatest(
      v_funded - coalesce((select sum(pu.prepayment_amount) from public.prepayment_usages pu
        where pu.account_id=v_account_id),0),0), updated_at=pg_catalog.now()
    where id=v_account_id;
  end loop;
  -- Linked refunds cancel only usage tied to their original expense.  Excess
  -- refund value remains an ordinary reverse debt after this projection.
  for v_debt in
    select rf.original_expense_id,s.participant_id owner_participant_id,abs(s.base_amount)::numeric(20,1) benefit
    from public.expenses rf join public.splits s on s.expense_id=rf.id
    where rf.original_expense_id is not null and rf.base_amount<0 and not rf.is_deleted and s.base_amount<0
    order by rf.occurred_at,rf.created_at,rf.id,s.participant_id
  loop
    v_left:=v_debt.benefit;
    for v_account in
      select pu.id usage_id,pu.amount,pu.prepayment_amount,pu.debt_amount,pu.base_amount,pu.bill_fx_rate,pu.prepayment_currency
      from public.prepayment_usages pu join public.prepayment_accounts pa on pa.id=pu.account_id
      join public.expense_debts ed on ed.id=pu.expense_debt_id
      where pa.activity_id=p_activity_id and pa.owner_participant_id=v_debt.owner_participant_id and ed.expense_id=v_debt.original_expense_id
      order by pu.bill_occurred_at,pu.expense_debt_id,pu.id
    loop
      exit when v_left<=0;
      v_take:=least(v_left,v_account.base_amount)::numeric(20,1);
      v_pre_take:=case when v_account.prepayment_currency=v_base_currency
        then v_take else pg_catalog.round(v_take/nullif(v_account.bill_fx_rate,0),4) end;
      if v_take>=v_account.base_amount then
        delete from public.prepayment_usages where id=v_account.usage_id;
      else
        update public.prepayment_usages set
          amount=amount-pg_catalog.round(v_take/nullif(bill_fx_rate,0),4),
          prepayment_amount=prepayment_amount-v_pre_take,
          debt_amount=debt_amount-pg_catalog.round(v_take/nullif(bill_fx_rate,0),4),
          base_amount=base_amount-v_take
        where id=v_account.usage_id;
      end if;
      v_left:=v_left-v_take;
    end loop;
  end loop;
  update public.prepayment_accounts pa set balance=greatest(
    coalesce((select sum(c.amount) from (
      select t.from_participant_id owner,t.to_participant_id cust,t.currency,tc.amount
      from public.transfers t join public.transfer_components tc on tc.transfer_id=t.id
      where t.activity_id=p_activity_id and not t.is_voided and tc.component_type='prepayment'
      union all select t.to_participant_id,t.from_participant_id,t.currency,-tc.amount
      from public.transfers t join public.transfer_components tc on tc.transfer_id=t.id
      where t.activity_id=p_activity_id and not t.is_voided and tc.component_type='prepayment_return'
    ) c where c.owner=pa.owner_participant_id and c.cust=pa.custodian_participant_id and c.currency=pa.currency),0)
    -coalesce((select sum(pu.prepayment_amount) from public.prepayment_usages pu where pu.account_id=pa.id),0),0), updated_at=pg_catalog.now()
  where pa.activity_id=p_activity_id;
end;
$function$;

-- Bilateral debt is a rebuildable view of debt facts, ordinary allocations,
-- prepayment usage, and final-settlement path consumption.  It keeps both
-- original and base values so no FX average is ever introduced.
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
  ), dir as (
    select r.*,coalesce(sum(r.gross_original) over (
      partition by r.debtor_participant_id,r.creditor_participant_id,r.currency
      order by r.occurred_at,r.created_at,r.expense_order,r.expense_debt_id
      rows between unbounded preceding and 1 preceding),0) prior_original,
      coalesce((select sum(x.gross_original) from raw x where
        x.debtor_participant_id=r.creditor_participant_id and x.creditor_participant_id=r.debtor_participant_id
        and x.currency=r.currency),0) reverse_original
    from raw r
  ), debt_rows as (
    select d.*,
      greatest(d.gross_original-least(d.gross_original,greatest(d.reverse_original-d.prior_original,0))
        -coalesce((select sum(coalesce(ta.original_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=d.expense_debt_id),0)
        -coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu where pu.expense_debt_id=d.expense_debt_id),0)
        -coalesce((select sum(coalesce(f.original_amount,f.amount)) from public.final_settlement_paths f join public.transfers t on t.id=f.transfer_id
          where f.activity_id=p_activity_id and f.source_expense_id=d.expense_id and f.component_type='settlement' and not t.is_voided
            and f.from_participant_id=d.debtor_participant_id and f.to_participant_id=d.creditor_participant_id),0),0)::numeric(20,4) original_residual,
      greatest(d.gross_base-pg_catalog.round(least(d.gross_original,greatest(d.reverse_original-d.prior_original,0))*d.fx_rate,1)
        -coalesce((select sum(coalesce(ta.base_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=d.expense_debt_id),0)
        -coalesce((select sum(pu.base_amount) from public.prepayment_usages pu where pu.expense_debt_id=d.expense_debt_id),0)
        -coalesce((select sum(coalesce(f.base_amount,f.amount)) from public.final_settlement_paths f join public.transfers t on t.id=f.transfer_id
          where f.activity_id=p_activity_id and f.source_expense_id=d.expense_id and f.component_type='settlement' and not t.is_voided
            and f.from_participant_id=d.debtor_participant_id and f.to_participant_id=d.creditor_participant_id),0),0)::numeric(20,1) base_residual
    from dir d
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

create or replace function private.phase5_rebuild_after_transfer(aid uuid)
returns void language plpgsql volatile security definer set search_path = ''
as $function$
begin
  perform private.rebuild_transfer_allocations_locked(aid);
  perform private.rebuild_prepayment_projections_locked(aid);
  perform private.rebuild_bilateral_debts_locked(aid);
end;
$function$;

-- The existing flow decomposer is retained as the deterministic base-unified
-- optimizer, but normal activities are now eligible as well as large roots.
create or replace function private.build_final_settlement_flow(p_activity_id uuid)
returns table(path_no integer, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,1), hops jsonb)
language plpgsql stable security definer set search_path = ''
as $function$
declare
  v_edge_from uuid[] := '{}'; v_edge_to uuid[] := '{}'; v_edge_remaining numeric[] := '{}'; v_edge_count integer := 0;
  v_sources uuid[] := '{}'; v_source_remaining numeric[] := '{}'; v_creditors uuid[] := '{}'; v_creditor_remaining numeric[] := '{}';
  v_queue_i integer; v_source_left numeric; v_match numeric; v_hop_no integer; v_path_no integer:=0;
  v_node uuid; v_target uuid; v_current_path jsonb; v_found_path jsonb; v_hops jsonb;
  v_queue_nodes uuid[]; v_queue_paths jsonb[]; v_visited uuid[]; v_rec record; v_edge_path_i integer; v_edge_path_text text;
begin
  if (select auth.uid()) is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=(select auth.uid())) then
    raise exception using errcode='42501',message='caller is not an activity member'; end if;
  if not exists(select 1 from public.activities a where a.id=p_activity_id and not a.is_deleted) then
    raise exception using errcode='P0002',message='activity was not found'; end if;
  for v_rec in select b.debtor_participant_id,b.creditor_participant_id,sum(coalesce(b.base_amount,b.amount))::numeric(20,1) amount
    from public.bilateral_debts b where b.activity_id=p_activity_id and coalesce(b.original_amount,b.amount)>0
    group by b.debtor_participant_id,b.creditor_participant_id order by b.debtor_participant_id,b.creditor_participant_id loop
    v_edge_count:=v_edge_count+1; v_edge_from:=array_append(v_edge_from,v_rec.debtor_participant_id); v_edge_to:=array_append(v_edge_to,v_rec.creditor_participant_id); v_edge_remaining:=array_append(v_edge_remaining,v_rec.amount);
  end loop;
  for v_rec in
    with edges as (select b.debtor_participant_id,b.creditor_participant_id,sum(coalesce(b.base_amount,b.amount)) amount from public.bilateral_debts b where b.activity_id=p_activity_id group by b.debtor_participant_id,b.creditor_participant_id)
    select p.id,sum(case when e.creditor_participant_id=p.id then e.amount else -e.amount end)::numeric(20,1) net_amount
    from public.participants p join edges e on e.debtor_participant_id=p.id or e.creditor_participant_id=p.id where p.activity_id=p_activity_id and not p.is_deleted
    group by p.id,p.participant_order having sum(case when e.creditor_participant_id=p.id then e.amount else -e.amount end)<0 order by p.participant_order,p.id loop
    v_sources:=array_append(v_sources,v_rec.id); v_source_remaining:=array_append(v_source_remaining,abs(v_rec.net_amount));
  end loop;
  for v_rec in
    with edges as (select b.debtor_participant_id,b.creditor_participant_id,sum(coalesce(b.base_amount,b.amount)) amount from public.bilateral_debts b where b.activity_id=p_activity_id group by b.debtor_participant_id,b.creditor_participant_id)
    select p.id,sum(case when e.creditor_participant_id=p.id then e.amount else -e.amount end)::numeric(20,1) net_amount
    from public.participants p join edges e on e.debtor_participant_id=p.id or e.creditor_participant_id=p.id where p.activity_id=p_activity_id and not p.is_deleted
    group by p.id,p.participant_order having sum(case when e.creditor_participant_id=p.id then e.amount else -e.amount end)>0 order by p.participant_order,p.id loop
    v_creditors:=array_append(v_creditors,v_rec.id); v_creditor_remaining:=array_append(v_creditor_remaining,v_rec.net_amount);
  end loop;
  for v_source_i in 1..coalesce(array_length(v_sources,1),0) loop
    v_source_left:=v_source_remaining[v_source_i];
    while v_source_left>0 loop
      v_queue_nodes:=array[v_sources[v_source_i]]; v_queue_paths:=array['[]'::jsonb]; v_visited:=array[v_sources[v_source_i]]; v_queue_i:=1; v_target:=null; v_found_path:=null;
      while v_queue_i<=coalesce(array_length(v_queue_nodes,1),0) loop
        v_node:=v_queue_nodes[v_queue_i]; v_current_path:=v_queue_paths[v_queue_i]; v_queue_i:=v_queue_i+1;
        for v_creditor_i in 1..coalesce(array_length(v_creditors,1),0) loop
          if v_creditors[v_creditor_i]=v_node and v_creditor_remaining[v_creditor_i]>0 and jsonb_array_length(v_current_path)>0 then v_target:=v_node; v_found_path:=v_current_path; exit; end if;
        end loop;
        exit when v_target is not null;
        for v_edge_i in 1..v_edge_count loop
          if v_edge_from[v_edge_i]=v_node and v_edge_remaining[v_edge_i]>0 and not(v_edge_to[v_edge_i]=any(v_visited)) then
            v_visited:=array_append(v_visited,v_edge_to[v_edge_i]); v_queue_nodes:=array_append(v_queue_nodes,v_edge_to[v_edge_i]); v_queue_paths:=array_append(v_queue_paths,v_current_path||to_jsonb(v_edge_i));
          end if;
        end loop;
      end loop;
      if v_target is null then raise exception using errcode='P0001',message='final settlement flow cannot decompose directed debt graph'; end if;
      v_match:=v_source_left;
      for v_edge_path_text in select jsonb_array_elements_text(v_found_path) loop v_edge_path_i:=v_edge_path_text::integer; v_match:=least(v_match,v_edge_remaining[v_edge_path_i]); end loop;
      for v_creditor_i in 1..coalesce(array_length(v_creditors,1),0) loop if v_creditors[v_creditor_i]=v_target then v_match:=least(v_match,v_creditor_remaining[v_creditor_i]); exit; end if; end loop;
      if v_match<=0 then raise exception using errcode='P0001',message='final settlement flow has zero residual capacity'; end if;
      v_path_no:=v_path_no+1; v_hops:='[]'::jsonb; v_hop_no:=0;
      for v_edge_path_text in select jsonb_array_elements_text(v_found_path) loop v_edge_path_i:=v_edge_path_text::integer; v_hop_no:=v_hop_no+1; v_hops:=v_hops||jsonb_build_array(jsonb_build_object('hop_no',v_hop_no,'from_participant_id',v_edge_from[v_edge_path_i],'to_participant_id',v_edge_to[v_edge_path_i],'amount',v_match)); v_edge_remaining[v_edge_path_i]:=v_edge_remaining[v_edge_path_i]-v_match; end loop;
      v_source_left:=v_source_left-v_match; v_source_remaining[v_source_i]:=v_source_left;
      for v_creditor_i in 1..coalesce(array_length(v_creditors,1),0) loop if v_creditors[v_creditor_i]=v_target then v_creditor_remaining[v_creditor_i]:=v_creditor_remaining[v_creditor_i]-v_match; exit; end if; end loop;
      return query select v_path_no,v_sources[v_source_i],v_target,v_match::numeric(20,1),v_hops;
    end loop;
  end loop;
end;
$function$;

create or replace function private.build_final_settlement_flow_original(
  p_activity_id uuid, p_currency character(3)
)
returns table(path_no integer, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,4), hops jsonb)
language plpgsql stable security definer set search_path = ''
as $function$
declare
  v_edge_from uuid[] := '{}'; v_edge_to uuid[] := '{}'; v_edge_remaining numeric[] := '{}'; v_edge_count integer:=0;
  v_sources uuid[] := '{}'; v_source_remaining numeric[] := '{}'; v_creditors uuid[] := '{}'; v_creditor_remaining numeric[] := '{}';
  v_queue_i integer; v_source_left numeric; v_match numeric; v_hop_no integer; v_path_no integer:=0;
  v_node uuid; v_target uuid; v_current_path jsonb; v_found_path jsonb; v_hops jsonb; v_queue_nodes uuid[]; v_queue_paths jsonb[]; v_visited uuid[];
  v_rec record; v_edge_path_i integer; v_edge_path_text text;
begin
  for v_rec in select b.debtor_participant_id,b.creditor_participant_id,sum(coalesce(b.original_amount,b.amount))::numeric(20,4) amount
    from public.bilateral_debts b where b.activity_id=p_activity_id and b.currency=p_currency and coalesce(b.original_amount,b.amount)>0
    group by b.debtor_participant_id,b.creditor_participant_id order by b.debtor_participant_id,b.creditor_participant_id loop
    v_edge_count:=v_edge_count+1; v_edge_from:=array_append(v_edge_from,v_rec.debtor_participant_id); v_edge_to:=array_append(v_edge_to,v_rec.creditor_participant_id); v_edge_remaining:=array_append(v_edge_remaining,v_rec.amount);
  end loop;
  for v_rec in
    with edges as (select b.debtor_participant_id,b.creditor_participant_id,sum(coalesce(b.original_amount,b.amount)) amount from public.bilateral_debts b where b.activity_id=p_activity_id and b.currency=p_currency group by b.debtor_participant_id,b.creditor_participant_id)
    select p.id,sum(case when e.creditor_participant_id=p.id then e.amount else -e.amount end)::numeric(20,4) net_amount
    from public.participants p join edges e on e.debtor_participant_id=p.id or e.creditor_participant_id=p.id where p.activity_id=p_activity_id and not p.is_deleted
    group by p.id,p.participant_order having sum(case when e.creditor_participant_id=p.id then e.amount else -e.amount end)<0 order by p.participant_order,p.id loop
    v_sources:=array_append(v_sources,v_rec.id); v_source_remaining:=array_append(v_source_remaining,abs(v_rec.net_amount));
  end loop;
  for v_rec in
    with edges as (select b.debtor_participant_id,b.creditor_participant_id,sum(coalesce(b.original_amount,b.amount)) amount from public.bilateral_debts b where b.activity_id=p_activity_id and b.currency=p_currency group by b.debtor_participant_id,b.creditor_participant_id)
    select p.id,sum(case when e.creditor_participant_id=p.id then e.amount else -e.amount end)::numeric(20,4) net_amount
    from public.participants p join edges e on e.debtor_participant_id=p.id or e.creditor_participant_id=p.id where p.activity_id=p_activity_id and not p.is_deleted
    group by p.id,p.participant_order having sum(case when e.creditor_participant_id=p.id then e.amount else -e.amount end)>0 order by p.participant_order,p.id loop
    v_creditors:=array_append(v_creditors,v_rec.id); v_creditor_remaining:=array_append(v_creditor_remaining,v_rec.net_amount);
  end loop;
  for v_source_i in 1..coalesce(array_length(v_sources,1),0) loop
    v_source_left:=v_source_remaining[v_source_i]; while v_source_left>0 loop
      v_queue_nodes:=array[v_sources[v_source_i]]; v_queue_paths:=array['[]'::jsonb]; v_visited:=array[v_sources[v_source_i]]; v_queue_i:=1; v_target:=null; v_found_path:=null;
      while v_queue_i<=coalesce(array_length(v_queue_nodes,1),0) loop
        v_node:=v_queue_nodes[v_queue_i]; v_current_path:=v_queue_paths[v_queue_i]; v_queue_i:=v_queue_i+1;
        for v_creditor_i in 1..coalesce(array_length(v_creditors,1),0) loop if v_creditors[v_creditor_i]=v_node and v_creditor_remaining[v_creditor_i]>0 and jsonb_array_length(v_current_path)>0 then v_target:=v_node; v_found_path:=v_current_path; exit; end if; end loop;
        exit when v_target is not null;
        for v_edge_i in 1..v_edge_count loop if v_edge_from[v_edge_i]=v_node and v_edge_remaining[v_edge_i]>0 and not(v_edge_to[v_edge_i]=any(v_visited)) then v_visited:=array_append(v_visited,v_edge_to[v_edge_i]); v_queue_nodes:=array_append(v_queue_nodes,v_edge_to[v_edge_i]); v_queue_paths:=array_append(v_queue_paths,v_current_path||to_jsonb(v_edge_i)); end if; end loop;
      end loop;
      if v_target is null then raise exception using errcode='P0001',message='original-currency settlement flow cannot be decomposed'; end if;
      v_match:=v_source_left; for v_edge_path_text in select jsonb_array_elements_text(v_found_path) loop v_edge_path_i:=v_edge_path_text::integer; v_match:=least(v_match,v_edge_remaining[v_edge_path_i]); end loop;
      for v_creditor_i in 1..coalesce(array_length(v_creditors,1),0) loop if v_creditors[v_creditor_i]=v_target then v_match:=least(v_match,v_creditor_remaining[v_creditor_i]); exit; end if; end loop;
      v_path_no:=v_path_no+1; v_hops:='[]'::jsonb; v_hop_no:=0;
      for v_edge_path_text in select jsonb_array_elements_text(v_found_path) loop v_edge_path_i:=v_edge_path_text::integer; v_hop_no:=v_hop_no+1; v_hops:=v_hops||jsonb_build_array(jsonb_build_object('hop_no',v_hop_no,'from_participant_id',v_edge_from[v_edge_path_i],'to_participant_id',v_edge_to[v_edge_path_i],'amount',v_match)); v_edge_remaining[v_edge_path_i]:=v_edge_remaining[v_edge_path_i]-v_match; end loop;
      v_source_left:=v_source_left-v_match; v_source_remaining[v_source_i]:=v_source_left;
      for v_creditor_i in 1..coalesce(array_length(v_creditors,1),0) loop if v_creditors[v_creditor_i]=v_target then v_creditor_remaining[v_creditor_i]:=v_creditor_remaining[v_creditor_i]-v_match; exit; end if; end loop;
      return query select v_path_no,v_sources[v_source_i],v_target,v_match::numeric(20,4),v_hops;
    end loop;
  end loop;
end;
$function$;

create or replace function private.build_final_settlement_plan_v2(
  p_activity_id uuid, p_mode text
)
returns table(
  activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,4), ordinary_amount numeric(20,4), prepayment_return_amount numeric(20,4),
  currency character(3), mode text, path_currency character(3),
  source_financial_version bigint, is_prepayment_return boolean
)
language plpgsql stable security definer set search_path = ''
as $function$
declare v_base character(3); v_version bigint; v_mode text:=coalesce(p_mode,'base_unified'); v_uid uuid:=(select auth.uid());
begin
  if v_uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=v_uid) then
    raise exception using errcode='42501',message='caller is not an activity member'; end if;
  if v_mode not in ('base_unified','original_currency') then raise exception using errcode='22023',message='invalid final settlement mode'; end if;
  select a.base_currency,a.financial_version into v_base,v_version from public.activities a where a.id=p_activity_id and not a.is_deleted;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  return query
  with ordinary as (
    select f.from_participant_id,f.to_participant_id,sum(f.amount)::numeric(20,4) amount,v_base::character(3) currency
    from private.build_final_settlement_flow(p_activity_id) f where v_mode='base_unified'
    group by f.from_participant_id,f.to_participant_id
    union all
    select f.from_participant_id,f.to_participant_id,sum(f.amount)::numeric(20,4) amount,currencies.currency
    from (select distinct b.currency from public.bilateral_debts b where b.activity_id=p_activity_id and b.original_amount>0) currencies
    cross join lateral private.build_final_settlement_flow_original(p_activity_id,currencies.currency) f
    where v_mode='original_currency'
    group by f.from_participant_id,f.to_participant_id,currencies.currency
  ), returns as (
    select pa.custodian_participant_id from_id,pa.owner_participant_id to_id,
      pa.balance::numeric(20,4) amount,pa.currency::character(3) currency
    from public.prepayment_accounts pa where pa.activity_id=p_activity_id and pa.balance>0
  ), merged as (
    select coalesce(o.from_participant_id,r.from_id) from_id,coalesce(o.to_participant_id,r.to_id) to_id,
      coalesce(o.amount,0)::numeric(20,4) ordinary_amount,coalesce(r.amount,0)::numeric(20,4) return_amount,
      coalesce(o.currency,r.currency)::character(3) currency
    from ordinary o full join returns r on r.from_id=o.from_participant_id and r.to_id=o.to_participant_id and r.currency=o.currency
  )
  select p_activity_id,m.from_id,m.to_id,(m.ordinary_amount+m.return_amount)::numeric(20,4),m.ordinary_amount,m.return_amount,
    m.currency,v_mode,m.currency,v_version,(m.ordinary_amount=0)
  from merged m where m.ordinary_amount>0 or m.return_amount>0
  order by m.from_id,m.to_id,m.currency;
end;
$function$;

create or replace function public.preview_final_settlement_v2(p_activity_id uuid, p_mode text default 'base_unified')
returns table(activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,4), ordinary_amount numeric(20,4), prepayment_return_amount numeric(20,4),
  currency character(3), mode text, path_currency character(3), source_financial_version bigint,
  is_prepayment_return boolean)
language sql stable security invoker set search_path = '' as $function$
select * from private.build_final_settlement_plan_v2($1,$2);
$function$;

create or replace function public.get_final_settlement_plan_v2(p_activity_id uuid, p_mode text default 'base_unified')
returns table(activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,4), ordinary_amount numeric(20,4), prepayment_return_amount numeric(20,4),
  currency character(3), mode text, path_currency character(3), source_financial_version bigint,
  is_prepayment_return boolean)
language sql stable security invoker set search_path = '' as $function$
select * from private.build_final_settlement_plan_v2($1,$2);
$function$;

create or replace function public.preview_activity_settlement_v2(p_activity_id uuid, p_mode text default 'base_unified')
returns table(activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,4), ordinary_amount numeric(20,4), prepayment_return_amount numeric(20,4),
  currency character(3), mode text, path_currency character(3), source_financial_version bigint,
  is_prepayment_return boolean)
language sql stable security invoker set search_path = '' as $function$
select * from private.build_final_settlement_plan_v2($1,$2);
$function$;

create or replace function private.execute_final_settlement_v2_impl(
  p_activity_id uuid, p_from uuid, p_to uuid, p_amount numeric(20,4), p_currency character(3),
  p_mode text, p_expected_version bigint, p_request_id uuid, p_occurred_at timestamptz, p_behalf uuid
)
returns table(transfer_id uuid, amount numeric(20,4), currency character(3), mode text, financial_version bigint)
language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_user uuid:=(select auth.uid()); v_mode text:=coalesce(p_mode,'base_unified'); v_currency character(3);
  v_base character(3); v_archived timestamptz; v_version bigint; v_plan record; v_transfer uuid;
  v_existing record; v_payload jsonb; v_result jsonb; v_flow record; v_hop record; v_debt record; v_path_order integer:=0; v_path_no integer; v_hop_seq integer; v_source_expense uuid; v_source_debt uuid; v_debt_currency character(3); v_fx numeric(20,10); v_original numeric(20,4); v_base_amount numeric(20,1); v_hop_remaining numeric(20,4); v_take numeric(20,4);
begin
  if v_user is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if p_expected_version is null or p_request_id is null then raise exception using errcode='22023',message='expected_financial_version and request_id are required'; end if;
  if p_amount is null or p_amount<=0 or p_from is null or p_to is null or p_from=p_to or p_occurred_at is null then raise exception using errcode='22023',message='invalid final settlement'; end if;
  if v_mode not in ('base_unified','original_currency') then raise exception using errcode='22023',message='invalid final settlement mode'; end if;
  v_payload:=jsonb_build_object('operation','execute_final_settlement','activity_id',p_activity_id,'from_participant_id',p_from,'to_participant_id',p_to,'amount',p_amount,'currency',pg_catalog.upper(pg_catalog.btrim(p_currency)),'mode',v_mode,'expected_financial_version',p_expected_version,'occurred_at',p_occurred_at,'on_behalf_of_participant_id',p_behalf);
  perform private.lock_debt_projection_activity(p_activity_id);
  select a.base_currency,a.archived_at,a.financial_version into v_base,v_archived,v_version from public.activities a where a.id=p_activity_id and not a.is_deleted for update;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if;
  perform private.assert_financial_version(p_activity_id,p_expected_version);
  v_currency:=private.validate_financial_currency(p_activity_id,p_currency);
  if v_mode='base_unified' and v_currency<>v_base then raise exception using errcode='22023',message='base_unified final settlement must use base currency'; end if;
  if v_mode='original_currency' and v_currency=v_base then null; end if;
  if v_currency=v_base and p_amount<>pg_catalog.round(p_amount,1) then raise exception using errcode='22023',message='base-currency amount must have one decimal place'; end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=v_user) then raise exception using errcode='42501',message='caller is not an activity member'; end if;
  perform private.authorize_phase5_actor(p_activity_id,p_from,p_to,p_behalf);
  select t.* into v_existing from public.transfers t where t.activity_id=p_activity_id and t.request_id=p_request_id for update;
  if found then
    if v_existing.request_payload is distinct from v_payload or v_existing.type<>'final_settlement'::public.transfer_type then raise exception using errcode='23505',message='final settlement request id was already used with a different payload'; end if;
    v_result:=v_existing.request_result; if v_result is null then raise exception using errcode='55000',message='idempotent result is unavailable'; end if;
    return query select (v_result->>'transfer_id')::uuid,(v_result->>'amount')::numeric,(v_result->>'currency')::character(3),(v_result->>'mode')::text,(v_result->>'financial_version')::bigint; return;
  end if;
  select p.* into v_plan from private.build_final_settlement_plan_v2(p_activity_id,v_mode) p
    where p.from_participant_id=p_from and p.to_participant_id=p_to and p.amount=p_amount and p.currency=v_currency;
  if not found then raise exception using errcode='23514',message='final settlement does not match current plan'; end if;
  insert into public.transfers(activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,recorded_by,on_behalf_of_participant_id,request_id,request_payload)
    values(p_activity_id,p_from,p_to,'final_settlement',p_amount,v_currency,p_occurred_at,v_user,p_behalf,p_request_id,v_payload) returning id into v_transfer;
  if v_plan.ordinary_amount>0 then insert into public.transfer_components(activity_id,transfer_id,component_type,amount) values(p_activity_id,v_transfer,'settlement',v_plan.ordinary_amount); end if;
  if v_plan.prepayment_return_amount>0 then insert into public.transfer_components(activity_id,transfer_id,component_type,amount) values(p_activity_id,v_transfer,'prepayment_return',v_plan.prepayment_return_amount); end if;
  perform private.assert_component_total(v_transfer);
  if v_plan.ordinary_amount>0 then
    if v_mode='base_unified' then
      for v_flow in select f.* from private.build_final_settlement_flow(p_activity_id) f where f.from_participant_id=p_from and f.to_participant_id=p_to order by f.path_no loop
        for v_hop in select * from jsonb_to_recordset(v_flow.hops) as h(hop_no integer,from_participant_id uuid,to_participant_id uuid,amount numeric) loop
          v_hop_remaining:=v_hop.amount; v_hop_seq:=0;
          for v_debt in
            select ed.id source_debt,ed.expense_id,coalesce(ed.original_currency,v_base)::character(3) debt_currency,coalesce(ed.fx_rate,1)::numeric(20,10) fx_rate,e.occurred_at,e.created_at,
              greatest(ed.amount-coalesce((select sum(coalesce(ta.base_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=ed.id),0)-coalesce((select sum(pu.base_amount) from public.prepayment_usages pu where pu.expense_debt_id=ed.id),0)-coalesce((select sum(f.base_amount) from public.final_settlement_paths f where f.activity_id=p_activity_id and f.source_expense_debt_id=ed.id),0),0)::numeric(20,1) available_base
            from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
            where ed.activity_id=p_activity_id and ed.debtor_participant_id=v_hop.from_participant_id and ed.creditor_participant_id=v_hop.to_participant_id
            order by e.occurred_at,e.created_at,e.id,ed.id
          loop
            exit when v_hop_remaining<=0; if v_debt.available_base<=0 then continue; end if;
            v_take:=least(v_hop_remaining,v_debt.available_base); v_hop_seq:=v_hop_seq+1; v_path_order:=v_path_order+1; v_base_amount:=v_take::numeric(20,1); v_fx:=v_debt.fx_rate; v_original:=case when v_debt.debt_currency=v_base then v_take else pg_catalog.round(v_take/nullif(v_fx,0),4) end;
            insert into public.final_settlement_paths(activity_id,transfer_id,path_order,path_no,hop_no,from_participant_id,to_participant_id,amount,component_type,source_expense_id,source_expense_debt_id,mode,path_currency,original_amount,base_amount,fx_rate)
              values(p_activity_id,v_transfer,v_path_order,v_flow.path_no,v_hop_seq,v_hop.from_participant_id,v_hop.to_participant_id,v_take,'settlement',v_debt.expense_id,v_debt.source_debt,v_mode,v_debt.debt_currency,v_original,v_base_amount,v_fx);
            v_hop_remaining:=v_hop_remaining-v_take;
          end loop;
          if v_hop_remaining>0 then raise exception using errcode='23514',message='final settlement path has no remaining expense debt capacity'; end if;
        end loop;
      end loop;
    else
      for v_flow in select f.* from private.build_final_settlement_flow_original(p_activity_id,v_currency) f where f.from_participant_id=p_from and f.to_participant_id=p_to order by f.path_no loop
        for v_hop in select * from jsonb_to_recordset(v_flow.hops) as h(hop_no integer,from_participant_id uuid,to_participant_id uuid,amount numeric) loop
          v_hop_remaining:=v_hop.amount; v_hop_seq:=0;
          for v_debt in
            select ed.id source_debt,ed.expense_id,coalesce(ed.fx_rate,1)::numeric(20,10) fx_rate,e.occurred_at,e.created_at,
              greatest(coalesce(ed.original_amount,ed.amount)-coalesce((select sum(coalesce(ta.original_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=ed.id),0)-coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu where pu.expense_debt_id=ed.id),0)-coalesce((select sum(f.original_amount) from public.final_settlement_paths f where f.activity_id=p_activity_id and f.source_expense_debt_id=ed.id),0),0)::numeric(20,4) available_original
            from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
            where ed.activity_id=p_activity_id and ed.debtor_participant_id=v_hop.from_participant_id and ed.creditor_participant_id=v_hop.to_participant_id and coalesce(ed.original_currency,v_base)=v_currency
            order by e.occurred_at,e.created_at,e.id,ed.id
          loop
            exit when v_hop_remaining<=0; if v_debt.available_original<=0 then continue; end if;
            v_take:=least(v_hop_remaining,v_debt.available_original); v_hop_seq:=v_hop_seq+1; v_path_order:=v_path_order+1; v_original:=v_take; v_fx:=v_debt.fx_rate; v_base_amount:=pg_catalog.round(v_take*v_fx,1);
            insert into public.final_settlement_paths(activity_id,transfer_id,path_order,path_no,hop_no,from_participant_id,to_participant_id,amount,component_type,source_expense_id,source_expense_debt_id,mode,path_currency,original_amount,base_amount,fx_rate)
              values(p_activity_id,v_transfer,v_path_order,v_flow.path_no,v_hop_seq,v_hop.from_participant_id,v_hop.to_participant_id,v_take,'settlement',v_debt.expense_id,v_debt.source_debt,v_mode,v_currency,v_original,v_base_amount,v_fx);
            v_hop_remaining:=v_hop_remaining-v_take;
          end loop;
          if v_hop_remaining>0 then raise exception using errcode='23514',message='original-currency path has no remaining expense debt capacity'; end if;
        end loop;
      end loop;
    end if;
  end if;
  if v_plan.prepayment_return_amount>0 then
    v_path_order:=v_path_order+1; select coalesce(max(fsp.path_no),0)+1 into v_path_no from public.final_settlement_paths as fsp where fsp.transfer_id=v_transfer;
    insert into public.final_settlement_paths(activity_id,transfer_id,path_order,path_no,hop_no,from_participant_id,to_participant_id,amount,component_type,mode,path_currency,original_amount,base_amount,fx_rate)
      values(p_activity_id,v_transfer,v_path_order,v_path_no,1,p_from,p_to,v_plan.prepayment_return_amount,'prepayment_return',v_mode,v_currency,v_plan.prepayment_return_amount,v_plan.prepayment_return_amount,1);
  end if;
  perform private.phase5_rebuild_after_transfer(p_activity_id);
  update public.activities as act set financial_version=act.financial_version+1 where act.id=p_activity_id returning act.financial_version into v_version;
  v_result:=jsonb_build_object('transfer_id',v_transfer,'amount',p_amount,'currency',v_currency,'mode',v_mode,'financial_version',v_version);
  update public.transfers set request_result=v_result where id=v_transfer;
  return query select v_transfer,p_amount,v_currency,v_mode,v_version;
end;
$function$;

create or replace function public.execute_final_settlement_v2(
  activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric(20,4), currency character(3),
  mode text, expected_financial_version bigint, request_id uuid,
  occurred_at timestamptz default pg_catalog.now(), on_behalf_of_participant_id uuid default null
)
returns table(transfer_id uuid, amount numeric(20,4), currency character(3), mode text, financial_version bigint)
language sql volatile security invoker set search_path = '' as $function$
select * from private.execute_final_settlement_v2_impl($1,$2,$3,$4,$5,$6,$7,$8,$9,$10);
$function$;

create or replace function public.create_final_settlement_v2(
  activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric(20,4), currency character(3),
  mode text, expected_financial_version bigint, request_id uuid,
  occurred_at timestamptz default pg_catalog.now(), on_behalf_of_participant_id uuid default null
)
returns table(transfer_id uuid, amount numeric(20,4), currency character(3), mode text, financial_version bigint)
language sql volatile security invoker set search_path = '' as $function$
select * from private.execute_final_settlement_v2_impl($1,$2,$3,$4,$5,$6,$7,$8,$9,$10);
$function$;


create or replace function private.validate_financial_currency(
  p_activity_id uuid, p_currency character(3)
)
returns character(3)
language plpgsql stable security definer set search_path = ''
as $function$
declare v_base character(3); v_multi boolean; v_currency character(3) := pg_catalog.upper(pg_catalog.btrim(p_currency));
begin
  select a.base_currency,a.multi_currency_enabled into v_base,v_multi
  from public.activities a where a.id=p_activity_id and not a.is_deleted;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_currency is null or v_currency !~ '^[A-Z]{3}$' then
    raise exception using errcode='22023',message='currency must be three uppercase letters';
  end if;
  if v_currency=v_base then return v_currency; end if;
  if not v_multi then raise exception using errcode='22023',message='foreign currency is disabled for this activity'; end if;
  if not exists(select 1 from public.exchange_rate_supported_currencies c
    where c.currency_code=v_currency and c.enabled) then
    raise exception using errcode='22023',message='currency is not supported';
  end if;
  return v_currency;
end;
$function$;

create or replace function private.assert_financial_version(
  p_activity_id uuid, p_expected_version bigint
)
returns void language plpgsql stable security definer set search_path = ''
as $function$
declare v_version bigint;
begin
  if p_expected_version is null then
    raise exception using errcode='22023',message='expected financial_version is required';
  end if;
  select a.financial_version into v_version from public.activities a where a.id=p_activity_id;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_version<>p_expected_version then
    raise exception using errcode='40001',message='financial_version mismatch; refresh the plan';
  end if;
end;
$function$;

create or replace function public.preview_prepayment(
  p_activity_id uuid, p_owner_participant_id uuid, p_custodian_participant_id uuid,
  p_amount numeric(20,4), p_currency character(3)
)
returns table(
  activity_id uuid, owner_participant_id uuid, custodian_participant_id uuid,
  amount numeric(20,4), settlement_amount numeric(20,4), prepayment_amount numeric(20,4),
  new_balance numeric(20,4), currency character(3), financial_version bigint
)
language plpgsql stable security invoker set search_path = ''
as $function$
declare v_currency character(3); v_base character(3); v_cap numeric(20,4); v_balance numeric(20,4); v_ver bigint;
begin
  if (select auth.uid()) is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=(select auth.uid())) then
    raise exception using errcode='42501',message='caller is not an activity member';
  end if;
  if p_amount is null or p_amount<=0 or p_owner_participant_id is null or p_custodian_participant_id is null
     or p_owner_participant_id=p_custodian_participant_id then
    raise exception using errcode='22023',message='invalid prepayment';
  end if;
  v_currency:=private.validate_financial_currency(p_activity_id,p_currency);
  select a.base_currency,a.financial_version into v_base,v_ver from public.activities a where a.id=p_activity_id;
  select coalesce(sum(case when v_currency=v_base then coalesce(b.base_amount,b.amount) else coalesce(b.original_amount,b.amount) end),0)
    into v_cap from public.bilateral_debts b
    where b.activity_id=p_activity_id
      and b.debtor_participant_id=p_owner_participant_id
      and b.creditor_participant_id=p_custodian_participant_id
      and (v_currency=v_base or b.currency=v_currency);
  select coalesce(pa.balance,0) into v_balance from public.prepayment_accounts pa
    where pa.activity_id=p_activity_id and pa.owner_participant_id=p_owner_participant_id
      and pa.custodian_participant_id=p_custodian_participant_id and pa.currency=v_currency;
  return query select p_activity_id,p_owner_participant_id,p_custodian_participant_id,p_amount,
    least(p_amount,coalesce(v_cap,0)),greatest(p_amount-coalesce(v_cap,0),0),
    coalesce(v_balance,0)+greatest(p_amount-coalesce(v_cap,0),0),v_currency,v_ver;
end;
$function$;

create or replace function private.create_prepayment_v2_impl(
  p_activity_id uuid, p_owner uuid, p_custodian uuid, p_amount numeric(20,4),
  p_currency character(3), p_occurred_at timestamptz, p_behalf uuid,
  p_expected_version bigint, p_request_id uuid
)
returns table(
  transfer_id uuid, settlement_amount numeric(20,4), prepayment_amount numeric(20,4),
  new_balance numeric(20,4), currency character(3), financial_version bigint
)
language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_user uuid := (select auth.uid()); v_currency character(3); v_base character(3); v_archived timestamptz;
  v_cap numeric(20,4); v_settlement numeric(20,4); v_prepayment numeric(20,4); v_balance numeric(20,4);
  v_version bigint; v_transfer uuid; v_existing record; v_payload jsonb; v_result jsonb;
begin
  if v_user is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if p_expected_version is null or p_request_id is null then
    raise exception using errcode='22023',message='expected_financial_version and request_id are required';
  end if;
  if p_amount is null or p_amount<=0 or p_owner is null or p_custodian is null or p_owner=p_custodian
     or p_occurred_at is null then raise exception using errcode='22023',message='invalid prepayment'; end if;
  v_payload:=jsonb_build_object('operation','create_prepayment','activity_id',p_activity_id,
    'owner_participant_id',p_owner,'custodian_participant_id',p_custodian,'amount',p_amount,
    'currency',pg_catalog.upper(pg_catalog.btrim(p_currency)),'occurred_at',p_occurred_at,
    'on_behalf_of_participant_id',p_behalf,'expected_financial_version',p_expected_version);
  perform private.lock_debt_projection_activity(p_activity_id);
  select a.base_currency,a.archived_at,a.financial_version into v_base,v_archived,v_version
    from public.activities a where a.id=p_activity_id and not a.is_deleted for update;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if;
  perform private.assert_financial_version(p_activity_id,p_expected_version);
  v_currency:=private.validate_financial_currency(p_activity_id,p_currency);
  if v_currency=v_base and p_amount<>pg_catalog.round(p_amount,1) then
    raise exception using errcode='22023',message='base-currency amount must have one decimal place';
  end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=v_user) then
    raise exception using errcode='42501',message='caller is not an activity member';
  end if;
  perform private.authorize_phase5_actor(p_activity_id,p_owner,p_custodian,p_behalf);
  if p_request_id is not null then
    select t.* into v_existing from public.transfers t where t.activity_id=p_activity_id and t.request_id=p_request_id for update;
    if found then
      if v_existing.request_payload is distinct from v_payload or v_existing.type<>'prepayment'::public.transfer_type then
        raise exception using errcode='23505',message='prepayment request id was already used with a different payload';
      end if;
      v_result:=v_existing.request_result;
      if v_result is null then raise exception using errcode='55000',message='idempotent result is unavailable'; end if;
      return query select (v_result->>'transfer_id')::uuid,(v_result->>'settlement_amount')::numeric,
        (v_result->>'prepayment_amount')::numeric,(v_result->>'new_balance')::numeric,
        (v_result->>'currency')::character(3),(v_result->>'financial_version')::bigint;
      return;
    end if;
  end if;
  select coalesce(sum(case when v_currency=v_base then coalesce(b.base_amount,b.amount) else coalesce(b.original_amount,b.amount) end),0)
    into v_cap from public.bilateral_debts b
    where b.activity_id=p_activity_id and b.debtor_participant_id=p_owner and b.creditor_participant_id=p_custodian
      and (v_currency=v_base or b.currency=v_currency);
  v_settlement:=least(p_amount,coalesce(v_cap,0));
  v_prepayment:=greatest(p_amount-v_settlement,0);
  insert into public.transfers(activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,recorded_by,on_behalf_of_participant_id,request_id,request_payload)
  values(p_activity_id,p_owner,p_custodian,'prepayment',p_amount,v_currency,p_occurred_at,v_user,p_behalf,p_request_id,v_payload)
  returning id into v_transfer;
  if v_settlement>0 then insert into public.transfer_components(activity_id,transfer_id,component_type,amount)
    values(p_activity_id,v_transfer,'settlement',v_settlement); end if;
  if v_prepayment>0 then insert into public.transfer_components(activity_id,transfer_id,component_type,amount)
    values(p_activity_id,v_transfer,'prepayment',v_prepayment); end if;
  perform private.assert_component_total(v_transfer);
  perform private.phase5_rebuild_after_transfer(p_activity_id);
  update public.activities as act set financial_version=act.financial_version+1 where act.id=p_activity_id returning act.financial_version into v_version;
  select coalesce(pa.balance,0) into v_balance from public.prepayment_accounts pa
    where pa.activity_id=p_activity_id and pa.owner_participant_id=p_owner and pa.custodian_participant_id=p_custodian and pa.currency=v_currency;
  v_result:=jsonb_build_object('transfer_id',v_transfer,'settlement_amount',v_settlement,'prepayment_amount',v_prepayment,
    'new_balance',coalesce(v_balance,0),'currency',v_currency,'financial_version',v_version);
  update public.transfers set request_result=v_result where id=v_transfer;
  return query select v_transfer,v_settlement,v_prepayment,coalesce(v_balance,0),v_currency,v_version;
end;
$function$;

create or replace function public.create_prepayment_v2(
  activity_id uuid, owner_participant_id uuid, custodian_participant_id uuid,
  amount numeric(20,4), currency character(3), occurred_at timestamptz default pg_catalog.now(),
  on_behalf_of_participant_id uuid default null, expected_financial_version bigint default null,
  request_id uuid default null
)
returns table(transfer_id uuid, settlement_amount numeric(20,4), prepayment_amount numeric(20,4),
  new_balance numeric(20,4), currency character(3), financial_version bigint)
language sql volatile security invoker set search_path = '' as $function$
select * from private.create_prepayment_v2_impl($1,$2,$3,$4,$5,$6,$7,$8,$9);
$function$;

create or replace function private.create_prepayment_return_v2_impl(
  p_activity_id uuid, p_owner uuid, p_custodian uuid, p_amount numeric(20,4),
  p_currency character(3), p_occurred_at timestamptz, p_behalf uuid,
  p_expected_version bigint, p_request_id uuid
)
returns table(
  transfer_id uuid, amount numeric(20,4), currency character(3),
  remaining_balance numeric(20,4), financial_version bigint
)
language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_user uuid := (select auth.uid()); v_currency character(3); v_base character(3);
  v_archived timestamptz; v_version bigint; v_balance numeric(20,4); v_transfer uuid;
  v_existing record; v_payload jsonb; v_result jsonb;
begin
  if v_user is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if p_expected_version is null or p_request_id is null then
    raise exception using errcode='22023',message='expected_financial_version and request_id are required';
  end if;
  if p_amount is null or p_amount<=0 or p_owner is null or p_custodian is null or p_owner=p_custodian
     or p_occurred_at is null then raise exception using errcode='22023',message='invalid prepayment return'; end if;
  v_payload:=jsonb_build_object('operation','create_prepayment_return','activity_id',p_activity_id,
    'owner_participant_id',p_owner,'custodian_participant_id',p_custodian,'amount',p_amount,
    'currency',pg_catalog.upper(pg_catalog.btrim(p_currency)),'occurred_at',p_occurred_at,
    'on_behalf_of_participant_id',p_behalf,'expected_financial_version',p_expected_version);
  perform private.lock_debt_projection_activity(p_activity_id);
  select a.base_currency,a.archived_at,a.financial_version into v_base,v_archived,v_version
    from public.activities a where a.id=p_activity_id and not a.is_deleted for update;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if;
  perform private.assert_financial_version(p_activity_id,p_expected_version);
  v_currency:=private.validate_financial_currency(p_activity_id,p_currency);
  if v_currency=v_base and p_amount<>pg_catalog.round(p_amount,1) then
    raise exception using errcode='22023',message='base-currency amount must have one decimal place';
  end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=v_user) then
    raise exception using errcode='42501',message='caller is not an activity member'; end if;
  perform private.authorize_phase5_actor(p_activity_id,p_custodian,p_owner,p_behalf);
  if p_request_id is not null then
    select t.* into v_existing from public.transfers t where t.activity_id=p_activity_id and t.request_id=p_request_id for update;
    if found then
      if v_existing.request_payload is distinct from v_payload or v_existing.type<>'prepayment_return'::public.transfer_type then
        raise exception using errcode='23505',message='prepayment return request id was already used with a different payload'; end if;
      v_result:=v_existing.request_result;
      if v_result is null then raise exception using errcode='55000',message='idempotent result is unavailable'; end if;
      return query select (v_result->>'transfer_id')::uuid,(v_result->>'amount')::numeric,
        (v_result->>'currency')::character(3),(v_result->>'remaining_balance')::numeric,
        (v_result->>'financial_version')::bigint; return;
    end if;
  end if;
  select pa.balance into v_balance from public.prepayment_accounts pa where pa.activity_id=p_activity_id
    and pa.owner_participant_id=p_owner and pa.custodian_participant_id=p_custodian and pa.currency=v_currency;
  if v_balance is null or p_amount>v_balance then
    raise exception using errcode='23514',message='prepayment return exceeds available balance'; end if;
  insert into public.transfers(activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,recorded_by,on_behalf_of_participant_id,request_id,request_payload)
  values(p_activity_id,p_custodian,p_owner,'prepayment_return',p_amount,v_currency,p_occurred_at,v_user,p_behalf,p_request_id,v_payload)
  returning id into v_transfer;
  insert into public.transfer_components(activity_id,transfer_id,component_type,amount)
    values(p_activity_id,v_transfer,'prepayment_return',p_amount);
  perform private.assert_component_total(v_transfer);
  perform private.phase5_rebuild_after_transfer(p_activity_id);
  update public.activities as act set financial_version=act.financial_version+1 where act.id=p_activity_id returning act.financial_version into v_version;
  select coalesce(pa.balance,0) into v_balance from public.prepayment_accounts pa where pa.activity_id=p_activity_id
    and pa.owner_participant_id=p_owner and pa.custodian_participant_id=p_custodian and pa.currency=v_currency;
  v_result:=jsonb_build_object('transfer_id',v_transfer,'amount',p_amount,'currency',v_currency,
    'remaining_balance',coalesce(v_balance,0),'financial_version',v_version);
  update public.transfers set request_result=v_result where id=v_transfer;
  return query select v_transfer,p_amount,v_currency,coalesce(v_balance,0),v_version;
end;
$function$;

create or replace function public.create_prepayment_return_v2(
  activity_id uuid, owner_participant_id uuid, custodian_participant_id uuid,
  amount numeric(20,4), currency character(3), occurred_at timestamptz default pg_catalog.now(),
  on_behalf_of_participant_id uuid default null, expected_financial_version bigint default null,
  request_id uuid default null
)
returns table(transfer_id uuid, amount numeric(20,4), currency character(3),
  remaining_balance numeric(20,4), financial_version bigint)
language sql volatile security invoker set search_path = '' as $function$
select * from private.create_prepayment_return_v2_impl($1,$2,$3,$4,$5,$6,$7,$8,$9);
$function$;

revoke all on function private.validate_financial_currency(uuid,character),
  private.assert_financial_version(uuid,bigint), private.rebuild_transfer_allocations_locked(uuid),
  private.rebuild_prepayment_projections_locked(uuid), private.rebuild_bilateral_debts_locked(uuid),
  private.phase5_rebuild_after_transfer(uuid), private.build_final_settlement_flow(uuid),
  private.build_final_settlement_flow_original(uuid,character), private.build_final_settlement_plan_v2(uuid,text),
  private.create_prepayment_v2_impl(uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid),
  private.create_prepayment_return_v2_impl(uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid),
  private.execute_final_settlement_v2_impl(uuid,uuid,uuid,numeric,character,text,bigint,uuid,timestamptz,uuid)
  from public,anon,authenticated;
grant execute on function private.create_prepayment_v2_impl(uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid),
  private.create_prepayment_return_v2_impl(uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid),
  private.execute_final_settlement_v2_impl(uuid,uuid,uuid,numeric,character,text,bigint,uuid,timestamptz,uuid)
  to authenticated;
grant execute on function private.validate_financial_currency(uuid,character),
  private.build_final_settlement_plan_v2(uuid,text)
  to authenticated;
revoke all on function public.preview_prepayment(uuid,uuid,uuid,numeric,character),
  public.create_prepayment_v2(uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid),
  public.create_prepayment_return_v2(uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid),
  public.preview_final_settlement_v2(uuid,text), public.get_final_settlement_plan_v2(uuid,text),
  public.preview_activity_settlement_v2(uuid,text),
  public.execute_final_settlement_v2(uuid,uuid,uuid,numeric,character,text,bigint,uuid,timestamptz,uuid),
  public.create_final_settlement_v2(uuid,uuid,uuid,numeric,character,text,bigint,uuid,timestamptz,uuid)
  from public,anon,authenticated;
grant execute on function public.preview_prepayment(uuid,uuid,uuid,numeric,character),
  public.create_prepayment_v2(uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid),
  public.create_prepayment_return_v2(uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid),
  public.preview_final_settlement_v2(uuid,text), public.get_final_settlement_plan_v2(uuid,text),
  public.preview_activity_settlement_v2(uuid,text),
  public.execute_final_settlement_v2(uuid,uuid,uuid,numeric,character,text,bigint,uuid,timestamptz,uuid),
  public.create_final_settlement_v2(uuid,uuid,uuid,numeric,character,text,bigint,uuid,timestamptz,uuid)
  to authenticated;

do $backfill$
declare v_activity_id uuid;
begin
  for v_activity_id in select id from public.activities where not is_deleted order by id loop
    perform private.rebuild_activity_debt_projection(v_activity_id);
  end loop;
end;
$backfill$;

commit;
