-- Restore a voided transfer as the same immutable fact. Validation runs while
-- the fact is still voided, so current debt/prepayment/final-plan state is the
-- source of truth and every projection change remains atomic.

alter table public.audit_logs
  drop constraint audit_logs_action_check;

alter table public.audit_logs
  add constraint audit_logs_action_check check (action in (
    'activity.create','activity.update','activity.delete','activity.archive','activity.unarchive',
    'activity.creator_transfer','member.join','member.remove',
    'participant.create','participant.update','participant.delete',
    'claim.create','claim.remove','expense.create','expense.update',
    'expense.delete','expense.restore','transfer.create','transfer.void','transfer.restore',
    'dispute.create','dispute.remove','attachment.create','attachment.complete',
    'attachment.delete'
  ));

create or replace function private.write_audit_log()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
declare
  aid uuid;
  act text;
  eid uuid;
  meta jsonb := '{}'::jsonb;
  uid uuid := (select auth.uid());
begin
  if tg_table_name='activities' then
    aid:=coalesce(new.id,old.id); eid:=aid;
    if tg_op='INSERT' then act:='activity.create';
    elsif new.is_deleted is distinct from old.is_deleted and new.is_deleted then act:='activity.delete';
    elsif new.archived_at is distinct from old.archived_at then act:=case when new.archived_at is null then 'activity.unarchive' else 'activity.archive' end;
    elsif new.created_by is distinct from old.created_by then act:='activity.creator_transfer';
    else act:='activity.update'; end if;
  elsif tg_table_name='activity_members' then
    aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id);
    act:=case when tg_op='INSERT' then 'member.join' else 'member.remove' end;
  elsif tg_table_name='participants' then
    aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id);
    act:=case when tg_op='INSERT' then 'participant.create' when new.is_deleted is distinct from old.is_deleted and new.is_deleted then 'participant.delete' else 'participant.update' end;
  elsif tg_table_name='participant_claims' then
    aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id);
    act:=case when tg_op='INSERT' then 'claim.create' else 'claim.remove' end;
  elsif tg_table_name='expenses' then
    select lu.activity_id into aid from public.ledger_units lu where lu.id=coalesce(new.ledger_unit_id,old.ledger_unit_id);
    eid:=coalesce(new.id,old.id);
    act:=case when tg_op='INSERT' then 'expense.create' when new.is_deleted is distinct from old.is_deleted and new.is_deleted then 'expense.delete' when new.is_deleted is distinct from old.is_deleted and not new.is_deleted then 'expense.restore' else 'expense.update' end;
  elsif tg_table_name='transfers' then
    aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id);
    if tg_op='INSERT' then
      act:='transfer.create';
    elsif new.is_voided is distinct from old.is_voided and new.is_voided then
      act:='transfer.void';
      meta:=jsonb_build_object(
        'void_reason',new.void_reason,
        'voided_at',new.voided_at,
        'voided_by',new.voided_by
      );
    elsif new.is_voided is distinct from old.is_voided and not new.is_voided then
      act:='transfer.restore';
      meta:=jsonb_build_object(
        'restore_reason',nullif(current_setting('app.transfer_restore_reason',true),''),
        'previous_void_reason',old.void_reason,
        'previous_voided_at',old.voided_at,
        'previous_voided_by',old.voided_by
      );
    else
      act:='transfer.create';
    end if;
  elsif tg_table_name='transfer_disputes' then
    aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id);
    act:=case when tg_op='INSERT' then 'dispute.create' when new.resolved_at is distinct from old.resolved_at and new.resolved_at is not null then 'dispute.remove' else 'dispute.create' end;
  elsif tg_table_name='attachments' then
    aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id);
    act:=case when tg_op='INSERT' then 'attachment.create' when new.status='ready' and old.status='pending' then 'attachment.complete' when new.status='deleted' and old.status is distinct from new.status then 'attachment.delete' else 'attachment.complete' end;
  else
    if tg_op='DELETE' then return old; else return new; end if;
  end if;

  insert into public.audit_logs(activity_id,actor_user_id,action,entity_type,entity_id,metadata)
  values(aid,uid,act,tg_table_name,eid,meta);
  if tg_op='DELETE' then return old; else return new; end if;
end;
$function$;

create or replace function private.restore_transfer_impl(
  p_transfer_id uuid,
  p_restore_reason text
)
returns table(transfer_id uuid, restored boolean, financial_version bigint)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_uid uuid := (select auth.uid());
  v_activity_id uuid;
  v_type public.transfer_type;
  v_from uuid;
  v_to uuid;
  v_amount numeric(20,1);
  v_recorded_by uuid;
  v_is_voided boolean;
  v_creator uuid;
  v_archived_at timestamptz;
  v_current_version bigint;
  v_settlement_amount numeric(20,1);
  v_prepayment_amount numeric(20,1);
  v_return_amount numeric(20,1);
  v_current_debt numeric(20,1);
  v_current_balance numeric(20,1);
  v_plan_count integer;
  v_plan_amount numeric(20,1);
  v_plan_ordinary numeric(20,1);
  v_plan_return numeric(20,1);
  v_new_version bigint;
begin
  if v_uid is null then
    raise exception using errcode='28000',message='authentication is required';
  end if;
  if p_restore_reason is null or pg_catalog.length(pg_catalog.btrim(p_restore_reason))=0 then
    raise exception using errcode='22023',message='restore reason is required';
  end if;

  select t.activity_id into v_activity_id
  from public.transfers t where t.id=p_transfer_id;
  if not found then
    raise exception using errcode='P0002',message='transfer was not found';
  end if;

  perform private.lock_debt_projection_activity(v_activity_id);
  select t.type,t.from_participant_id,t.to_participant_id,t.amount,t.recorded_by,t.is_voided,
         a.created_by,a.archived_at,a.financial_version
    into v_type,v_from,v_to,v_amount,v_recorded_by,v_is_voided,
         v_creator,v_archived_at,v_current_version
  from public.transfers t
  join public.activities a on a.id=t.activity_id
  where t.id=p_transfer_id and not a.is_deleted
    and t.type in ('settlement','prepayment','prepayment_return','final_settlement')
  for update of t,a;
  if not found then
    raise exception using errcode='P0002',message='financial transfer was not found';
  end if;
  if v_archived_at is not null then
    raise exception using errcode='55000',message='archived activity is read-only';
  end if;
  if not exists(
    select 1 from public.activity_members m
    where m.activity_id=v_activity_id and m.user_id=v_uid
  ) then
    raise exception using errcode='42501',message='caller is not an activity member';
  end if;
  if v_uid<>v_creator and v_uid<>v_recorded_by then
    raise exception using errcode='42501',message='member may restore only a transfer they recorded';
  end if;
  if not v_is_voided then
    return query select p_transfer_id,false,v_current_version;
    return;
  end if;

  perform private.assert_component_total(p_transfer_id);
  select
    coalesce(sum(c.amount) filter(where c.component_type='settlement'),0)::numeric(20,1),
    coalesce(sum(c.amount) filter(where c.component_type='prepayment'),0)::numeric(20,1),
    coalesce(sum(c.amount) filter(where c.component_type='prepayment_return'),0)::numeric(20,1)
    into v_settlement_amount,v_prepayment_amount,v_return_amount
  from public.transfer_components c where c.transfer_id=p_transfer_id;

  if v_type in ('settlement','prepayment') and v_settlement_amount>0 then
    select coalesce((
      select b.amount from public.bilateral_debts b
      where b.activity_id=v_activity_id
        and b.debtor_participant_id=v_from
        and b.creditor_participant_id=v_to
    ),0)::numeric(20,1) into v_current_debt;
    if v_current_debt<v_settlement_amount then
      raise exception using errcode='23514',message='transfer settlement component exceeds current bilateral debt';
    end if;
  elsif v_type='prepayment_return' then
    select coalesce((
      select pa.balance from public.prepayment_accounts pa
      where pa.activity_id=v_activity_id
        and pa.owner_participant_id=v_to
        and pa.custodian_participant_id=v_from
    ),0)::numeric(20,1) into v_current_balance;
    if v_current_balance<v_return_amount then
      raise exception using errcode='23514',message='prepayment return exceeds current available balance';
    end if;
  elsif v_type='final_settlement' then
    select count(*),coalesce(max(p.amount),0),coalesce(max(p.ordinary_amount),0),
           coalesce(max(p.prepayment_return_amount),0)
      into v_plan_count,v_plan_amount,v_plan_ordinary,v_plan_return
    from private.build_final_settlement_plan(v_activity_id) p
    where p.from_participant_id=v_from and p.to_participant_id=v_to;
    if v_plan_count<>1 or v_plan_amount<>v_amount
       or v_plan_ordinary<>v_settlement_amount or v_plan_return<>v_return_amount then
      raise exception using errcode='23514',message='voided final settlement no longer matches current plan; preview and execute a new final settlement';
    end if;

    if exists(
      (select f.path_no,f.hop_no,f.from_participant_id,f.to_participant_id,f.amount
       from public.final_settlement_paths f
       where f.transfer_id=p_transfer_id and f.component_type='settlement')
      except
      (select flow.path_no,h.hop_no,h.from_participant_id,h.to_participant_id,h.amount::numeric(20,1)
       from private.build_final_settlement_flow(v_activity_id) flow
       cross join lateral jsonb_to_recordset(flow.hops) as h(
         hop_no integer,from_participant_id uuid,to_participant_id uuid,amount numeric
       )
       where flow.from_participant_id=v_from and flow.to_participant_id=v_to)
    ) or exists(
      (select flow.path_no,h.hop_no,h.from_participant_id,h.to_participant_id,h.amount::numeric(20,1)
       from private.build_final_settlement_flow(v_activity_id) flow
       cross join lateral jsonb_to_recordset(flow.hops) as h(
         hop_no integer,from_participant_id uuid,to_participant_id uuid,amount numeric
       )
       where flow.from_participant_id=v_from and flow.to_participant_id=v_to)
      except
      (select f.path_no,f.hop_no,f.from_participant_id,f.to_participant_id,f.amount
       from public.final_settlement_paths f
       where f.transfer_id=p_transfer_id and f.component_type='settlement')
    ) then
      raise exception using errcode='23514',message='voided final settlement path no longer matches current plan; preview and execute a new final settlement';
    end if;

    if v_return_amount>0 then
      if (select count(*) from public.final_settlement_paths f
          where f.transfer_id=p_transfer_id and f.component_type='prepayment_return'
            and f.from_participant_id=v_from and f.to_participant_id=v_to
            and f.amount=v_return_amount and f.hop_no=1)<>1
         or (select count(*) from public.final_settlement_paths f
             where f.transfer_id=p_transfer_id and f.component_type='prepayment_return')<>1 then
        raise exception using errcode='23514',message='voided final settlement return path no longer matches its immutable component';
      end if;
    elsif exists(
      select 1 from public.final_settlement_paths f
      where f.transfer_id=p_transfer_id and f.component_type='prepayment_return'
    ) then
      raise exception using errcode='23514',message='voided final settlement has an unexpected return path';
    end if;
  end if;

  perform set_config('app.transfer_restore_reason',pg_catalog.btrim(p_restore_reason),true);
  update public.transfers t set
    is_voided=false,
    voided_at=null,
    voided_by=null,
    void_reason=null
  where t.id=p_transfer_id;

  perform private.phase5_rebuild_after_transfer(v_activity_id);
  update public.activities a
  set financial_version=a.financial_version+1
  where a.id=v_activity_id
  returning a.financial_version into v_new_version;

  return query select p_transfer_id,true,v_new_version;
end;
$function$;

create or replace function public.restore_transfer(
  transfer_id uuid,
  restore_reason text
)
returns table(transfer_id uuid, restored boolean, financial_version bigint)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select * from private.restore_transfer_impl($1,$2);
$function$;

revoke all on function private.restore_transfer_impl(uuid,text),public.restore_transfer(uuid,text)
  from public,anon,authenticated;
grant execute on function private.restore_transfer_impl(uuid,text),public.restore_transfer(uuid,text)
  to authenticated;

comment on function public.restore_transfer(uuid,text) is
  'Restores one voided transfer fact after validating current debt, prepayment, or exact final-settlement plan state.';
