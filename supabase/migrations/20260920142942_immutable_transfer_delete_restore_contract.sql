begin;

-- A transfer allocation is a rebuildable projection.  Keep a separate,
-- append-only source relation so voiding a transfer or rebuilding projections
-- cannot erase the fact that the transfer touched an Expense/sub-activity.
-- Only real settlement components are recorded here.  prepayment_usages are
-- automatic projections and intentionally do not create source-history rows.
create table if not exists public.transfer_source_expenses (
  id uuid primary key default extensions.gen_random_uuid(),
  activity_id uuid not null references public.activities(id) on delete restrict,
  transfer_id uuid not null,
  expense_id uuid not null references public.expenses(id) on delete restrict,
  ledger_unit_id uuid not null references public.ledger_units(id) on delete restrict,
  component_type text not null check (component_type = 'settlement'),
  created_at timestamptz not null default pg_catalog.now(),
  constraint transfer_source_expenses_transfer_fk
    foreign key (transfer_id, activity_id)
    references public.transfers(id, activity_id) on delete restrict,
  constraint transfer_source_expenses_identity_key
    unique (transfer_id, expense_id, component_type)
);

create index if not exists transfer_source_expenses_expense_idx
  on public.transfer_source_expenses (expense_id, activity_id);
create index if not exists transfer_source_expenses_ledger_unit_idx
  on public.transfer_source_expenses (ledger_unit_id, activity_id);
create index if not exists transfer_source_expenses_transfer_idx
  on public.transfer_source_expenses (transfer_id, activity_id);
create unique index if not exists transfer_source_expenses_identity_idx
  on public.transfer_source_expenses (transfer_id, expense_id, component_type);

alter table public.transfer_source_expenses enable row level security;
revoke all on table public.transfer_source_expenses from public, anon, authenticated;
grant all on table public.transfer_source_expenses to service_role;

-- The relation is append-only.  API roles have no DML grant, but the trigger
-- also protects the history if a privileged maintenance path is ever reused.
create or replace function private.reject_transfer_source_expense_mutation()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  raise exception using errcode = '55000',
    message = 'transfer source history is immutable';
end;
$function$;

drop trigger if exists transfer_source_expenses_immutable
  on public.transfer_source_expenses;
create trigger transfer_source_expenses_immutable
before update or delete on public.transfer_source_expenses
for each row execute function private.reject_transfer_source_expense_mutation();

-- Capture ordinary settlement allocations and final-settlement path sources at
-- insert time.  Both source facts survive projection rebuilds and transfer
-- voids.  The table/unique index are created above, so this is compatible with
-- a financial-core migration that may pre-create the same named audit table.
create or replace function private.capture_transfer_source_expense()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_expense_id uuid;
  v_ledger_unit_id uuid;
begin
  if tg_table_name = 'transfer_allocations' then
    select ed.expense_id, e.ledger_unit_id
      into v_expense_id, v_ledger_unit_id
    from public.expense_debts ed
    join public.expenses e on e.id = ed.expense_id
    where ed.activity_id = new.activity_id
      and ed.id = new.expense_debt_id;

    if v_expense_id is not null then
      insert into public.transfer_source_expenses(
        activity_id, transfer_id, expense_id, ledger_unit_id, component_type
      ) values (
        new.activity_id, new.transfer_id, v_expense_id, v_ledger_unit_id,
        'settlement'
      ) on conflict (transfer_id, expense_id, component_type) do nothing;
    end if;
  elsif tg_table_name = 'final_settlement_paths'
        and new.component_type = 'settlement' then
    -- source_expense_id is the stable identity in the existing path schema;
    -- source_expense_debt_id is also retained by the multi-currency path
    -- migration, so accept either without depending on rebuildable debt IDs.
    select coalesce(new.source_expense_id, ed.expense_id), e.ledger_unit_id
      into v_expense_id, v_ledger_unit_id
    from public.expenses e
    left join public.expense_debts ed on ed.id = new.source_expense_debt_id
    where e.id = coalesce(new.source_expense_id, ed.expense_id);

    if v_expense_id is not null and v_ledger_unit_id is not null then
      insert into public.transfer_source_expenses(
        activity_id, transfer_id, expense_id, ledger_unit_id, component_type
      ) values (
        new.activity_id, new.transfer_id, v_expense_id,
        v_ledger_unit_id, 'settlement'
      ) on conflict (transfer_id, expense_id, component_type) do nothing;
    end if;
  end if;
  return new;
end;
$function$;

drop trigger if exists transfer_allocations_capture_source
  on public.transfer_allocations;
create trigger transfer_allocations_capture_source
after insert on public.transfer_allocations
for each row execute function private.capture_transfer_source_expense();

drop trigger if exists final_settlement_paths_capture_source
  on public.final_settlement_paths;
create trigger final_settlement_paths_capture_source
after insert on public.final_settlement_paths
for each row execute function private.capture_transfer_source_expense();

-- Backfill all source identities still present in the current projections and
-- immutable final-settlement paths.  Future rebuilds/voids are handled by the
-- append-only triggers above.
insert into public.transfer_source_expenses(
  activity_id, transfer_id, expense_id, ledger_unit_id, component_type
)
select ta.activity_id, ta.transfer_id, ed.expense_id, e.ledger_unit_id,
       'settlement'
from public.transfer_allocations ta
join public.expense_debts ed
  on ed.activity_id = ta.activity_id and ed.id = ta.expense_debt_id
join public.expenses e on e.id = ed.expense_id
on conflict (transfer_id, expense_id, component_type) do nothing;

insert into public.transfer_source_expenses(
  activity_id, transfer_id, expense_id, ledger_unit_id, component_type
)
select f.activity_id, f.transfer_id, coalesce(f.source_expense_id, fed.expense_id), e.ledger_unit_id,
       'settlement'
from public.final_settlement_paths f
left join public.expense_debts fed on fed.id = f.source_expense_debt_id
join public.expenses e on e.id = coalesce(f.source_expense_id, fed.expense_id)
where f.component_type = 'settlement'
  and coalesce(f.source_expense_id, fed.expense_id) is not null
on conflict (transfer_id, expense_id, component_type) do nothing;

revoke all on function private.capture_transfer_source_expense() from public, anon, authenticated;
revoke all on function private.reject_transfer_source_expense_mutation() from public, anon, authenticated;

-- A voided Transfer remains a historical fact.  The only allowed transition
-- is active -> voided through the existing void RPC; unvoid/edit/delete is
-- rejected even for a privileged table writer.
create or replace function private.assert_transfer_immutable_lifecycle()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if tg_op = 'DELETE' then
    raise exception using errcode = '55000', message = 'transfers are immutable facts';
  end if;

  if old.is_voided then
    if new is distinct from old then
      raise exception using errcode = '55000', message = 'voided transfer is immutable';
    end if;
    return new;
  end if;

  if new.activity_id is distinct from old.activity_id
     or new.from_participant_id is distinct from old.from_participant_id
     or new.to_participant_id is distinct from old.to_participant_id
     or new.type is distinct from old.type
     or new.amount is distinct from old.amount
     or new.currency is distinct from old.currency
     or new.occurred_at is distinct from old.occurred_at
     or new.recorded_by is distinct from old.recorded_by
     or new.on_behalf_of_participant_id is distinct from old.on_behalf_of_participant_id
     or new.created_at is distinct from old.created_at
     or new.request_id is distinct from old.request_id then
    raise exception using errcode = '55000', message = 'transfer financial fields are immutable';
  end if;

  if not new.is_voided and (
       new.voided_at is distinct from old.voided_at
    or new.voided_by is distinct from old.voided_by
    or new.void_reason is distinct from old.void_reason
  ) then
    raise exception using errcode = '55000', message = 'void metadata requires void transition';
  end if;

  if new.is_voided is distinct from old.is_voided and not new.is_voided then
    raise exception using errcode = '55000', message = 'voided transfer cannot be restored';
  end if;
  return new;
end;
$function$;

drop trigger if exists transfers_immutable_lifecycle on public.transfers;
create trigger transfers_immutable_lifecycle
before update or delete on public.transfers
for each row execute function private.assert_transfer_immutable_lifecycle();
revoke all on function private.assert_transfer_immutable_lifecycle() from public, anon, authenticated;

-- Settled Expense financial facts remain immutable even after the Transfer is
-- voided.  Presentation fields may still be changed while the Expense is
-- active; a deleted Expense cannot be edited or resurrected.
create or replace function private.assert_expense_financial_mutation_allowed()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_activity_id uuid;
  v_creator uuid;
  v_user uuid := (select auth.uid());
  v_settled boolean;
begin
  select lu.activity_id, a.created_by
    into v_activity_id, v_creator
  from public.ledger_units lu
  join public.activities a on a.id = lu.activity_id
  where lu.id = old.ledger_unit_id;

  select exists (
    select 1
    from public.transfer_source_expenses tse
    where tse.expense_id = old.id
  ) or exists (
    select 1
    from public.expense_debts ed
    join public.transfer_allocations ta
      on ta.activity_id = ed.activity_id and ta.expense_debt_id = ed.id
    join public.transfers t on t.id = ta.transfer_id
    where ed.expense_id = old.id
      and not t.is_voided
      and coalesce(ta.base_amount, ta.amount) > 0
  ) into v_settled;

  if tg_op = 'DELETE' then
    if old.is_deleted or v_settled then
      raise exception using errcode = '23514', message = 'expense is an immutable historical fact';
    end if;
    if v_creator is distinct from v_user and old.created_by is distinct from v_user then
      raise exception using errcode = '42501', message = 'only expense creator or activity creator may delete expense';
    end if;
    return old;
  end if;

  if old.is_deleted then
    raise exception using errcode = '55000', message = 'deleted expense cannot be modified or restored';
  end if;

  if old.is_deleted = false and new.is_deleted = true then
    if v_settled then
      raise exception using errcode = '23514', message = 'settled expense cannot be deleted';
    end if;
    if v_creator is distinct from v_user and old.created_by is distinct from v_user then
      raise exception using errcode = '42501', message = 'only expense creator or activity creator may delete expense';
    end if;
  end if;

  if v_settled and (
       new.ledger_unit_id is distinct from old.ledger_unit_id
    or new.original_amount is distinct from old.original_amount
    or new.original_currency is distinct from old.original_currency
    or new.fx_rate is distinct from old.fx_rate
    or new.base_amount is distinct from old.base_amount
    or new.split_method is distinct from old.split_method
    or new.occurred_at is distinct from old.occurred_at
    or new.original_expense_id is distinct from old.original_expense_id
    or new.is_deleted is distinct from old.is_deleted
  ) then
    raise exception using errcode = '23514', message = 'settled expense financial fields are immutable';
  end if;
  return new;
end;
$function$;

create or replace function private.assert_expense_children_mutation_allowed()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_expense_id uuid := case when tg_op = 'DELETE' then old.expense_id else new.expense_id end;
begin
  if exists (
    select 1 from public.transfer_source_expenses tse
    where tse.expense_id = v_expense_id
  ) or exists (
    select 1 from public.expense_debts ed
    join public.transfer_allocations ta
      on ta.activity_id = ed.activity_id and ta.expense_debt_id = ed.id
    join public.transfers t on t.id = ta.transfer_id
    where ed.expense_id = v_expense_id
      and not t.is_voided
      and coalesce(ta.base_amount, ta.amount) > 0
  ) then
    raise exception using errcode = '23514', message = 'settled expense financial children are immutable';
  end if;
  if tg_op = 'DELETE' then return old; else return new; end if;
end;
$function$;

-- A sub-activity may still be restored only when it has no real transfer
-- history.  This trigger closes the same rule for every direct update and for
-- the existing delete_sub_activity/restore_sub_activity RPCs.
create or replace function private.assert_sub_activity_transfer_history()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if new.is_deleted is distinct from old.is_deleted
     and exists (
       select 1 from public.transfer_source_expenses tse
       where tse.ledger_unit_id = old.id
     ) then
    raise exception using errcode = '23514',
      message = 'sub-activity has immutable real transfer history';
  end if;
  return new;
end;
$function$;

drop trigger if exists ledger_units_transfer_history_guard on public.ledger_units;
create trigger ledger_units_transfer_history_guard
before update of is_deleted on public.ledger_units
for each row execute function private.assert_sub_activity_transfer_history();
revoke all on function private.assert_sub_activity_transfer_history() from public, anon, authenticated;

-- Restores are removed from the public contract.  Keep old objects for
-- migration compatibility, but no API role (including service_role) can call
-- them.  Deletion and void RPCs remain the only lifecycle writes.
revoke all on function public.restore_expense(uuid), private.restore_expense_impl(uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.restore_transfer(uuid, text), private.restore_transfer_impl(uuid, text)
  from public, anon, authenticated, service_role;

commit;
