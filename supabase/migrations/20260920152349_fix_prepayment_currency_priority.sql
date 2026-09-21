-- The previous currency migration attempted to drop the legacy constraint
-- using the untruncated name.  PostgreSQL truncated that identifier, so the
-- old three-column uniqueness must be removed before two currency accounts can
-- coexist for one owner/custodian pair.
alter table public.prepayment_accounts
  drop constraint if exists prepayment_accounts_activity_id_owner_participant_id_custod_key,
  drop constraint if exists prepayment_accounts_activity_id_owner_participant_id_custodian_participant_id_key;
create unique index if not exists prepayment_accounts_activity_owner_custodian_currency_key
  on public.prepayment_accounts(activity_id, owner_participant_id, custodian_participant_id, currency);

-- Keep the projection rebuild logic unchanged except for account ordering:
-- same-currency prepayments must consume same-currency debts before the base
-- account is allowed to consume the remaining debt graph.
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
      select ed.id, ed.amount debt_base,
        coalesce(ed.original_amount,ed.amount)::numeric(20,4) debt_original,
        coalesce(ed.original_currency,v_base_currency)::character(3) debt_currency,
        coalesce(ed.fx_rate,1)::numeric(20,10) debt_fx,
        e.occurred_at,e.created_at,e.id expense_id,
        greatest(coalesce(ed.original_amount,ed.amount)
          -coalesce((select sum(coalesce(ta.original_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=ed.id),0)
          -coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu where pu.expense_debt_id=ed.id),0),0)::numeric(20,4) available_original,
        greatest(ed.amount
          -coalesce((select sum(coalesce(ta.base_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=ed.id),0)
          -coalesce((select sum(pu.base_amount) from public.prepayment_usages pu where pu.expense_debt_id=ed.id),0),0)::numeric(20,1) available_base
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

revoke all on function private.rebuild_prepayment_projections_locked(uuid)
  from public, anon, authenticated;

commit;
