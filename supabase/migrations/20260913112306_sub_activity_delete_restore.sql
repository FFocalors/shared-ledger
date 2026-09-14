begin;

-- Sub-activities are soft-deleted ledger units.  The source facts (Expenses,
-- Payments, Splits, Transfers and Attachments) remain immutable; projection
-- rows are rebuilt from the surviving facts under the same Activity advisory
-- lock used by every financial write path.

alter table public.audit_logs
  drop constraint if exists audit_logs_action_check;

alter table public.audit_logs
  add constraint audit_logs_action_check check (action in (
    'activity.create','activity.update','activity.delete','activity.archive','activity.unarchive',
    'activity.creator_transfer','member.join','member.remove',
    'participant.create','participant.update','participant.delete',
    'claim.create','claim.remove','expense.create','expense.update',
    'expense.delete','expense.restore','transfer.create','transfer.void','transfer.restore',
    'ledger_unit.delete','ledger_unit.restore',
    'dispute.create','dispute.remove','attachment.create','attachment.complete',
    'attachment.delete'
  ));

-- Extend the existing append-only audit trigger with the two ledger-unit
-- lifecycle events.  The trigger is restricted to is_deleted metadata, so a
-- future name/type edit cannot accidentally emit an unsupported action.
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
  elsif tg_table_name='ledger_units' then
    aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id);
    act:=case when new.is_deleted then 'ledger_unit.delete' else 'ledger_unit.restore' end;
    meta:=jsonb_build_object(
      'deleted_at',new.deleted_at,
      'deleted_by',new.deleted_by
    );
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
      meta:=jsonb_build_object('void_reason',new.void_reason,'voided_at',new.voided_at,'voided_by',new.voided_by);
    elsif new.is_voided is distinct from old.is_voided and not new.is_voided then
      act:='transfer.restore';
      meta:=jsonb_build_object('restore_reason',nullif(current_setting('app.transfer_restore_reason',true),''),'previous_void_reason',old.void_reason,'previous_voided_at',old.voided_at,'previous_voided_by',old.voided_by);
    else act:='transfer.create'; end if;
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

drop trigger if exists audit_ledger_units on public.ledger_units;
create trigger audit_ledger_units
after update of is_deleted, deleted_at, deleted_by on public.ledger_units
for each row execute function private.write_audit_log();

create or replace function private.delete_sub_activity_impl(p_sub_activity_id uuid)
returns table(
  sub_activity_id uuid,
  activity_id uuid,
  changed boolean,
  is_deleted boolean,
  financial_version bigint
)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_uid uuid := (select auth.uid());
  v_activity_id uuid;
  v_activity_type public.activity_type;
  v_archived_at timestamptz;
  v_activity_deleted boolean;
  v_unit_type public.ledger_unit_type;
  v_was_deleted boolean;
  v_version bigint;
begin
  if v_uid is null then
    raise exception using errcode = '28000', message = 'authentication is required';
  end if;
  if p_sub_activity_id is null then
    raise exception using errcode = '22023', message = 'sub_activity_id is required';
  end if;

  -- Resolve the Activity before taking the shared financial lock.  The row
  -- lock below closes races with archive/delete and serializes this lifecycle
  -- operation with all other Activity financial writes.
  select lu.activity_id
    into v_activity_id
  from public.ledger_units lu
  where lu.id = p_sub_activity_id;
  if not found then
    raise exception using errcode = 'P0002', message = 'sub-activity was not found';
  end if;

  perform private.lock_debt_projection_activity(v_activity_id);

  select a.type, a.archived_at, a.is_deleted, a.financial_version,
         lu.type, lu.is_deleted
    into v_activity_type, v_archived_at, v_activity_deleted, v_version,
         v_unit_type, v_was_deleted
  from public.activities a
  join public.ledger_units lu on lu.activity_id = a.id
  where a.id = v_activity_id and lu.id = p_sub_activity_id
  for update of a, lu;

  if not found or v_activity_deleted then
    raise exception using errcode = 'P0002', message = 'activity was not found';
  end if;
  if v_archived_at is not null then
    raise exception using errcode = '55000', message = 'archived activity is read-only';
  end if;
  if v_activity_type <> 'large'::public.activity_type
     or v_unit_type <> 'sub_activity'::public.ledger_unit_type then
    raise exception using errcode = '22023', message = 'only a large activity sub-activity may be changed';
  end if;
  if not exists (
    select 1 from public.activity_members m
    where m.activity_id = v_activity_id and m.user_id = v_uid
  ) then
    raise exception using errcode = '42501', message = 'caller is not an activity member';
  end if;

  if v_was_deleted then
    return query select p_sub_activity_id, v_activity_id, false, true, v_version;
    return;
  end if;

  update public.ledger_units
  set is_deleted = true,
      deleted_at = pg_catalog.now(),
      deleted_by = v_uid
  where id = p_sub_activity_id;

  perform private.rebuild_activity_debt_projection(v_activity_id);

  update public.activities a
  set financial_version = a.financial_version + 1
  where a.id = v_activity_id
  returning a.financial_version into v_version;

  return query select p_sub_activity_id, v_activity_id, true, true, v_version;
end;
$function$;

create or replace function private.restore_sub_activity_impl(p_sub_activity_id uuid)
returns table(
  sub_activity_id uuid,
  activity_id uuid,
  changed boolean,
  is_deleted boolean,
  financial_version bigint
)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_uid uuid := (select auth.uid());
  v_activity_id uuid;
  v_activity_type public.activity_type;
  v_archived_at timestamptz;
  v_activity_deleted boolean;
  v_unit_type public.ledger_unit_type;
  v_was_deleted boolean;
  v_version bigint;
begin
  if v_uid is null then
    raise exception using errcode = '28000', message = 'authentication is required';
  end if;
  if p_sub_activity_id is null then
    raise exception using errcode = '22023', message = 'sub_activity_id is required';
  end if;

  select lu.activity_id into v_activity_id
  from public.ledger_units lu where lu.id = p_sub_activity_id;
  if not found then
    raise exception using errcode = 'P0002', message = 'sub-activity was not found';
  end if;

  perform private.lock_debt_projection_activity(v_activity_id);

  select a.type, a.archived_at, a.is_deleted, a.financial_version,
         lu.type, lu.is_deleted
    into v_activity_type, v_archived_at, v_activity_deleted, v_version,
         v_unit_type, v_was_deleted
  from public.activities a
  join public.ledger_units lu on lu.activity_id = a.id
  where a.id = v_activity_id and lu.id = p_sub_activity_id
  for update of a, lu;

  if not found or v_activity_deleted then
    raise exception using errcode = 'P0002', message = 'activity was not found';
  end if;
  if v_archived_at is not null then
    raise exception using errcode = '55000', message = 'archived activity is read-only';
  end if;
  if v_activity_type <> 'large'::public.activity_type
     or v_unit_type <> 'sub_activity'::public.ledger_unit_type then
    raise exception using errcode = '22023', message = 'only a large activity sub-activity may be changed';
  end if;
  if not exists (
    select 1 from public.activity_members m
    where m.activity_id = v_activity_id and m.user_id = v_uid
  ) then
    raise exception using errcode = '42501', message = 'caller is not an activity member';
  end if;

  if not v_was_deleted then
    return query select p_sub_activity_id, v_activity_id, false, false, v_version;
    return;
  end if;

  update public.ledger_units
  set is_deleted = false,
      deleted_at = null,
      deleted_by = null
  where id = p_sub_activity_id;

  perform private.rebuild_activity_debt_projection(v_activity_id);

  update public.activities a
  set financial_version = a.financial_version + 1
  where a.id = v_activity_id
  returning a.financial_version into v_version;

  return query select p_sub_activity_id, v_activity_id, true, false, v_version;
end;
$function$;

create or replace function public.delete_sub_activity(sub_activity_id uuid)
returns table(
  sub_activity_id uuid,
  activity_id uuid,
  changed boolean,
  is_deleted boolean,
  financial_version bigint
)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select * from private.delete_sub_activity_impl($1);
$function$;

create or replace function public.restore_sub_activity(sub_activity_id uuid)
returns table(
  sub_activity_id uuid,
  activity_id uuid,
  changed boolean,
  is_deleted boolean,
  financial_version bigint
)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select * from private.restore_sub_activity_impl($1);
$function$;

-- Lifecycle is RPC-only.  Keep the existing member-readable SELECT surface,
-- but ensure API roles cannot bypass the lock, projection rebuild, versioning,
-- and audit trail with direct UPDATE/DELETE.
revoke insert, update, delete on table public.ledger_units from public, anon, authenticated;
revoke all on function private.delete_sub_activity_impl(uuid), private.restore_sub_activity_impl(uuid)
  from public, anon, authenticated;
grant execute on function private.delete_sub_activity_impl(uuid), private.restore_sub_activity_impl(uuid)
  to authenticated;
revoke all on function public.delete_sub_activity(uuid), public.restore_sub_activity(uuid)
  from public, anon, authenticated;
grant execute on function public.delete_sub_activity(uuid), public.restore_sub_activity(uuid)
  to authenticated;

commit;
