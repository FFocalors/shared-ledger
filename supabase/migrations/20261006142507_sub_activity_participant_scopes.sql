begin;

-- A separate bit distinguishes pre-migration children from a configured scope
-- whose membership rows are missing or corrupted. Configured-but-empty fails
-- closed; only pre-migration children retain legacy-unscoped behavior.
alter table public.ledger_units
  add column participant_scope_configured boolean not null default false;

-- Existing sub-activities have no persisted participant selection. Only the
-- false configuration marker means legacy-unscoped; a configured empty or
-- incomplete association set fails closed. Never invent historical choices.
create table public.sub_activity_participants (
  activity_id uuid not null,
  ledger_unit_id uuid not null,
  participant_id uuid not null,
  created_at timestamptz not null default pg_catalog.now(),
  primary key (ledger_unit_id, participant_id),
  constraint sub_activity_participants_unit_activity_fk
    foreign key (ledger_unit_id, activity_id)
    references public.ledger_units (id, activity_id) on delete restrict,
  constraint sub_activity_participants_participant_activity_fk
    foreign key (activity_id, participant_id)
    references public.participants (activity_id, id) on delete restrict
);

comment on table public.sub_activity_participants is
  'Explicit Participant scope for configured child ledger units. participant_scope_configured=false alone means legacy-unscoped; configured-but-empty is invalid and fails closed. Soft deletion preserves these rows.';

create index sub_activity_participants_activity_participant_idx
  on public.sub_activity_participants (activity_id, participant_id, ledger_unit_id);

alter table public.sub_activity_participants enable row level security;
revoke all on table public.sub_activity_participants
  from public, anon, authenticated, service_role;
grant select on table public.sub_activity_participants to authenticated;

create policy sub_activity_participants_select_member
  on public.sub_activity_participants
  for select to authenticated
  using (private.is_activity_member(activity_id));

create or replace function private.prevent_client_scope_configuration_mutation()
returns trigger
language plpgsql
volatile
security invoker
set search_path = ''
as $function$
begin
  if old.participant_scope_configured is distinct from new.participant_scope_configured
     and current_user in ('anon', 'authenticated', 'service_role') then
    raise exception using errcode = '42501', message = 'sub-activity participant scope is server-managed';
  end if;
  return new;
end;
$function$;

revoke all on function private.prevent_client_scope_configuration_mutation()
  from public, anon, authenticated, service_role;
create trigger ledger_units_scope_configuration_guard
before update of participant_scope_configured on public.ledger_units
for each row execute function private.prevent_client_scope_configuration_mutation();

create or replace function private.create_sub_activity_scoped_impl(
  p_activity_id uuid,
  p_name text,
  p_participant_ids uuid[]
)
returns table (
  parent_activity_id uuid,
  ledger_unit_id uuid,
  created_name text,
  created_type public.ledger_unit_type
)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_parent_activity_id uuid;
  v_ledger_unit_id uuid;
  v_name text;
  v_type public.ledger_unit_type;
  v_input_count integer;
  v_distinct_count integer;
  v_active_count integer;
begin
  -- The existing implementation locks the Activity row, verifies active
  -- membership/large type/root ledger, creates the child, and locks the
  -- Activity Participant list. Validate ids only after those checks; any error
  -- below rolls the new row and all transactional effects back.
  select created.parent_activity_id, created.ledger_unit_id,
         created.created_name, created.created_type
    into v_parent_activity_id, v_ledger_unit_id, v_name, v_type
  from private.create_sub_activity_impl(p_activity_id, p_name) as created;
  if not found then
    raise exception using errcode = 'P0001', message = 'sub-activity creation returned no row';
  end if;

  if p_participant_ids is null or pg_catalog.cardinality(p_participant_ids) = 0 then
    raise exception using errcode = '23514', message = 'a sub-activity requires at least one participant';
  end if;
  if exists (select 1 from pg_catalog.unnest(p_participant_ids) as selected(id) where selected.id is null) then
    raise exception using errcode = '23514', message = 'sub-activity participant ids must not contain null';
  end if;
  select pg_catalog.count(*), pg_catalog.count(distinct selected.id)
    into v_input_count, v_distinct_count
  from pg_catalog.unnest(p_participant_ids) as selected(id);
  if v_input_count <> v_distinct_count then
    raise exception using errcode = '23514', message = 'sub-activity participant ids must be unique';
  end if;

  select pg_catalog.count(*) into v_active_count
  from public.participants as participant
  where participant.activity_id = p_activity_id
    and participant.id = any (p_participant_ids)
    and not participant.is_deleted;
  if v_active_count <> v_input_count then
    raise exception using errcode = '23514', message = 'all sub-activity participants must be active in the same activity';
  end if;

  insert into public.sub_activity_participants (activity_id, ledger_unit_id, participant_id)
  select p_activity_id, v_ledger_unit_id, selected.id
  from pg_catalog.unnest(p_participant_ids) as selected(id);

  update public.ledger_units
  set participant_scope_configured = true
  where id = v_ledger_unit_id and activity_id = p_activity_id;

  return query select v_parent_activity_id, v_ledger_unit_id, v_name, v_type;
end;
$function$;

create or replace function private.create_sub_activity_all_impl(
  p_activity_id uuid,
  p_name text
)
returns table (
  parent_activity_id uuid,
  ledger_unit_id uuid,
  created_name text,
  created_type public.ledger_unit_type
)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_parent_activity_id uuid;
  v_ledger_unit_id uuid;
  v_name text;
  v_type public.ledger_unit_type;
  v_participant_ids uuid[];
begin
  -- Preserve the deployed two-argument RPC for older clients by freezing the
  -- whole active Activity list as this newly-created child's explicit scope.
  select created.parent_activity_id, created.ledger_unit_id,
         created.created_name, created.created_type
    into v_parent_activity_id, v_ledger_unit_id, v_name, v_type
  from private.create_sub_activity_impl(p_activity_id, p_name) as created;
  if not found then
    raise exception using errcode = 'P0001', message = 'sub-activity creation returned no row';
  end if;

  select pg_catalog.array_agg(participant.id order by participant.participant_order)
    into v_participant_ids
  from public.participants as participant
  where participant.activity_id = p_activity_id and not participant.is_deleted;
  if v_participant_ids is null or pg_catalog.cardinality(v_participant_ids) = 0 then
    raise exception using errcode = '23514', message = 'a sub-activity requires at least one active participant';
  end if;

  insert into public.sub_activity_participants (activity_id, ledger_unit_id, participant_id)
  select p_activity_id, v_ledger_unit_id, selected.id
  from pg_catalog.unnest(v_participant_ids) as selected(id);

  update public.ledger_units
  set participant_scope_configured = true
  where id = v_ledger_unit_id and activity_id = p_activity_id;

  return query select v_parent_activity_id, v_ledger_unit_id, v_name, v_type;
end;
$function$;

create or replace function public.create_sub_activity(
  activity_id uuid,
  name text
)
returns table (
  parent_activity_id uuid,
  ledger_unit_id uuid,
  created_name text,
  created_type public.ledger_unit_type
)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select * from private.create_sub_activity_all_impl($1, $2);
$function$;

-- No default for participant_ids: PostgREST must distinguish this explicit
-- scoped request from the backward-compatible two-argument overload.
create or replace function public.create_sub_activity(
  activity_id uuid,
  name text,
  participant_ids uuid[]
)
returns table (
  parent_activity_id uuid,
  ledger_unit_id uuid,
  created_name text,
  created_type public.ledger_unit_type
)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select * from private.create_sub_activity_scoped_impl($1, $2, $3);
$function$;

revoke all on function private.create_sub_activity_scoped_impl(uuid, text, uuid[])
  from public, anon, authenticated;
revoke all on function private.create_sub_activity_all_impl(uuid, text)
  from public, anon, authenticated;
-- No API caller may invoke the old implementation directly, because that
-- would create a child without recording its explicit scope. The new definer
-- helpers retain owner access to it internally.
revoke all on function private.create_sub_activity_impl(uuid, text)
  from public, anon, authenticated, service_role;
grant execute on function private.create_sub_activity_scoped_impl(uuid, text, uuid[])
  to authenticated;
grant execute on function private.create_sub_activity_all_impl(uuid, text)
  to authenticated;

revoke all on function public.create_sub_activity(uuid, text)
  from public, anon;
revoke all on function public.create_sub_activity(uuid, text, uuid[])
  from public, anon;
grant execute on function public.create_sub_activity(uuid, text)
  to authenticated;
grant execute on function public.create_sub_activity(uuid, text, uuid[])
  to authenticated;

create or replace function private.enforce_sub_activity_participant_scope()
returns trigger
language plpgsql
volatile
security invoker
set search_path = ''
as $function$
declare
  v_ledger_unit_id uuid;
  v_activity_id uuid;
  v_ledger_unit_type public.ledger_unit_type;
  v_scope_configured boolean;
  v_participant_in_scope boolean;
begin
  select expense.ledger_unit_id, unit.activity_id, unit.type, unit.participant_scope_configured
    into v_ledger_unit_id, v_activity_id, v_ledger_unit_type, v_scope_configured
  from public.expenses as expense
  join public.ledger_units as unit on unit.id = expense.ledger_unit_id
  where expense.id = new.expense_id;
  if not found then
    raise exception using errcode = '23503', message = 'expense ledger unit was not found';
  end if;

  if v_ledger_unit_type <> 'sub_activity'::public.ledger_unit_type then
    return new;
  end if;

  if not v_scope_configured then
    -- Existing sub-activities predate persisted selection and remain
    -- legacy-unscoped; never infer or invent their historical selection.
    return new;
  end if;

  select exists (
    select 1 from public.sub_activity_participants as scoped
    where scoped.activity_id = v_activity_id
      and scoped.ledger_unit_id = v_ledger_unit_id
      and scoped.participant_id = new.participant_id
  ) into v_participant_in_scope;
  if not v_participant_in_scope then
    if tg_table_name = 'payments' then
      raise exception using errcode = '23514', message = 'payment participant is outside the configured sub-activity scope';
    else
      raise exception using errcode = '23514', message = 'split participant is outside the configured sub-activity scope';
    end if;
  end if;
  return new;
end;
$function$;

revoke all on function private.enforce_sub_activity_participant_scope()
  from public, anon, authenticated, service_role;

create trigger payments_sub_activity_participant_scope
before insert or update of expense_id, participant_id on public.payments
for each row execute function private.enforce_sub_activity_participant_scope();

create trigger splits_sub_activity_participant_scope
before insert or update of expense_id, participant_id on public.splits
for each row execute function private.enforce_sub_activity_participant_scope();

-- The composite Expense/ledger-unit foreign key on expense_debts prevents a
-- ledger-unit move while the old generated debt projection still exists.
-- Clear only that Expense's rebuildable projection before an eligible move;
-- the projection wrapper reconstructs debts, allocations, prepayment usages,
-- and bilateral balances after the new Expense facts and children are saved.
-- Preserve the existing permanent financial lock before cascading any rows.
create or replace function private.update_expense_projected_impl(
  p_expense_id uuid,
  p_ledger_unit_id uuid,
  p_title text,
  p_original_amount numeric(20,4),
  p_original_currency character(3),
  p_fx_rate numeric(20,10),
  p_split_method public.expense_split_method,
  p_payments jsonb,
  p_manual_splits jsonb,
  p_aa_participant_ids uuid[],
  p_occurred_at timestamptz,
  p_note text,
  p_original_expense_id uuid
)
returns table(updated_expense_id uuid, base_amount numeric(20,1), version bigint)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_updated_expense_id uuid;
  v_base_amount numeric(20,1);
  v_version bigint;
  v_activity_id uuid;
  v_archived_at timestamptz;
  v_current_ledger_unit_id uuid;
  v_user_id uuid := (select auth.uid());
begin
  select lu.activity_id into v_activity_id
  from public.expenses as e
  join public.ledger_units as lu on lu.id = e.ledger_unit_id
  where e.id = p_expense_id;
  if not found then
    raise exception using errcode = 'P0002', message = 'expense was not found';
  end if;

  perform private.lock_debt_projection_activity(v_activity_id);

  select a.archived_at into v_archived_at
  from public.activities as a
  where a.id = v_activity_id and not a.is_deleted
  for update of a;
  if not found then
    raise exception using errcode = 'P0002', message = 'activity was not found for financial write';
  end if;
  if v_archived_at is not null then
    raise exception using errcode = '55000', message = 'archived activity is read-only';
  end if;

  select e.ledger_unit_id into v_current_ledger_unit_id
  from public.expenses as e
  where e.id = p_expense_id
  for update of e;
  if not found then
    raise exception using errcode = 'P0002', message = 'expense was not found';
  end if;

  if p_ledger_unit_id is distinct from v_current_ledger_unit_id then
    if v_user_id is null then
      raise exception using errcode = '28000', message = 'authentication is required';
    end if;
    if not exists (
      select 1 from public.activity_members as member
      where member.activity_id = v_activity_id
        and member.user_id = v_user_id
    ) then
      raise exception using errcode = '42501', message = 'caller is not an activity member';
    end if;

    if exists (
      select 1 from public.expenses as e
      where e.id = p_expense_id and e.financial_locked
    ) or exists (
      select 1 from public.transfer_source_expenses as source
      where source.expense_id = p_expense_id
    ) or exists (
      select 1 from private.expense_refund_sources as refund_source
      where refund_source.original_expense_id = p_expense_id
    ) or exists (
      select 1
      from public.expense_debts as debt
      join public.transfer_allocations as allocation
        on allocation.activity_id = debt.activity_id
       and allocation.expense_debt_id = debt.id
      join public.transfers as transfer on transfer.id = allocation.transfer_id
      where debt.expense_id = p_expense_id
        and not transfer.is_voided
        and coalesce(allocation.base_amount, allocation.amount) > 0
    ) then
      raise exception using errcode = '23514', message = 'settled expense financial fields are immutable';
    end if;

    delete from public.expense_debts as debt
    where debt.expense_id = p_expense_id;
  end if;

  select updated.updated_expense_id, updated.base_amount, updated.version
    into v_updated_expense_id, v_base_amount, v_version
  from private.update_expense_impl(
    p_expense_id, p_ledger_unit_id, p_title, p_original_amount,
    p_original_currency, p_fx_rate, p_split_method, p_payments,
    p_manual_splits, p_aa_participant_ids, p_occurred_at, p_note,
    p_original_expense_id
  ) as updated;

  perform private.rebuild_expense_and_bilateral_debts(v_updated_expense_id, v_activity_id);
  return query select v_updated_expense_id, v_base_amount, v_version;
end;
$function$;

commit;
