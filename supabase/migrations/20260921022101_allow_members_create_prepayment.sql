begin;

-- Adding a prepayment is an activity-wide action.  Keep the actor contract for
-- settlement, prepayment return, and final settlement unchanged: those paths
-- still call private.authorize_phase5_actor and therefore still require the
-- existing claimed-party/on-behalf rules.

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
  v_cap numeric(20,4); v_balance numeric(20,4); v_ver bigint; v_participant_count integer;
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
  select a.base_currency,a.archived_at,a.financial_version
    into v_base,v_archived,v_ver
    from public.activities a
    where a.id=p_activity_id and not a.is_deleted;
  if not found then
    raise exception using errcode='P0002',message='activity was not found';
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
  v_participant_count integer;
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
  select a.base_currency,a.archived_at,a.financial_version into v_base,v_archived,v_version
    from public.activities a where a.id=p_activity_id and not a.is_deleted for update;
  if not found then
    raise exception using errcode='P0002',message='activity was not found';
  end if;
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
  -- Deliberately do not call the phase-5 actor gate here.  New prepayments
  -- are allowed for any two distinct activity participants.
  if p_request_id is not null then
    select t.* into v_existing
      from public.transfers t
      where t.activity_id=p_activity_id and t.request_id=p_request_id
      for update;
    if found then
      if v_existing.request_payload is distinct from v_payload
         or v_existing.type<>'prepayment'::public.transfer_type then
        raise exception using errcode='23505',message='prepayment request id was already used with a different payload';
      end if;
      v_result:=v_existing.request_result;
      if v_result is null then
        raise exception using errcode='55000',message='idempotent result is unavailable';
      end if;
      return query select (v_result->>'transfer_id')::uuid,(v_result->>'settlement_amount')::numeric,
        (v_result->>'prepayment_amount')::numeric,(v_result->>'new_balance')::numeric,
        (v_result->>'currency')::character(3),(v_result->>'financial_version')::bigint;
      return;
    end if;
  end if;
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
      values(p_activity_id,v_transfer,'settlement',v_settlement);
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

-- Keep the existing endpoint grants: the private implementation is callable
-- only by authenticated clients through the authenticated public RPC.
revoke all on function private.create_prepayment_v2_impl(
  uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid
) from public,anon,authenticated;
grant execute on function private.create_prepayment_v2_impl(
  uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid
) to authenticated;
revoke all on function public.preview_prepayment(uuid,uuid,uuid,numeric,character)
  from public,anon,authenticated;
grant execute on function public.preview_prepayment(uuid,uuid,uuid,numeric,character)
  to authenticated;

commit;
