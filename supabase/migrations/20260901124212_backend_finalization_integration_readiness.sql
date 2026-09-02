begin;

-- Phase 7: contract finalization.  This migration adds only the missing
-- collaboration/integration surfaces; financial facts and their existing
-- projection algorithms remain unchanged.

alter table public.activities add column if not exists participants_locked_at timestamptz;

-- Creator settings remain a direct RLS-protected update surface from Phase 1,
-- but archived/deleted Activities must be immutable even on that path.  The
-- archive RPC changes archived_at explicitly and is the only permitted
-- lifecycle exception.
create or replace function private.assert_activity_settings_writable()
returns trigger language plpgsql security definer set search_path='' as $function$
begin
  if old.is_deleted then raise exception using errcode='55000',message='deleted activity is read-only'; end if;
  if old.archived_at is not null and new.archived_at is not distinct from old.archived_at then
    raise exception using errcode='55000',message='archived activity is read-only';
  end if;
  return new;
end;
$function$;
drop trigger if exists activities_settings_writable on public.activities;
create trigger activities_settings_writable before update on public.activities
for each row execute function private.assert_activity_settings_writable();
revoke all on function private.assert_activity_settings_writable() from public,anon,authenticated;

-- A tiny, append-only collaboration audit.  It is deliberately not an event
-- store and never participates in a financial projection.
create table public.audit_logs (
  id uuid primary key default extensions.gen_random_uuid(),
  activity_id uuid references public.activities(id) on delete set null,
  actor_user_id uuid references auth.users(id) on delete set null,
  action text not null check (action in (
    'activity.create','activity.update','activity.delete','activity.archive','activity.unarchive',
    'activity.creator_transfer','member.join','member.remove',
    'participant.create','participant.update','participant.delete',
    'claim.create','claim.remove','expense.create','expense.update',
    'expense.delete','expense.restore','transfer.create','transfer.void',
    'dispute.create','dispute.remove','attachment.create','attachment.complete',
    'attachment.delete'
  )),
  entity_type text not null,
  entity_id uuid,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default pg_catalog.now()
);
create index audit_logs_activity_created_idx on public.audit_logs(activity_id, created_at desc, id);
create index audit_logs_entity_idx on public.audit_logs(entity_type, entity_id, created_at desc);
alter table public.audit_logs enable row level security;
create policy audit_logs_select_member on public.audit_logs for select to authenticated
  using (activity_id is not null and (select private.is_activity_member(activity_id)));
revoke all on public.audit_logs from public, anon, authenticated;
grant select on public.audit_logs to authenticated;
grant all on public.audit_logs to service_role;

-- Minimal dispute marker.  A dispute is metadata only: no financial table is
-- updated and financial_version is intentionally untouched.
create table public.transfer_disputes (
  id uuid primary key default extensions.gen_random_uuid(),
  activity_id uuid not null references public.activities(id) on delete restrict,
  transfer_id uuid not null,
  participant_id uuid not null,
  disputed_by uuid not null references auth.users(id) on delete restrict,
  note text,
  created_at timestamptz not null default pg_catalog.now(),
  resolved_at timestamptz,
  resolved_by uuid references auth.users(id) on delete set null,
  constraint transfer_disputes_transfer_fk foreign key (transfer_id, activity_id)
    references public.transfers(id, activity_id) on delete cascade,
  constraint transfer_disputes_participant_fk foreign key (activity_id, participant_id)
    references public.participants(activity_id, id) on delete restrict,
  constraint transfer_disputes_participant_distinct check (participant_id is not null),
  unique (transfer_id, participant_id)
);
create index transfer_disputes_activity_idx on public.transfer_disputes(activity_id, created_at desc);
create index transfer_disputes_transfer_idx on public.transfer_disputes(transfer_id);
alter table public.transfer_disputes enable row level security;
create policy transfer_disputes_select_member on public.transfer_disputes for select to authenticated
  using ((select private.is_activity_member(activity_id)));
revoke all on public.transfer_disputes from public, anon, authenticated;
grant select on public.transfer_disputes to authenticated;
grant all on public.transfer_disputes to service_role;

-- Attachment metadata is the authoritative Activity boundary.  The actual
-- bytes are written through the Storage API, never by direct storage DML.
create table public.attachments (
  id uuid primary key default extensions.gen_random_uuid(),
  activity_id uuid not null references public.activities(id) on delete restrict,
  ledger_unit_id uuid not null,
  expense_id uuid references public.expenses(id) on delete restrict,
  kind text not null default 'image' check (kind = 'image'),
  storage_bucket text not null default 'activity-attachments',
  storage_path text not null unique,
  original_filename text,
  mime_type text not null check (mime_type in ('image/jpeg','image/png','image/webp')),
  size_bytes bigint check (size_bytes is null or (size_bytes > 0 and size_bytes <= 10485760)),
  status text not null default 'pending' check (status in ('pending','ready','deleted')),
  uploaded_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  completed_at timestamptz,
  deleted_at timestamptz,
  constraint attachments_unit_fk foreign key (ledger_unit_id, activity_id)
    references public.ledger_units(id, activity_id) on delete restrict,
  constraint attachments_expense_unit_fk foreign key (expense_id, ledger_unit_id)
    references public.expenses(id, ledger_unit_id) on delete restrict,
  constraint attachments_lifecycle check (
    (status = 'pending' and completed_at is null and deleted_at is null)
    or (status = 'ready' and completed_at is not null and deleted_at is null)
    or (status = 'deleted' and deleted_at is not null)
  )
);
create index attachments_activity_idx on public.attachments(activity_id, created_at desc);
create index attachments_expense_idx on public.attachments(expense_id, activity_id);
create index attachments_unit_idx on public.attachments(ledger_unit_id, activity_id);
create index attachments_expense_unit_fk_idx on public.attachments(expense_id, ledger_unit_id);
create index attachments_uploaded_by_idx on public.attachments(uploaded_by);
alter table public.attachments enable row level security;
create policy attachments_select_member on public.attachments for select to authenticated
  using ((select private.is_activity_member(activity_id)) and status <> 'deleted');
revoke all on public.attachments from public, anon, authenticated;
grant select on public.attachments to authenticated;
grant all on public.attachments to service_role;

-- A read-only reference cache.  rate means one unit of quote/expense currency
-- converts to rate units of base_currency, matching Expense.fx_rate.  The
-- Expense snapshot remains immutable and is never rewritten from this table.
create table public.exchange_rate_cache (
  base_currency character(3) not null check (base_currency ~ '^[A-Z]{3}$'),
  quote_currency character(3) not null check (quote_currency ~ '^[A-Z]{3}$'),
  rate numeric(20,10) not null check (rate > 0),
  observed_at timestamptz not null,
  source text,
  updated_at timestamptz not null default pg_catalog.now(),
  primary key (base_currency, quote_currency),
  check (base_currency <> quote_currency)
);
alter table public.exchange_rate_cache enable row level security;
create policy exchange_rate_cache_select_authenticated on public.exchange_rate_cache
  for select to authenticated using (true);
revoke all on public.exchange_rate_cache from public, anon, authenticated;
grant select on public.exchange_rate_cache to authenticated;
grant all on public.exchange_rate_cache to service_role;

-- Cover every Phase 7 foreign key without changing existing migrations.
create index activities_deleted_by_idx on public.activities(deleted_by);
create index ledger_units_deleted_by_idx on public.ledger_units(deleted_by);
create index participants_deleted_by_idx on public.participants(deleted_by);
create index participant_claims_activity_participant_fk_idx
  on public.participant_claims(activity_id, participant_id);
create index audit_logs_actor_user_idx on public.audit_logs(actor_user_id);
create index transfer_disputes_disputed_by_idx on public.transfer_disputes(disputed_by);
create index transfer_disputes_participant_fk_idx
  on public.transfer_disputes(activity_id, participant_id);
create index transfer_disputes_resolved_by_idx on public.transfer_disputes(resolved_by);
create index transfer_disputes_transfer_fk_idx
  on public.transfer_disputes(transfer_id, activity_id);

-- The public member predicate also hides logically deleted Activities.
create or replace function private.is_activity_member(activity_uuid uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.activity_members m
    join public.activities a on a.id = m.activity_id
    where m.activity_id = $1 and m.user_id = (select auth.uid()) and not a.is_deleted
  );
$$;
create or replace function private.is_activity_creator(activity_uuid uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.activities a
    where a.id = $1 and a.created_by = (select auth.uid()) and not a.is_deleted
  );
$$;

-- Lock the list exactly when the first formal financial record/sub-activity is
-- staged.  Failed transactions roll this marker back with the fact.
create or replace function private.lock_participant_list_on_fact()
returns trigger language plpgsql security definer set search_path = '' as $function$
declare aid uuid;
begin
  if tg_table_name = 'expenses' then
    select activity_id into aid from public.ledger_units where id = new.ledger_unit_id;
  else
    aid := new.activity_id;
  end if;
  update public.activities set participants_locked_at = coalesce(participants_locked_at, pg_catalog.now())
  where id = aid and participants_locked_at is null and not is_deleted;
  return new;
end;
$function$;
drop trigger if exists expenses_lock_participants on public.expenses;
create trigger expenses_lock_participants before insert on public.expenses
for each row execute function private.lock_participant_list_on_fact();
drop trigger if exists sub_activity_lock_participants on public.ledger_units;
create trigger sub_activity_lock_participants before insert on public.ledger_units
for each row when (new.type = 'sub_activity'::public.ledger_unit_type)
execute function private.lock_participant_list_on_fact();
revoke all on function private.lock_participant_list_on_fact() from public, anon, authenticated;

-- Restore follows the same lock -> fact -> projection path as delete/update.
create or replace function private.restore_expense_impl(p_expense_id uuid)
returns table(restored_expense_id uuid, restored boolean, version bigint)
language plpgsql volatile security definer set search_path = '' as $function$
declare uid uuid := (select auth.uid()); aid uuid; was_deleted boolean; ver bigint;
begin
  if uid is null then raise exception using errcode='28000', message='authentication is required'; end if;
  select lu.activity_id into aid
  from public.expenses e join public.ledger_units lu on lu.id=e.ledger_unit_id
  join public.activities a on a.id=lu.activity_id
  where e.id=p_expense_id and not a.is_deleted;
  if not found then raise exception using errcode='P0002', message='expense was not found'; end if;
  perform private.lock_debt_projection_activity(aid);
  perform 1 from public.activities a where a.id=aid and not a.is_deleted and a.archived_at is null for update;
  if not found then raise exception using errcode='55000', message='activity is archived or deleted'; end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=aid and m.user_id=uid) then
    raise exception using errcode='42501', message='caller is not an activity member';
  end if;
  select e.is_deleted, e.version into was_deleted, ver from public.expenses e where e.id=p_expense_id for update;
  if exists(select 1 from public.expenses e where e.id=p_expense_id and e.original_expense_id is not null)
     and not exists(select 1 from public.expenses e join public.expenses o on o.id=e.original_expense_id where e.id=p_expense_id and not o.is_deleted) then
    raise exception using errcode='23514',message='original expense must be active before restoring refund';
  end if;
  if not was_deleted then return query select p_expense_id,false,ver; return; end if;
  update public.expenses as e set is_deleted=false, deleted_at=null, deleted_by=null,
    updated_by=uid, version=e.version+1 where e.id=p_expense_id returning e.version into ver;
  perform private.rebuild_expense_and_bilateral_debts(p_expense_id,aid);
  return query select p_expense_id,true,ver;
end;
$function$;

create or replace function public.restore_expense(expense_id uuid)
returns table(restored_expense_id uuid, restored boolean, version bigint)
language sql volatile security invoker set search_path = '' as $$
  select * from private.restore_expense_impl($1);
$$;
revoke all on function private.restore_expense_impl(uuid), public.restore_expense(uuid) from public, anon, authenticated;
grant execute on function private.restore_expense_impl(uuid) to authenticated;
grant execute on function public.restore_expense(uuid) to authenticated;

-- Participant lifecycle and claims.  Claims remain legal after list locking.
create or replace function private.create_participant_impl(p_activity_id uuid,p_name text,p_order integer default null)
returns table(participant_id uuid,participant_name text,participant_order integer)
language plpgsql volatile security definer set search_path = '' as $function$
declare uid uuid := (select auth.uid()); ord integer; pid uuid;
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if p_name is null or pg_catalog.length(pg_catalog.btrim(p_name))=0 then raise exception using errcode='22023',message='participant name must not be blank'; end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  perform 1 from public.activities a join public.activity_members m on m.activity_id=a.id
    where a.id=p_activity_id and not a.is_deleted and a.archived_at is null and m.user_id=uid for update of a;
  if not found then raise exception using errcode='42501',message='caller is not an active activity member'; end if;
  if exists(select 1 from public.activities where id=p_activity_id and participants_locked_at is not null) then
    raise exception using errcode='55000',message='participant list is locked';
  end if;
  if p_order is null then select coalesce(max(p.participant_order)+1,0) into ord from public.participants p where p.activity_id=p_activity_id; else ord:=p_order; end if;
  if ord < 0 then raise exception using errcode='22023',message='participant_order must be non-negative'; end if;
  insert into public.participants(activity_id,name,participant_order) values(p_activity_id,pg_catalog.btrim(p_name),ord)
    returning public.participants.id,public.participants.name,public.participants.participant_order
    into pid,participant_name,participant_order;
  return query select pid,participant_name,participant_order;
end;
$function$;

create or replace function private.delete_participant_impl(p_participant_id uuid)
returns table(participant_id uuid, deleted boolean)
language plpgsql volatile security definer set search_path = '' as $function$
declare uid uuid := (select auth.uid()); aid uuid; was_deleted boolean;
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  select activity_id,is_deleted into aid,was_deleted from public.participants where id=p_participant_id;
  if not found then raise exception using errcode='P0002',message='participant was not found'; end if;
  perform private.lock_debt_projection_activity(aid);
  perform 1 from public.activities a join public.activity_members m on m.activity_id=a.id
    where a.id=aid and not a.is_deleted and a.archived_at is null and m.user_id=uid for update of a;
  if not found then raise exception using errcode='42501',message='caller is not an active activity member'; end if;
  select p.activity_id,p.is_deleted into aid,was_deleted from public.participants p where p.id=p_participant_id for update;
  if exists(select 1 from public.activities where id=aid and participants_locked_at is not null) then raise exception using errcode='55000',message='participant list is locked'; end if;
  if was_deleted then return query select p_participant_id,false; return; end if;
  if exists(select 1 from public.participant_claims c where c.participant_id=p_participant_id)
     or exists(select 1 from public.payments pay where pay.participant_id=p_participant_id)
     or exists(select 1 from public.splits s where s.participant_id=p_participant_id)
     or exists(select 1 from public.transfers t where t.from_participant_id=p_participant_id or t.to_participant_id=p_participant_id or t.on_behalf_of_participant_id=p_participant_id)
     then raise exception using errcode='23514',message='participant is claimed or used by financial facts'; end if;
  update public.participants set is_deleted=true,deleted_at=pg_catalog.now(),deleted_by=uid where id=p_participant_id;
  return query select p_participant_id,true;
end;
$function$;

create or replace function private.claim_participant_impl(p_activity_id uuid,p_participant_id uuid)
returns table(claim_id uuid,claimed_participant_id uuid,is_new boolean)
language plpgsql volatile security definer set search_path = '' as $function$
declare uid uuid := (select auth.uid()); cid uuid; existing uuid;
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  perform 1 from public.activities a join public.activity_members m on m.activity_id=a.id where a.id=p_activity_id and not a.is_deleted and a.archived_at is null and m.user_id=uid for update of a;
  if not found then raise exception using errcode='42501',message='caller is not an active activity member'; end if;
  perform 1 from public.participants p where p.id=p_participant_id and p.activity_id=p_activity_id and not p.is_deleted for update;
  if not found then raise exception using errcode='P0002',message='participant was not found'; end if;
  select id into existing from public.participant_claims where activity_id=p_activity_id and user_id=uid;
  if existing is not null then
    select id,participant_id into cid,claim_id from public.participant_claims where id=existing;
    if claim_id <> p_participant_id then raise exception using errcode='23505',message='user already claimed a participant'; end if;
    return query select cid,p_participant_id,false; return;
  end if;
  insert into public.participant_claims(activity_id,participant_id,user_id) values(p_activity_id,p_participant_id,uid) returning id into cid;
  return query select cid,p_participant_id,true;
exception when unique_violation then raise exception using errcode='23505',message='participant is already claimed';
end;
$function$;

create or replace function private.unclaim_participant_impl(p_activity_id uuid)
returns boolean language plpgsql volatile security definer set search_path = '' as $function$
declare uid uuid := (select auth.uid()); n integer;
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  perform 1 from public.activities a join public.activity_members m on m.activity_id=a.id where a.id=p_activity_id and not a.is_deleted and a.archived_at is null and m.user_id=uid for update of a;
  if not found then raise exception using errcode='42501',message='caller is not an active activity member'; end if;
  delete from public.participant_claims where activity_id=p_activity_id and user_id=uid;
  get diagnostics n=row_count; return n>0;
end;
$function$;

create or replace function public.create_participant(activity_id uuid,name text,participant_order integer default null)
returns table(participant_id uuid,participant_name text,participant_order integer) language sql volatile security invoker set search_path='' as $$ select * from private.create_participant_impl($1,$2,$3); $$;
create or replace function public.delete_participant(participant_id uuid)
returns table(participant_id uuid,deleted boolean) language sql volatile security invoker set search_path='' as $$ select * from private.delete_participant_impl($1); $$;
create or replace function public.claim_participant(activity_id uuid,participant_id uuid)
returns table(claim_id uuid,claimed_participant_id uuid,is_new boolean) language sql volatile security invoker set search_path='' as $$ select * from private.claim_participant_impl($1,$2); $$;
create or replace function public.unclaim_participant(activity_id uuid)
returns boolean language sql volatile security invoker set search_path='' as $$ select private.unclaim_participant_impl($1); $$;
revoke all on function private.create_participant_impl(uuid,text,integer),private.delete_participant_impl(uuid),private.claim_participant_impl(uuid,uuid),private.unclaim_participant_impl(uuid),public.create_participant(uuid,text,integer),public.delete_participant(uuid),public.claim_participant(uuid,uuid),public.unclaim_participant(uuid) from public,anon,authenticated;
grant execute on function public.create_participant(uuid,text,integer),public.delete_participant(uuid),public.claim_participant(uuid,uuid),public.unclaim_participant(uuid) to authenticated;
grant execute on function private.create_participant_impl(uuid,text,integer),private.delete_participant_impl(uuid),private.claim_participant_impl(uuid,uuid),private.unclaim_participant_impl(uuid) to authenticated;
revoke insert,update,delete on public.participants,public.participant_claims from authenticated;

-- Creator management.  Membership removal is physical access revocation only;
-- Participant rows and all historical facts remain untouched.
create or replace function private.remove_activity_member_impl(p_activity_id uuid,p_user_id uuid)
returns boolean language plpgsql volatile security definer set search_path='' as $function$
declare uid uuid := (select auth.uid()); n integer;
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  perform 1 from public.activities where id=p_activity_id and created_by=uid and not is_deleted and archived_at is null for update;
  if not found then raise exception using errcode='42501',message='creator permission required'; end if;
  if p_user_id=uid then raise exception using errcode='22023',message='creator cannot remove self'; end if;
  delete from public.activity_members where activity_id=p_activity_id and user_id=p_user_id;
  get diagnostics n=row_count; if n=0 then raise exception using errcode='P0002',message='activity member was not found'; end if; return true;
end;
$function$;
create or replace function private.transfer_activity_creator_impl(p_activity_id uuid,p_new_creator uuid)
returns uuid language plpgsql volatile security definer set search_path='' as $function$
declare uid uuid := (select auth.uid());
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  perform 1 from public.activities where id=p_activity_id and created_by=uid and not is_deleted and archived_at is null for update;
  if not found then raise exception using errcode='42501',message='creator permission required'; end if;
  if p_new_creator is null or p_new_creator=uid or not exists(select 1 from public.activity_members where activity_id=p_activity_id and user_id=p_new_creator) then raise exception using errcode='42501',message='new creator must be another active member'; end if;
  update public.activities set created_by=p_new_creator where id=p_activity_id; return p_new_creator;
end;
$function$;
create or replace function private.delete_activity_impl(p_activity_id uuid)
returns boolean language plpgsql volatile security definer set search_path='' as $function$
declare uid uuid := (select auth.uid());
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  perform 1 from public.activities where id=p_activity_id and created_by=uid and not is_deleted and archived_at is null for update;
  if not found then raise exception using errcode='42501',message='creator permission required'; end if;
  update public.activities set is_deleted=true,deleted_at=pg_catalog.now(),deleted_by=uid where id=p_activity_id; return true;
end;
$function$;
create or replace function public.remove_activity_member(activity_id uuid,user_id uuid) returns boolean language sql volatile security invoker set search_path='' as $$ select private.remove_activity_member_impl($1,$2); $$;
create or replace function public.transfer_activity_creator(activity_id uuid,new_creator_user_id uuid) returns uuid language sql volatile security invoker set search_path='' as $$ select private.transfer_activity_creator_impl($1,$2); $$;
create or replace function public.delete_activity(activity_id uuid) returns boolean language sql volatile security invoker set search_path='' as $$ select private.delete_activity_impl($1); $$;
revoke all on function private.remove_activity_member_impl(uuid,uuid),private.transfer_activity_creator_impl(uuid,uuid),private.delete_activity_impl(uuid),public.remove_activity_member(uuid,uuid),public.transfer_activity_creator(uuid,uuid),public.delete_activity(uuid) from public,anon,authenticated;
grant execute on function public.remove_activity_member(uuid,uuid),public.transfer_activity_creator(uuid,uuid),public.delete_activity(uuid) to authenticated;
grant execute on function private.remove_activity_member_impl(uuid,uuid),private.transfer_activity_creator_impl(uuid,uuid),private.delete_activity_impl(uuid) to authenticated;

create or replace function private.update_activity_settings_impl(
  p_activity_id uuid, p_name text, p_base_currency character(3),
  p_multi_currency_enabled boolean
)
returns table(activity_id uuid,activity_name text,activity_base_currency character(3),activity_multi_currency_enabled boolean)
language plpgsql volatile security definer set search_path = '' as $function$
declare uid uuid := (select auth.uid()); current_version bigint;
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if p_name is null or pg_catalog.length(pg_catalog.btrim(p_name))=0 then raise exception using errcode='22023',message='activity name must not be blank'; end if;
  if p_base_currency is null or p_base_currency !~ '^[A-Z]{3}$' then raise exception using errcode='22023',message='base_currency must be three uppercase letters'; end if;
  if p_multi_currency_enabled is null then raise exception using errcode='22023',message='multi_currency_enabled is required'; end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  select financial_version into current_version from public.activities where id=p_activity_id and created_by=uid and not is_deleted and archived_at is null for update;
  if not found then raise exception using errcode='42501',message='creator permission required or activity is archived'; end if;
  if current_version > 0 and exists(select 1 from public.activities where id=p_activity_id and base_currency is distinct from p_base_currency) then
    raise exception using errcode='55000',message='base_currency is locked after the first financial write';
  end if;
  update public.activities a set name=pg_catalog.btrim(p_name),base_currency=p_base_currency,multi_currency_enabled=p_multi_currency_enabled where a.id=p_activity_id
    returning a.id,a.name,a.base_currency,a.multi_currency_enabled into activity_id,activity_name,activity_base_currency,activity_multi_currency_enabled;
  return next;
end;
$function$;
create or replace function public.update_activity_settings(activity_id uuid,name text,base_currency character(3),multi_currency_enabled boolean)
returns table(activity_id uuid,activity_name text,activity_base_currency character(3),activity_multi_currency_enabled boolean)
language sql volatile security invoker set search_path='' as $$ select * from private.update_activity_settings_impl($1,$2,$3,$4); $$;
revoke all on function private.update_activity_settings_impl(uuid,text,character(3),boolean),public.update_activity_settings(uuid,text,character(3),boolean) from public,anon,authenticated;
grant execute on function private.update_activity_settings_impl(uuid,text,character(3),boolean),public.update_activity_settings(uuid,text,character(3),boolean) to authenticated;

-- Dispute RPCs.
create or replace function private.add_transfer_dispute_impl(p_transfer_id uuid,p_participant_id uuid,p_note text)
returns table(dispute_id uuid,created boolean) language plpgsql volatile security definer set search_path='' as $function$
declare uid uuid := (select auth.uid()); aid uuid; did uuid;
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  select activity_id into aid from public.transfers where id=p_transfer_id and not is_voided;
  if not found then raise exception using errcode='P0002',message='transfer was not found'; end if;
  perform private.lock_debt_projection_activity(aid);
  perform 1 from public.activities where id=aid and not is_deleted and archived_at is null for update;
  if not found then raise exception using errcode='55000',message='activity is archived or deleted'; end if;
  if not exists(select 1 from public.activity_members where activity_id=aid and user_id=uid) then raise exception using errcode='42501',message='caller is not an activity member'; end if;
  if not exists(select 1 from public.transfers where id=p_transfer_id and (from_participant_id=p_participant_id or to_participant_id=p_participant_id)) then raise exception using errcode='42501',message='participant is not related to transfer'; end if;
  if not exists(select 1 from public.participant_claims where activity_id=aid and participant_id=p_participant_id and user_id=uid)
     and not exists(select 1 from public.transfers where id=p_transfer_id and recorded_by=uid) then
    raise exception using errcode='42501',message='caller is not related to transfer';
  end if;
  insert into public.transfer_disputes(activity_id,transfer_id,participant_id,disputed_by,note) values(aid,p_transfer_id,p_participant_id,uid,p_note) on conflict(transfer_id,participant_id) do update set note=excluded.note,resolved_at=null,resolved_by=null returning id into did;
  return query select did,true;
end;
$function$;
create or replace function private.remove_transfer_dispute_impl(p_dispute_id uuid)
returns boolean language plpgsql volatile security definer set search_path='' as $function$
declare uid uuid := (select auth.uid()); n integer;
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  update public.transfer_disputes d set resolved_at=pg_catalog.now(),resolved_by=uid where d.id=p_dispute_id and d.resolved_at is null
    and exists(select 1 from public.activity_members m join public.activities a on a.id=m.activity_id where m.activity_id=d.activity_id and m.user_id=uid and not a.is_deleted and a.archived_at is null)
    and (d.disputed_by=uid or exists(select 1 from public.activities a where a.id=d.activity_id and a.created_by=uid));
  get diagnostics n=row_count; if n=0 then raise exception using errcode='42501',message='dispute permission denied or already removed'; end if; return true;
end;
$function$;
create or replace function public.add_transfer_dispute(transfer_id uuid,participant_id uuid,note text default null) returns table(dispute_id uuid,created boolean) language sql volatile security invoker set search_path='' as $$ select * from private.add_transfer_dispute_impl($1,$2,$3); $$;
create or replace function public.remove_transfer_dispute(dispute_id uuid) returns boolean language sql volatile security invoker set search_path='' as $$ select private.remove_transfer_dispute_impl($1); $$;
revoke all on function private.add_transfer_dispute_impl(uuid,uuid,text),private.remove_transfer_dispute_impl(uuid),public.add_transfer_dispute(uuid,uuid,text),public.remove_transfer_dispute(uuid) from public,anon,authenticated;
grant execute on function public.add_transfer_dispute(uuid,uuid,text),public.remove_transfer_dispute(uuid) to authenticated;
grant execute on function private.add_transfer_dispute_impl(uuid,uuid,text),private.remove_transfer_dispute_impl(uuid) to authenticated;

-- Audit trigger: successful writes only, no version or financial side effects.
create or replace function private.write_audit_log()
returns trigger language plpgsql security definer set search_path='' as $function$
declare aid uuid; act text; eid uuid; meta jsonb := '{}'::jsonb; uid uuid := (select auth.uid());
begin
  if tg_table_name='activities' then aid:=coalesce(new.id,old.id); eid:=aid;
    if tg_op='INSERT' then act:='activity.create';
    elsif new.is_deleted is distinct from old.is_deleted and new.is_deleted then act:='activity.delete';
    elsif new.archived_at is distinct from old.archived_at then act:=case when new.archived_at is null then 'activity.unarchive' else 'activity.archive' end;
    elsif new.created_by is distinct from old.created_by then act:='activity.creator_transfer'; else act:='activity.update'; end if;
  elsif tg_table_name='activity_members' then aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id); act:=case when tg_op='INSERT' then 'member.join' else 'member.remove' end;
  elsif tg_table_name='participants' then aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id); act:=case when tg_op='INSERT' then 'participant.create' when new.is_deleted is distinct from old.is_deleted and new.is_deleted then 'participant.delete' else 'participant.update' end;
  elsif tg_table_name='participant_claims' then aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id); act:=case when tg_op='INSERT' then 'claim.create' else 'claim.remove' end;
  elsif tg_table_name='expenses' then select lu.activity_id into aid from public.ledger_units lu where lu.id=coalesce(new.ledger_unit_id,old.ledger_unit_id); eid:=coalesce(new.id,old.id); act:=case when tg_op='INSERT' then 'expense.create' when new.is_deleted is distinct from old.is_deleted and new.is_deleted then 'expense.delete' when new.is_deleted is distinct from old.is_deleted and not new.is_deleted then 'expense.restore' else 'expense.update' end;
  elsif tg_table_name='transfers' then aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id); act:=case when tg_op='INSERT' then 'transfer.create' when new.is_voided is distinct from old.is_voided and new.is_voided then 'transfer.void' else 'transfer.create' end;
  elsif tg_table_name='transfer_disputes' then aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id); act:=case when tg_op='INSERT' then 'dispute.create' when new.resolved_at is distinct from old.resolved_at and new.resolved_at is not null then 'dispute.remove' else 'dispute.create' end;
  elsif tg_table_name='attachments' then aid:=coalesce(new.activity_id,old.activity_id); eid:=coalesce(new.id,old.id); act:=case when tg_op='INSERT' then 'attachment.create' when new.status='ready' and old.status='pending' then 'attachment.complete' when new.status='deleted' and old.status is distinct from new.status then 'attachment.delete' else 'attachment.complete' end;
  else if tg_op='DELETE' then return old; else return new; end if; end if;
  insert into public.audit_logs(activity_id,actor_user_id,action,entity_type,entity_id,metadata) values(aid,uid,act,tg_table_name,eid,meta);
  if tg_op='DELETE' then return old; else return new; end if;
end;
$function$;
drop trigger if exists audit_activities on public.activities; create trigger audit_activities after insert or update of name,type,base_currency,multi_currency_enabled,created_by,is_deleted,archived_at on public.activities for each row execute function private.write_audit_log();
drop trigger if exists audit_activity_members on public.activity_members; create trigger audit_activity_members after insert or delete on public.activity_members for each row execute function private.write_audit_log();
drop trigger if exists audit_participants on public.participants; create trigger audit_participants after insert or update on public.participants for each row execute function private.write_audit_log();
drop trigger if exists audit_participant_claims on public.participant_claims; create trigger audit_participant_claims after insert or delete on public.participant_claims for each row execute function private.write_audit_log();
drop trigger if exists audit_expenses on public.expenses; create trigger audit_expenses after insert or update on public.expenses for each row execute function private.write_audit_log();
drop trigger if exists audit_transfers on public.transfers; create trigger audit_transfers after insert or update on public.transfers for each row execute function private.write_audit_log();
drop trigger if exists audit_transfer_disputes on public.transfer_disputes; create trigger audit_transfer_disputes after insert or update on public.transfer_disputes for each row execute function private.write_audit_log();
drop trigger if exists audit_attachments on public.attachments; create trigger audit_attachments after insert or update on public.attachments for each row execute function private.write_audit_log();
revoke all on function private.write_audit_log() from public,anon,authenticated;

-- Attachment lifecycle RPC.  The caller creates metadata, uploads via the
-- Storage API, then calls complete_attachment.  No storage table is modified.
create or replace function private.create_attachment_impl(p_activity_id uuid,p_ledger_unit_id uuid,p_expense_id uuid,p_filename text,p_mime_type text,p_size_bytes bigint)
returns table(attachment_id uuid,bucket text,path text,status text)
language plpgsql volatile security definer set search_path='' as $function$
declare uid uuid := (select auth.uid()); ext text; pid uuid := extensions.gen_random_uuid(); attachment_count integer;
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if p_mime_type not in ('image/jpeg','image/png','image/webp') or p_size_bytes is null or p_size_bytes<=0 or p_size_bytes>10485760 then raise exception using errcode='22023',message='only image/jpeg, image/png, image/webp up to 10 MiB are supported'; end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  perform 1 from public.ledger_units l join public.activities a on a.id=l.activity_id join public.activity_members m on m.activity_id=a.id where l.id=p_ledger_unit_id and a.id=p_activity_id and not a.is_deleted and a.archived_at is null and not l.is_deleted and m.user_id=uid;
  if not found then raise exception using errcode='42501',message='caller cannot attach to this Activity'; end if;
  if p_expense_id is null then
    select count(*) into attachment_count from public.attachments a where a.ledger_unit_id=p_ledger_unit_id and a.expense_id is null and a.status in ('pending','ready');
  else
    select count(*) into attachment_count from public.attachments a where a.expense_id=p_expense_id and a.status in ('pending','ready');
  end if;
  if attachment_count >= 10 then raise exception using errcode='54000',message='Activity attachment limit reached'; end if;
  if p_expense_id is not null and not exists(select 1 from public.expenses e where e.id=p_expense_id and e.ledger_unit_id=p_ledger_unit_id and not e.is_deleted) then raise exception using errcode='23514',message='expense does not belong to active ledger unit'; end if;
  ext:=case p_mime_type when 'image/png' then 'png' when 'image/webp' then 'webp' else 'jpg' end;
  insert into public.attachments(id,activity_id,ledger_unit_id,expense_id,original_filename,mime_type,size_bytes,uploaded_by,storage_path) values(pid,p_activity_id,p_ledger_unit_id,p_expense_id,p_filename,p_mime_type,p_size_bytes,uid,p_activity_id::text||'/'||p_ledger_unit_id::text||'/'||pid::text||'.'||ext);
  return query select pid,'activity-attachments'::text,p_activity_id::text||'/'||p_ledger_unit_id::text||'/'||pid::text||'.'||ext,'pending'::text;
end;
$function$;
create or replace function private.complete_attachment_impl(p_attachment_id uuid)
returns boolean language plpgsql volatile security definer set search_path='' as $function$
declare uid uuid := (select auth.uid()); n integer;
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  update public.attachments x set status='ready',completed_at=pg_catalog.now() where x.id=p_attachment_id and x.status='pending'
    and exists(select 1 from public.activities a where a.id=x.activity_id and not a.is_deleted and a.archived_at is null)
    and exists(select 1 from public.activity_members m where m.activity_id=x.activity_id and m.user_id=uid)
    and exists(select 1 from storage.objects o where o.bucket_id=x.storage_bucket and o.name=x.storage_path);
  get diagnostics n=row_count; if n=0 then raise exception using errcode='42501',message='attachment is not pending, uploaded, or accessible'; end if; return true;
end;
$function$;
create or replace function private.delete_attachment_impl(p_attachment_id uuid)
returns boolean language plpgsql volatile security definer set search_path='' as $function$
declare uid uuid := (select auth.uid()); n integer;
begin
  if uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  update public.attachments x set status='deleted',deleted_at=pg_catalog.now() where x.id=p_attachment_id and x.status<>'deleted' and exists(select 1 from public.activities a where a.id=x.activity_id and a.archived_at is null and not a.is_deleted) and (x.uploaded_by=uid or exists(select 1 from public.activities a where a.id=x.activity_id and a.created_by=uid)) and exists(select 1 from public.activity_members m where m.activity_id=x.activity_id and m.user_id=uid);
  get diagnostics n=row_count; if n=0 then raise exception using errcode='42501',message='attachment delete permission denied'; end if; return true;
end;
$function$;
create or replace function public.create_attachment(activity_id uuid,ledger_unit_id uuid,expense_id uuid,filename text,mime_type text,size_bytes bigint) returns table(attachment_id uuid,bucket text,path text,status text) language sql volatile security invoker set search_path='' as $$ select * from private.create_attachment_impl($1,$2,$3,$4,$5,$6); $$;
create or replace function public.complete_attachment(attachment_id uuid) returns boolean language sql volatile security invoker set search_path='' as $$ select private.complete_attachment_impl($1); $$;
create or replace function public.delete_attachment(attachment_id uuid) returns boolean language sql volatile security invoker set search_path='' as $$ select private.delete_attachment_impl($1); $$;
revoke all on function private.create_attachment_impl(uuid,uuid,uuid,text,text,bigint),private.complete_attachment_impl(uuid),private.delete_attachment_impl(uuid),public.create_attachment(uuid,uuid,uuid,text,text,bigint),public.complete_attachment(uuid),public.delete_attachment(uuid) from public,anon,authenticated;
grant execute on function public.create_attachment(uuid,uuid,uuid,text,text,bigint),public.complete_attachment(uuid),public.delete_attachment(uuid) to authenticated;
grant execute on function private.create_attachment_impl(uuid,uuid,uuid,text,text,bigint),private.complete_attachment_impl(uuid),private.delete_attachment_impl(uuid) to authenticated;

create or replace function public.get_exchange_rate(p_base_currency character(3),p_quote_currency character(3))
returns table(base_currency character(3),quote_currency character(3),rate numeric(20,10),observed_at timestamptz,source text)
language sql stable security invoker set search_path='' as $$
  select c.base_currency,c.quote_currency,c.rate,c.observed_at,c.source from public.exchange_rate_cache c where c.base_currency=$1 and c.quote_currency=$2;
$$;
revoke all on function public.get_exchange_rate(character(3),character(3)) from public,anon,authenticated;
grant execute on function public.get_exchange_rate(character(3),character(3)) to authenticated;

-- Private Storage bucket and Activity-scoped object policies.  The Storage
-- API remains the only writer of storage.objects.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('activity-attachments','activity-attachments',false,10485760,array['image/jpeg','image/png','image/webp']::text[])
on conflict (id) do update set public=false,file_size_limit=excluded.file_size_limit,allowed_mime_types=excluded.allowed_mime_types;
drop policy if exists activity_attachments_read on storage.objects;
create policy activity_attachments_read on storage.objects for select to authenticated using (
  bucket_id='activity-attachments' and exists(select 1 from public.attachments x where x.storage_bucket=storage.objects.bucket_id and x.storage_path=storage.objects.name and x.status<>'deleted' and private.is_activity_member(x.activity_id))
);
drop policy if exists activity_attachments_upload on storage.objects;
create policy activity_attachments_upload on storage.objects for insert to authenticated with check (
  bucket_id='activity-attachments' and exists(select 1 from public.attachments x join public.activities a on a.id=x.activity_id where x.storage_bucket=storage.objects.bucket_id and x.storage_path=storage.objects.name and x.status='pending' and a.archived_at is null and not a.is_deleted and private.is_activity_member(x.activity_id))
);
drop policy if exists activity_attachments_delete on storage.objects;
create policy activity_attachments_delete on storage.objects for delete to authenticated using (
  bucket_id='activity-attachments' and exists(select 1 from public.attachments x join public.activities a on a.id=x.activity_id where x.storage_bucket=storage.objects.bucket_id and x.storage_path=storage.objects.name and a.archived_at is null and not a.is_deleted and (x.uploaded_by=(select auth.uid()) or a.created_by=(select auth.uid())) and private.is_activity_member(x.activity_id))
);

-- Realtime is publication membership only.  Do not alter the locked realtime
-- schema; Postgres Changes continues to enforce each table's RLS policy.
do $publication$
declare t text;
begin
  foreach t in array array['activities','activity_members','ledger_units','participants','participant_claims','expenses','transfers','expense_debts','bilateral_debts','transfer_allocations','transfer_components','prepayment_accounts','prepayment_usages','final_settlement_paths','attachments','transfer_disputes'] loop
    if not exists(select 1 from pg_catalog.pg_publication_tables where pubname='supabase_realtime' and schemaname='public' and tablename=t) then
      execute 'alter publication supabase_realtime add table public.'||pg_catalog.quote_ident(t);
    end if;
  end loop;
end;
$publication$;

-- Contract freeze: API roles never need schema-maintenance privileges on
-- business tables.  Keep existing SELECT (and profile self-update) grants,
-- while removing accidental TRUNCATE/TRIGGER/REFERENCES and lifecycle direct
-- writes that were inherited from the early foundation grants.
revoke truncate, trigger, references on table
  public.activities, public.activity_members, public.ledger_units,
  public.participants, public.participant_claims, public.expenses,
  public.payments, public.splits, public.expense_debts, public.bilateral_debts,
  public.transfers, public.transfer_allocations, public.transfer_components,
  public.prepayment_accounts, public.prepayment_usages,
  public.final_settlement_paths, public.audit_logs, public.transfer_disputes,
  public.attachments, public.exchange_rate_cache
  from public, anon, authenticated;
revoke insert, update, delete on table public.activity_members, public.ledger_units
  from authenticated;

commit;
