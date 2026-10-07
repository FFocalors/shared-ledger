begin;

-- Prepayment is an activity-level feature of large activities. Guard both the
-- immutable facts and their projections so legacy RPCs, v2 RPCs, restores, and
-- service-side rebuilds share the same boundary.

create or replace function private.assert_large_prepayment_activity(p_activity_id uuid)
returns void
language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_type public.activity_type;
begin
  select a.type into v_type
  from public.activities a
  where a.id = p_activity_id and not a.is_deleted
  for share;

  if v_type is distinct from 'large'::public.activity_type then
    raise exception using errcode = '23514', message = '普通活动不支持预存';
  end if;
end;
$function$;

create or replace function private.guard_activity_prepayment_type_downgrade()
returns trigger
language plpgsql volatile security definer set search_path = ''
as $function$
begin
  if old.type = 'large'::public.activity_type
     and new.type = 'normal'::public.activity_type
     and (
       exists (select 1 from public.transfers t where t.activity_id=old.id and t.type in ('prepayment'::public.transfer_type,'prepayment_return'::public.transfer_type))
       or exists (select 1 from public.transfer_components c where c.activity_id=old.id and c.component_type in ('prepayment','prepayment_return'))
       or exists (select 1 from public.prepayment_accounts pa where pa.activity_id=old.id)
       or exists (select 1 from public.prepayment_usages pu where pu.activity_id=old.id)
       or exists (select 1 from public.final_settlement_paths f where f.activity_id=old.id and f.component_type='prepayment_return')
     ) then
    raise exception using errcode='23514',message='普通活动不支持预存';
  end if;
  return new;
end;
$function$;

create or replace function private.guard_prepayment_transfer_activity()
returns trigger
language plpgsql volatile security definer set search_path = ''
as $function$
begin
  if new.type in ('prepayment'::public.transfer_type, 'prepayment_return'::public.transfer_type) then
    perform private.assert_large_prepayment_activity(new.activity_id);
  end if;
  return new;
end;
$function$;

create or replace function private.guard_prepayment_component_activity()
returns trigger
language plpgsql volatile security definer set search_path = ''
as $function$
begin
  if new.component_type in ('prepayment', 'prepayment_return') then
    perform private.assert_large_prepayment_activity(new.activity_id);
  end if;
  return new;
end;
$function$;

create or replace function private.guard_prepayment_projection_activity()
returns trigger
language plpgsql volatile security definer set search_path = ''
as $function$
begin
  perform private.assert_large_prepayment_activity(new.activity_id);
  return new;
end;
$function$;

create or replace function private.guard_prepayment_final_path_activity()
returns trigger
language plpgsql volatile security definer set search_path = ''
as $function$
begin
  if new.component_type = 'prepayment_return' then
    perform private.assert_large_prepayment_activity(new.activity_id);
  end if;
  return new;
end;
$function$;

drop trigger if exists transfers_large_activity_prepayment_guard on public.transfers;
create trigger transfers_large_activity_prepayment_guard
before insert or update on public.transfers
for each row execute function private.guard_prepayment_transfer_activity();

drop trigger if exists transfer_components_large_activity_prepayment_guard on public.transfer_components;
create trigger transfer_components_large_activity_prepayment_guard
before insert or update on public.transfer_components
for each row execute function private.guard_prepayment_component_activity();

drop trigger if exists prepayment_accounts_large_activity_guard on public.prepayment_accounts;
create trigger prepayment_accounts_large_activity_guard
before insert or update on public.prepayment_accounts
for each row execute function private.guard_prepayment_projection_activity();

drop trigger if exists prepayment_usages_large_activity_guard on public.prepayment_usages;
create trigger prepayment_usages_large_activity_guard
before insert or update on public.prepayment_usages
for each row execute function private.guard_prepayment_projection_activity();

drop trigger if exists final_settlement_paths_large_activity_prepayment_guard on public.final_settlement_paths;
create trigger final_settlement_paths_large_activity_prepayment_guard
before insert or update on public.final_settlement_paths
for each row execute function private.guard_prepayment_final_path_activity();

drop trigger if exists activities_prepayment_type_downgrade_guard on public.activities;
create trigger activities_prepayment_type_downgrade_guard
before update of type on public.activities
for each row execute function private.guard_activity_prepayment_type_downgrade();

-- Fail closed if any prepayment fact or projection exists on an ordinary
-- activity. This migration never removes or rewrites existing financial data.
do $check$
begin
  if exists (
    select 1
    from public.activities a
    where a.type = 'normal'::public.activity_type
      and (
        exists (
          select 1 from public.transfers t
          where t.activity_id = a.id
            and t.type in ('prepayment'::public.transfer_type, 'prepayment_return'::public.transfer_type)
        )
        or exists (
          select 1 from public.transfer_components c
          where c.activity_id = a.id and c.component_type in ('prepayment', 'prepayment_return')
        )
        or exists (select 1 from public.prepayment_accounts pa where pa.activity_id = a.id)
        or exists (select 1 from public.prepayment_usages pu where pu.activity_id = a.id)
        or exists (
          select 1 from public.final_settlement_paths f
          where f.activity_id = a.id and f.component_type = 'prepayment_return'
        )
      )
  ) then
    raise exception using
      errcode = '23514',
      message = 'ordinary activities contain prepayment facts or projections; migration aborted';
  end if;
end;
$check$;

-- The authenticated preview remains callable with its existing signature,
-- but ordinary activities are rejected before any prepayment calculation.
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
declare
  v_currency character(3); v_base character(3); v_archived timestamptz;
  v_cap numeric(20,4); v_balance numeric(20,4); v_ver bigint; v_type public.activity_type;
  v_participant_count integer;
begin
  if (select auth.uid()) is null then
    raise exception using errcode='28000',message='authentication is required';
  end if;
  if not exists(
    select 1 from public.activity_members m
    where m.activity_id=p_activity_id and m.user_id=(select auth.uid())
  ) then
    raise exception using errcode='42501',message='caller is not an activity member';
  end if;
  if p_amount is null or p_amount<=0 or p_owner_participant_id is null
     or p_custodian_participant_id is null
     or p_owner_participant_id=p_custodian_participant_id then
    raise exception using errcode='22023',message='invalid prepayment';
  end if;
  select a.base_currency,a.archived_at,a.financial_version,a.type
    into v_base,v_archived,v_ver,v_type
    from public.activities a
    where a.id=p_activity_id and not a.is_deleted;
  if not found then
    raise exception using errcode='P0002',message='activity was not found';
  end if;
  if v_type <> 'large'::public.activity_type then
    raise exception using errcode='23514',message='普通活动不支持预存';
  end if;
  if v_archived is not null then
    raise exception using errcode='55000',message='archived activity is read-only';
  end if;
  select count(*) into v_participant_count
    from public.participants p
    where p.activity_id=p_activity_id
      and p.id in (p_owner_participant_id,p_custodian_participant_id)
      and not p.is_deleted;
  if v_participant_count<>2 then
    raise exception using errcode='P0002',message='prepayment participant was not found';
  end if;
  v_currency:=private.validate_financial_currency(p_activity_id,p_currency);
  if v_currency=v_base and p_amount<>pg_catalog.round(p_amount,1) then
    raise exception using errcode='22023',message='base-currency amount must have one decimal place';
  end if;
  select coalesce(sum(case when v_currency=v_base then coalesce(b.base_amount,b.amount)
                           else coalesce(b.original_amount,b.amount) end),0)
    into v_cap
    from public.bilateral_debts b
    where b.activity_id=p_activity_id
      and b.debtor_participant_id=p_owner_participant_id
      and b.creditor_participant_id=p_custodian_participant_id
      and (v_currency=v_base or b.currency=v_currency);
  select coalesce(pa.balance,0) into v_balance
    from public.prepayment_accounts pa
    where pa.activity_id=p_activity_id
      and pa.owner_participant_id=p_owner_participant_id
      and pa.custodian_participant_id=p_custodian_participant_id
      and pa.currency=v_currency;
  return query
    select p_activity_id,p_owner_participant_id,p_custodian_participant_id,p_amount,
      least(p_amount,coalesce(v_cap,0)),greatest(p_amount-coalesce(v_cap,0),0),
      coalesce(v_balance,0)+greatest(p_amount-coalesce(v_cap,0),0),v_currency,v_ver;
end;
$function$;

-- Ordinary bilateral debts still appear in final settlement previews and can
-- still be settled. Only prepayment-return items are excluded for normal.
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
    from public.prepayment_accounts pa
    join public.activities a on a.id=pa.activity_id and a.type='large'::public.activity_type
    where pa.activity_id=p_activity_id and pa.balance>0
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

revoke all on function private.assert_large_prepayment_activity(uuid),
  private.guard_prepayment_transfer_activity(),
  private.guard_prepayment_component_activity(),
  private.guard_prepayment_projection_activity(),
  private.guard_prepayment_final_path_activity(),
  private.guard_activity_prepayment_type_downgrade()
from public, anon, authenticated;

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
  v_base_take numeric(20,1);
begin
  if exists (select 1 from public.activities a where a.id=p_activity_id and a.type='normal'::public.activity_type) then
    if exists (
      select 1 from public.transfers t
      where t.activity_id=p_activity_id and t.type in ('prepayment'::public.transfer_type,'prepayment_return'::public.transfer_type)
      union all
      select 1 from public.transfer_components c
      where c.activity_id=p_activity_id and c.component_type in ('prepayment','prepayment_return')
      union all
      select 1 from public.prepayment_accounts pa where pa.activity_id=p_activity_id
      union all
      select 1 from public.prepayment_usages pu where pu.activity_id=p_activity_id
      union all
      select 1 from public.final_settlement_paths f where f.activity_id=p_activity_id and f.component_type='prepayment_return'
    ) then
      raise exception using errcode='23514',message='普通活动不支持预存';
    end if;
    return;
  end if;
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
    order by owner_participant_id,custodian_participant_id,
      (currency=v_base_currency),currency
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
      with raw as (
        select ed.id,ed.expense_id,ed.activity_id,ed.debtor_participant_id,ed.creditor_participant_id,
          ed.amount::numeric(20,1) gross_base,
          coalesce(ed.original_amount,ed.amount)::numeric(20,4) gross_original,
          coalesce(ed.original_currency,v_base_currency)::character(3) debt_currency,
          coalesce(ed.fx_rate,1)::numeric(20,10) debt_fx,
          e.occurred_at,e.created_at,e.id expense_id_order,
          greatest(coalesce(ed.original_amount,ed.amount)
            -coalesce((select sum(coalesce(ta.original_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=ed.id),0)
            -coalesce((select sum(coalesce(f.original_amount,f.amount)) from public.final_settlement_paths f join public.transfers ft on ft.id=f.transfer_id
              where f.activity_id=p_activity_id and f.component_type='settlement' and not ft.is_voided
                and f.from_participant_id=ed.debtor_participant_id and f.to_participant_id=ed.creditor_participant_id
                and (f.source_expense_debt_id=ed.id or (f.source_expense_debt_id is null and f.source_expense_id=ed.expense_id))),0),0)::numeric(20,4) unpaid_original,
          greatest(ed.amount
            -coalesce((select sum(coalesce(ta.base_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=ed.id),0)
            -coalesce((select sum(coalesce(f.base_amount,f.amount)) from public.final_settlement_paths f join public.transfers ft on ft.id=f.transfer_id
              where f.activity_id=p_activity_id and f.component_type='settlement' and not ft.is_voided
                and f.from_participant_id=ed.debtor_participant_id and f.to_participant_id=ed.creditor_participant_id
                and (f.source_expense_debt_id=ed.id or (f.source_expense_debt_id is null and f.source_expense_id=ed.expense_id))),0),0)::numeric(20,1) unpaid_base
        from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
        where ed.activity_id=p_activity_id and not e.is_deleted
      ), net as (
        select r.*,
          coalesce(sum(r.unpaid_original) over(partition by r.debtor_participant_id,r.creditor_participant_id,r.debt_currency
            order by r.occurred_at,r.created_at,r.expense_id_order,r.id rows between unbounded preceding and 1 preceding),0) prior_original,
          coalesce((select sum(x.unpaid_original) from raw x where x.debtor_participant_id=r.creditor_participant_id
            and x.creditor_participant_id=r.debtor_participant_id and x.debt_currency=r.debt_currency
            -- A linked refund is processed by the explicit Usage-release pass
            -- below. Excluding that matching refund here prevents its reverse
            -- debt from both reducing eligible Usage and releasing the same
            -- Usage a second time.
            and not exists(select 1 from public.expenses linked_refund
              where linked_refund.id=x.expense_id
                and linked_refund.original_expense_id=r.expense_id
                and linked_refund.original_amount<0 and not linked_refund.is_deleted)),0) reverse_original
        from raw r
      ), available as (
        select n.*,
          greatest(n.unpaid_original-least(n.unpaid_original,greatest(n.reverse_original-n.prior_original,0)),0)::numeric(20,4) net_original,
          greatest(n.unpaid_base-pg_catalog.round(least(n.unpaid_original,greatest(n.reverse_original-n.prior_original,0))*n.debt_fx,1),0)::numeric(20,1) net_base
        from net n
      )
      select av.id,av.gross_base debt_base,av.gross_original debt_original,av.debt_currency,av.debt_fx,
        av.occurred_at,av.created_at,av.expense_id_order expense_id,
        greatest(av.net_original-coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu where pu.expense_debt_id=av.id),0),0)::numeric(20,4) available_original,
        greatest(av.net_base-coalesce((select sum(pu.base_amount) from public.prepayment_usages pu where pu.expense_debt_id=av.id),0),0)::numeric(20,1) available_base
      from available av
      where av.debtor_participant_id=v_account.owner_participant_id
        and av.creditor_participant_id=v_account.custodian_participant_id
        and (v_account.currency=v_base_currency or av.debt_currency=v_account.currency)
      order by av.occurred_at,av.created_at,av.expense_id_order,av.id
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
    select rf.original_expense_id,s.participant_id owner_participant_id,abs(s.amount)::numeric(20,4) benefit
    from public.expenses rf join public.splits s on s.expense_id=rf.id
    where rf.original_expense_id is not null and rf.original_amount<0 and not rf.is_deleted and s.amount<0
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
      v_take:=least(v_left,v_account.debt_amount)::numeric(20,4);
      v_base_take:=pg_catalog.round(v_take*v_account.bill_fx_rate,1)::numeric(20,1);
      v_pre_take:=case when v_account.prepayment_currency=v_base_currency then v_base_take else v_take end;
      if v_take>=v_account.debt_amount then
        delete from public.prepayment_usages where id=v_account.usage_id;
      else
        update public.prepayment_usages set
          amount=amount-v_take,
          prepayment_amount=prepayment_amount-v_pre_take,
          debt_amount=debt_amount-v_take,
          base_amount=base_amount-v_base_take
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
  v_user uuid := (select auth.uid()); v_currency character(3); v_base character(3); v_archived timestamptz; v_is_deleted boolean;
  v_cap numeric(20,4); v_settlement numeric(20,4); v_prepayment numeric(20,4); v_balance numeric(20,4);
  v_version bigint; v_transfer uuid; v_existing record; v_payload jsonb; v_result jsonb;
  v_participant_count integer;
  v_settlement_component_id uuid;
  v_preview record;
begin
  if v_user is null then
    raise exception using errcode='28000',message='authentication is required';
  end if;
  if p_expected_version is null or p_request_id is null then
    raise exception using errcode='22023',message='expected_financial_version and request_id are required';
  end if;
  if p_amount is null or p_amount<=0 or p_owner is null or p_custodian is null
     or p_owner=p_custodian or p_occurred_at is null then
    raise exception using errcode='22023',message='invalid prepayment';
  end if;
  if p_behalf is not null then
    raise exception using errcode='42501',message='on-behalf prepayment is not supported';
  end if;
  v_payload:=jsonb_build_object('operation','create_prepayment','activity_id',p_activity_id,
    'owner_participant_id',p_owner,'custodian_participant_id',p_custodian,'amount',p_amount,
    'currency',pg_catalog.upper(pg_catalog.btrim(p_currency)),'occurred_at',p_occurred_at,
    'on_behalf_of_participant_id',p_behalf,'expected_financial_version',p_expected_version);
  perform private.lock_debt_projection_activity(p_activity_id);
  select a.base_currency,a.archived_at,a.financial_version,a.is_deleted into v_base,v_archived,v_version,v_is_deleted
    from public.activities a where a.id=p_activity_id for update;
  if not found then
    raise exception using errcode='P0002',message='activity was not found';
  end if;
  select t.* into v_existing
    from public.transfers t where t.activity_id=p_activity_id and t.request_id=p_request_id for update;
  if found then
    if v_existing.request_payload is distinct from v_payload
       or v_existing.type<>'prepayment'::public.transfer_type
       or v_existing.recorded_by is distinct from v_user then
      raise exception using errcode='23505',message='prepayment request id was already used with a different payload or actor';
    end if;
    v_result:=v_existing.request_result;
    if v_result is null then raise exception using errcode='55000',message='idempotent result is unavailable'; end if;
    return query select (v_result->>'transfer_id')::uuid,(v_result->>'settlement_amount')::numeric,
      (v_result->>'prepayment_amount')::numeric,(v_result->>'new_balance')::numeric,
      (v_result->>'currency')::character(3),(v_result->>'financial_version')::bigint;
    return;
  end if;
  if v_is_deleted then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived is not null then
    raise exception using errcode='55000',message='archived activity is read-only';
  end if;
  perform private.assert_financial_version(p_activity_id,p_expected_version);
  v_currency:=private.validate_financial_currency(p_activity_id,p_currency);
  if v_currency=v_base and p_amount<>pg_catalog.round(p_amount,1) then
    raise exception using errcode='22023',message='base-currency amount must have one decimal place';
  end if;
  if not exists(
    select 1 from public.activity_members m
    where m.activity_id=p_activity_id and m.user_id=v_user
  ) then
    raise exception using errcode='42501',message='caller is not an activity member';
  end if;
  select count(*) into v_participant_count
    from public.participants p
    where p.activity_id=p_activity_id
      and p.id in (p_owner,p_custodian)
      and not p.is_deleted;
  if v_participant_count<>2 then
    raise exception using errcode='P0002',message='prepayment participant was not found';
  end if;
  perform private.assert_large_prepayment_activity(p_activity_id);
  -- Deliberately do not call the phase-5 actor gate here.  New prepayments
  -- are allowed for any two distinct activity participants.
  select coalesce(sum(case when v_currency=v_base then coalesce(b.base_amount,b.amount)
                           else coalesce(b.original_amount,b.amount) end),0)
    into v_cap
    from public.bilateral_debts b
    where b.activity_id=p_activity_id
      and b.debtor_participant_id=p_owner
      and b.creditor_participant_id=p_custodian
      and (v_currency=v_base or b.currency=v_currency);
  v_settlement:=least(p_amount,coalesce(v_cap,0));
  v_prepayment:=greatest(p_amount-v_settlement,0);
  insert into public.transfers(
    activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,
    recorded_by,on_behalf_of_participant_id,request_id,request_payload
  ) values(
    p_activity_id,p_owner,p_custodian,'prepayment',p_amount,v_currency,p_occurred_at,
    v_user,p_behalf,p_request_id,v_payload
  ) returning id into v_transfer;
  if v_settlement>0 then
    insert into public.transfer_components(activity_id,transfer_id,component_type,amount)
      values(p_activity_id,v_transfer,'settlement',v_settlement)
      returning id into v_settlement_component_id;
    -- The settlement portion is a real cash payment, so persist the FIFO
    -- source amounts just like an ordinary FIFO repayment. Without these
    -- durable rows a later full projection rebuild can move this payment to
    -- a different Expense when debts are recreated.
    for v_preview in
      select * from private.build_expense_repayment_preview(
        p_activity_id,p_owner,p_custodian,v_settlement,v_currency,'FIFO',null,p_expected_version
      )
    loop
      if v_preview.payment_amount<=0 then
        continue;
      end if;
      insert into public.transfer_expense_allocations(
        activity_id,transfer_id,settlement_component_id,expense_id,ledger_unit_id,
        debtor_participant_id,creditor_participant_id,allocation_mode,
        payment_currency,payment_amount,original_currency,original_amount,
        base_amount,fx_rate,source_expense_debt_id
      )
      select p_activity_id,v_transfer,v_settlement_component_id,v_preview.expense_id,
        v_preview.ledger_unit_id,p_owner,p_custodian,'FIFO',
        v_preview.payment_currency,v_preview.payment_amount,
        v_preview.original_currency,v_preview.original_amount,v_preview.base_amount,
        v_preview.fx_rate,ed.id
      from public.expense_debts ed
      where ed.activity_id=p_activity_id and ed.expense_id=v_preview.expense_id
        and ed.debtor_participant_id=p_owner and ed.creditor_participant_id=p_custodian;
      if not found then
        raise exception using errcode='40001',message='prepayment settlement source changed while committing; refresh the plan';
      end if;
    end loop;
  end if;
  if v_prepayment>0 then
    insert into public.transfer_components(activity_id,transfer_id,component_type,amount)
      values(p_activity_id,v_transfer,'prepayment',v_prepayment);
  end if;
  perform private.assert_component_total(v_transfer);
  perform private.phase5_rebuild_after_transfer(p_activity_id);
  update public.activities as act
    set financial_version=act.financial_version+1
    where act.id=p_activity_id
    returning act.financial_version into v_version;
  select coalesce(pa.balance,0) into v_balance
    from public.prepayment_accounts pa
    where pa.activity_id=p_activity_id
      and pa.owner_participant_id=p_owner
      and pa.custodian_participant_id=p_custodian
      and pa.currency=v_currency;
  v_result:=jsonb_build_object('transfer_id',v_transfer,'settlement_amount',v_settlement,
    'prepayment_amount',v_prepayment,'new_balance',coalesce(v_balance,0),
    'currency',v_currency,'financial_version',v_version);
  update public.transfers set request_result=v_result where id=v_transfer;
  return query select v_transfer,v_settlement,v_prepayment,coalesce(v_balance,0),v_currency,v_version;
end;
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
  v_archived timestamptz; v_version bigint; v_is_deleted boolean; v_balance numeric(20,4); v_transfer uuid;
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
  select a.base_currency,a.archived_at,a.financial_version,a.is_deleted into v_base,v_archived,v_version,v_is_deleted
    from public.activities a where a.id=p_activity_id for update;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  select t.* into v_existing from public.transfers t where t.activity_id=p_activity_id and t.request_id=p_request_id for update;
  if found then
    if v_existing.request_payload is distinct from v_payload or v_existing.type<>'prepayment_return'::public.transfer_type
       or v_existing.recorded_by is distinct from v_user then
      raise exception using errcode='23505',message='prepayment return request id was already used with a different payload or actor'; end if;
    v_result:=v_existing.request_result;
    if v_result is null then raise exception using errcode='55000',message='idempotent result is unavailable'; end if;
    return query select (v_result->>'transfer_id')::uuid,(v_result->>'amount')::numeric,
      (v_result->>'currency')::character(3),(v_result->>'remaining_balance')::numeric,
      (v_result->>'financial_version')::bigint; return;
  end if;
  if v_is_deleted then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if;
  perform private.assert_financial_version(p_activity_id,p_expected_version);
  v_currency:=pg_catalog.upper(pg_catalog.btrim(p_currency));
  if v_currency is null or v_currency !~ '^[A-Z]{3}$' then raise exception using errcode='22023',message='invalid prepayment return currency'; end if;
  if v_currency=v_base and p_amount<>pg_catalog.round(p_amount,1) then
    raise exception using errcode='22023',message='base-currency amount must have one decimal place';
  end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=v_user) then
    raise exception using errcode='42501',message='caller is not an activity member'; end if;
  perform private.authorize_phase5_actor(p_activity_id,p_custodian,p_owner,p_behalf);
  perform private.assert_large_prepayment_activity(p_activity_id);
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

create or replace function private.create_prepayment_impl(aid uuid,owner uuid,cust uuid,amt numeric(20,1),at_time timestamptz,behalf uuid) returns table(transfer_id uuid,settlement_amount numeric(20,1),prepayment_amount numeric(20,1),currency character(3),financial_version bigint) language plpgsql volatile security definer set search_path='' as $function$
#variable_conflict use_column
declare debt numeric:=0; st numeric; pp numeric; tid uuid; cur character(3); ar timestamptz; cnt integer; ver bigint; u uuid:=(select auth.uid()); begin if amt is null or amt<=0 or owner is null or cust is null or owner=cust or at_time is null then raise exception using errcode='22023',message='invalid prepayment'; end if; perform private.lock_debt_projection_activity(aid); select base_currency,archived_at into cur,ar from public.activities where id=aid and not is_deleted for update; if not found then raise exception using errcode='P0002',message='activity was not found'; end if; if ar is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if; perform 1 from public.participants where activity_id=aid and id in(owner,cust) and not is_deleted order by id for update; get diagnostics cnt=row_count; if cnt<>2 then raise exception using errcode='P0002',message='transfer participant was not found'; end if; perform private.authorize_phase5_actor(aid,owner,cust,behalf); perform private.assert_large_prepayment_activity(aid); select coalesce(amount,0) into debt from public.bilateral_debts where activity_id=aid and debtor_participant_id=owner and creditor_participant_id=cust; st:=least(amt,coalesce(debt,0)); pp:=amt-st; insert into public.transfers(activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,recorded_by,on_behalf_of_participant_id) values(aid,owner,cust,'prepayment',amt,cur,at_time,u,behalf) returning id into tid; if st>0 then insert into public.transfer_components(activity_id,transfer_id,component_type,amount) values(aid,tid,'settlement',st); end if; if pp>0 then insert into public.transfer_components(activity_id,transfer_id,component_type,amount) values(aid,tid,'prepayment',pp); end if; perform private.assert_component_total(tid); perform private.phase5_rebuild_after_transfer(aid); update public.activities set financial_version=financial_version+1 where id=aid returning financial_version into ver; return query select tid,st,pp,cur,ver; end;$function$;

create or replace function private.create_prepayment_return_impl(aid uuid,owner uuid,cust uuid,amt numeric(20,1),at_time timestamptz,behalf uuid) returns table(transfer_id uuid,amount numeric(20,1),currency character(3),financial_version bigint) language plpgsql volatile security definer set search_path='' as $function$
#variable_conflict use_column
declare bal numeric; tid uuid; cur character(3); ar timestamptz; cnt integer; ver bigint; u uuid:=(select auth.uid()); begin if amt is null or amt<=0 or owner is null or cust is null or owner=cust or at_time is null then raise exception using errcode='22023',message='invalid prepayment return'; end if; perform private.lock_debt_projection_activity(aid); select base_currency,archived_at into cur,ar from public.activities where id=aid and not is_deleted for update; if not found then raise exception using errcode='P0002',message='activity was not found'; end if; if ar is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if; perform 1 from public.participants where activity_id=aid and id in(owner,cust) and not is_deleted order by id for update; get diagnostics cnt=row_count; if cnt<>2 then raise exception using errcode='P0002',message='transfer participant was not found'; end if; perform private.authorize_phase5_actor(aid,cust,owner,behalf); perform private.assert_large_prepayment_activity(aid); select balance into bal from public.prepayment_accounts where activity_id=aid and owner_participant_id=owner and custodian_participant_id=cust; if bal is null or amt>bal then raise exception using errcode='23514',message='prepayment return exceeds available balance'; end if; insert into public.transfers(activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,recorded_by,on_behalf_of_participant_id) values(aid,cust,owner,'prepayment_return',amt,cur,at_time,u,behalf) returning id into tid; insert into public.transfer_components(activity_id,transfer_id,component_type,amount) values(aid,tid,'prepayment_return',amt); perform private.assert_component_total(tid); perform private.phase5_rebuild_after_transfer(aid); update public.activities set financial_version=financial_version+1 where id=aid returning financial_version into ver; return query select tid,amt,cur,ver; end;$function$;

commit;
