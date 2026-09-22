begin;

-- The settlement-mode contract was added after the original final-settlement
-- functions.  Replace both implementations so every final_settlement fact is
-- written with the only mode permitted by transfers' type-consistency check.
-- Keep the existing signatures, definer/search_path settings, authorization,
-- locking, path accounting, and result shape unchanged.
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
  v_currency:=private.validate_financial_currency(p_activity_id,p_currency);
  if v_mode='original_currency' and v_currency=v_base then null; end if;
  if v_currency=v_base and p_amount<>pg_catalog.round(p_amount,1) then raise exception using errcode='22023',message='base-currency amount must have one decimal place'; end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=v_user) then raise exception using errcode='42501',message='caller is not an activity member'; end if;
  perform private.authorize_phase5_actor(p_activity_id,p_from,p_to,p_behalf);

  -- Check the idempotency key before the optimistic-version assertion.  A
  -- retry after a committed request necessarily carries the now-stale
  -- original version, but must still return the committed result.
  select t.* into v_existing from public.transfers t where t.activity_id=p_activity_id and t.request_id=p_request_id for update;
  if found then
    if v_existing.request_payload is distinct from v_payload or v_existing.type<>'final_settlement'::public.transfer_type then raise exception using errcode='23505',message='final settlement request id was already used with a different payload'; end if;
    v_result:=v_existing.request_result; if v_result is null then raise exception using errcode='55000',message='idempotent result is unavailable'; end if;
    return query select (v_result->>'transfer_id')::uuid,(v_result->>'amount')::numeric,(v_result->>'currency')::character(3),(v_result->>'mode')::text,(v_result->>'financial_version')::bigint; return;
  end if;
  perform private.assert_financial_version(p_activity_id,p_expected_version);
  select p.* into v_plan from private.build_final_settlement_plan_v2(p_activity_id,v_mode) p
    where p.from_participant_id=p_from and p.to_participant_id=p_to and p.amount=p_amount and p.currency=v_currency;
  if not found then raise exception using errcode='23514',message='final settlement does not match current plan'; end if;
  -- base_unified ordinary debt is always settled in the activity base
  -- currency.  A pure prepayment return is different: its currency is the
  -- prepayment account's own currency and must not be converted implicitly.
  if v_mode='base_unified' and v_plan.ordinary_amount>0 and v_currency<>v_base then
    raise exception using errcode='22023',message='base_unified ordinary settlement must use base currency';
  end if;
  insert into public.transfers(activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,recorded_by,on_behalf_of_participant_id,request_id,request_payload,settlement_mode)
    values(p_activity_id,p_from,p_to,'final_settlement',p_amount,v_currency,p_occurred_at,v_user,p_behalf,p_request_id,v_payload,'FINAL_SETTLEMENT') returning id into v_transfer;
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

-- Legacy clients call this implementation through create_final_settlement,
-- execute_final_settlement, or execute_final_settlement_item.  Keep the old
-- contract intact while writing the new required mode explicitly.
create or replace function private.create_final_settlement_impl(
  p_activity_id uuid, p_from_participant_id uuid, p_to_participant_id uuid,
  p_amount numeric(20,1), p_occurred_at timestamptz,
  p_on_behalf_of_participant_id uuid
)
returns table(transfer_id uuid, amount numeric(20,1), currency character(3), financial_version bigint)
language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_plan record; v_flow record; v_hop record; v_currency character(3); v_archived_at timestamptz;
  v_type public.activity_type; v_transfer_id uuid; v_version bigint;
  v_uid uuid := (select auth.uid()); v_path_order integer := 0; v_source_expense uuid;
  v_ordinary_total numeric(20,1); v_return_path_no integer;
begin
  if p_amount is null or p_amount <= 0 or p_from_participant_id is null
     or p_to_participant_id is null or p_from_participant_id = p_to_participant_id
     or p_occurred_at is null then
    raise exception using errcode = '22023', message = 'invalid final settlement';
  end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  select a.type, a.base_currency, a.archived_at
    into v_type, v_currency, v_archived_at
  from public.activities a where a.id = p_activity_id and not a.is_deleted for update;
  if not found then raise exception using errcode = 'P0002', message = 'activity was not found'; end if;
  if v_type <> 'large'::public.activity_type then
    raise exception using errcode = '23514', message = 'final settlement requires a large activity';
  end if;
  if v_archived_at is not null then raise exception using errcode = '55000', message = 'archived activity is read-only'; end if;
  perform private.authorize_phase5_actor(p_activity_id, p_from_participant_id,
    p_to_participant_id, p_on_behalf_of_participant_id);
  select plan.* into v_plan from private.build_final_settlement_plan(p_activity_id) plan
    where plan.from_participant_id = p_from_participant_id
      and plan.to_participant_id = p_to_participant_id
      and plan.amount = p_amount;
  if not found then raise exception using errcode = '23514', message = 'final settlement does not match current plan'; end if;

  select coalesce(sum(f.amount),0)::numeric(20,1) into v_ordinary_total
  from private.build_final_settlement_flow(p_activity_id) f
  where f.from_participant_id=p_from_participant_id and f.to_participant_id=p_to_participant_id;
  if v_ordinary_total <> v_plan.ordinary_amount then
    raise exception using errcode='23514', message='final settlement flow changed while validating plan';
  end if;

  insert into public.transfers(activity_id, from_participant_id, to_participant_id,
    type, amount, currency, occurred_at, recorded_by, on_behalf_of_participant_id,
    settlement_mode)
  values(p_activity_id, p_from_participant_id, p_to_participant_id,
    'final_settlement', p_amount, v_currency, p_occurred_at, v_uid,
    p_on_behalf_of_participant_id, 'FINAL_SETTLEMENT') returning id into v_transfer_id;
  if v_plan.ordinary_amount > 0 then
    insert into public.transfer_components(activity_id, transfer_id, component_type, amount)
    values(p_activity_id, v_transfer_id, 'settlement', v_plan.ordinary_amount);
  end if;
  if v_plan.prepayment_return_amount > 0 then
    insert into public.transfer_components(activity_id, transfer_id, component_type, amount)
    values(p_activity_id, v_transfer_id, 'prepayment_return', v_plan.prepayment_return_amount);
  end if;
  perform private.assert_component_total(v_transfer_id);

  -- Persist every residual-flow path and every capacity-limited hop exactly
  -- as emitted by the validator; no direct edge is fabricated.
  for v_flow in select f.* from private.build_final_settlement_flow(p_activity_id) f
    where f.from_participant_id=p_from_participant_id and f.to_participant_id=p_to_participant_id
    order by f.path_no
  loop
    for v_hop in select * from jsonb_to_recordset(v_flow.hops) as h(hop_no integer,from_participant_id uuid,to_participant_id uuid,amount numeric)
    loop
      v_path_order := v_path_order + 1;
      select ed.expense_id into v_source_expense from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
      where ed.activity_id=p_activity_id and ed.debtor_participant_id=v_hop.from_participant_id and ed.creditor_participant_id=v_hop.to_participant_id
      order by e.occurred_at,e.created_at,e.id limit 1;
      insert into public.final_settlement_paths(activity_id,transfer_id,path_order,path_no,hop_no,from_participant_id,to_participant_id,amount,component_type,source_expense_id)
      values(p_activity_id,v_transfer_id,v_path_order,v_flow.path_no,v_hop.hop_no,v_hop.from_participant_id,v_hop.to_participant_id,v_hop.amount,'settlement',v_source_expense);
    end loop;
  end loop;
  if v_plan.prepayment_return_amount > 0 then
    select coalesce(max(f.path_no),0)+1 into v_return_path_no
    from public.final_settlement_paths f where f.transfer_id=v_transfer_id;
    v_path_order := v_path_order + 1;
    insert into public.final_settlement_paths(activity_id, transfer_id, path_order, path_no, hop_no,
      from_participant_id, to_participant_id, amount, component_type)
    values(p_activity_id, v_transfer_id, v_path_order, v_return_path_no, 1, p_from_participant_id,
      p_to_participant_id, v_plan.prepayment_return_amount, 'prepayment_return');
  end if;

  perform private.phase5_rebuild_after_transfer(p_activity_id);
  update public.activities a set financial_version = a.financial_version + 1
    where a.id = p_activity_id returning a.financial_version into v_version;
  return query select v_transfer_id, p_amount, v_currency, v_version;
end;
$function$;

commit;
