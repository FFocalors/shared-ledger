begin;

-- `transfer_source_expenses` is the append-only source of truth for a real
-- settlement touching an Expense.  Keep a denormalized, read-only marker on
-- the Expense so list/detail clients can disable financial editing even after
-- the transfer itself has been voided.  The source table remains canonical;
-- this flag is only a client-facing projection of that history.
alter table public.expenses
  add column if not exists financial_locked boolean not null default false;

comment on column public.expenses.financial_locked is
  'Derived read-only marker: true once a real settlement transfer has touched this expense; prepayment_usages alone does not set it.';

update public.expenses e
set financial_locked = true
from public.transfer_source_expenses tse
where tse.expense_id = e.id
  and not e.is_deleted
  and not e.financial_locked;

create or replace function private.mark_expense_financial_locked()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
begin
  update public.expenses e
  set financial_locked = true
  where e.id = new.expense_id
    and not e.financial_locked;
  return new;
end;
$function$;

drop trigger if exists transfer_source_expenses_mark_expense_locked
  on public.transfer_source_expenses;
create trigger transfer_source_expenses_mark_expense_locked
after insert on public.transfer_source_expenses
for each row execute function private.mark_expense_financial_locked();
revoke all on function private.mark_expense_financial_locked()
  from public, anon, authenticated;

-- Preserve the historical freeze after a transfer is voided.  Presentation
-- fields remain editable; all financial fields and lifecycle transitions stay
-- blocked once source history exists (or the derived marker is true).
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

  select old.financial_locked or exists (
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

  -- Only the internal source-history trigger may move this marker from false
  -- to true, and the marker can never be cleared.
  if new.financial_locked is distinct from old.financial_locked then
    if old.financial_locked or not exists (
      select 1 from public.transfer_source_expenses tse
      where tse.expense_id = old.id
    ) or not new.financial_locked then
      raise exception using errcode = '55000', message = 'expense financial lock is immutable';
    end if;
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

-- Child rows must stay attached to the same historical Expense.  Check both
-- old and new expense IDs on UPDATE so a privileged maintenance path cannot
-- move a payment/split away from a locked Expense.
create or replace function private.assert_expense_children_mutation_allowed()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_old_expense_id uuid;
  v_new_expense_id uuid;
begin
  if tg_op = 'INSERT' then
    v_new_expense_id := new.expense_id;
  elsif tg_op = 'DELETE' then
    v_old_expense_id := old.expense_id;
  else
    v_old_expense_id := old.expense_id;
    v_new_expense_id := new.expense_id;
  end if;

  if exists (
    select 1 from public.expenses e
    where e.id in (v_old_expense_id, v_new_expense_id)
      and e.financial_locked
  ) or exists (
    select 1
    from public.transfer_source_expenses tse
    where tse.expense_id in (v_old_expense_id, v_new_expense_id)
  ) or exists (
    select 1
    from public.expense_debts ed
    join public.transfer_allocations ta
      on ta.activity_id = ed.activity_id and ta.expense_debt_id = ed.id
    join public.transfers t on t.id = ta.transfer_id
    where ed.expense_id in (v_old_expense_id, v_new_expense_id)
      and not t.is_voided
      and coalesce(ta.base_amount, ta.amount) > 0
  ) then
    raise exception using errcode = '23514', message = 'settled expense financial children are immutable';
  end if;
  if tg_op = 'DELETE' then return old; else return new; end if;
end;
$function$;
revoke all on function private.assert_expense_financial_mutation_allowed(),
  private.assert_expense_children_mutation_allowed()
  from public, anon, authenticated;

-- A dedicated presentation-only write avoids the existing full Expense update
-- path deleting and recreating payments/splits.  It works for both unsettled
-- and financially locked Expenses, while never accepting financial fields.
create or replace function private.update_expense_presentation_impl(
  p_expense_id uuid,
  p_title text,
  p_note text,
  p_icon_key text,
  p_expected_version bigint default null
)
returns table(
  updated_expense_id uuid,
  version bigint,
  financial_version bigint,
  financial_locked boolean
)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_user uuid := (select auth.uid());
  v_activity_id uuid;
  v_archived_at timestamptz;
  v_activity_deleted boolean;
  v_expense_deleted boolean;
  v_version bigint;
  v_financial_version bigint;
  v_financial_locked boolean;
  v_title text := pg_catalog.btrim(p_title);
  v_icon_key text;
begin
  if v_user is null then
    raise exception using errcode = '28000', message = 'authentication is required';
  end if;
  if v_title is null or pg_catalog.length(v_title) = 0 then
    raise exception using errcode = '22023', message = 'expense title is required';
  end if;

  select lu.activity_id
    into v_activity_id
  from public.expenses e
  join public.ledger_units lu on lu.id = e.ledger_unit_id
  join public.activities a on a.id = lu.activity_id
  where e.id = p_expense_id
    and not lu.is_deleted;
  if not found then
    raise exception using errcode = 'P0002', message = 'expense was not found';
  end if;

  perform private.lock_debt_projection_activity(v_activity_id);
  select a.archived_at, a.is_deleted
    into v_archived_at, v_activity_deleted
  from public.activities a
  where a.id = v_activity_id
  for update;
  if not found or v_activity_deleted then
    raise exception using errcode = 'P0002', message = 'activity was not found';
  end if;
  if v_archived_at is not null then
    raise exception using errcode = '55000', message = 'archived activity is read-only';
  end if;

  select e.is_deleted, e.version, e.financial_locked
    into v_expense_deleted, v_version, v_financial_locked
  from public.expenses e
  where e.id = p_expense_id
  for update;
  if v_expense_deleted then
    raise exception using errcode = '55000', message = 'deleted expense cannot be modified or restored';
  end if;
  if p_expected_version is not null and v_version <> p_expected_version then
    raise exception using errcode = '40001', message = 'expense version mismatch; refresh the expense';
  end if;
  if not exists (
    select 1 from public.activity_members am
    where am.activity_id = v_activity_id and am.user_id = v_user
  ) then
    raise exception using errcode = '42501', message = 'caller is not an activity member';
  end if;

  v_icon_key := private.normalize_expense_icon_key(p_icon_key);
  update public.expenses e
  set title = v_title,
      note = p_note,
      icon_key = v_icon_key,
      updated_by = v_user,
      version = e.version + 1
  where e.id = p_expense_id
  returning e.version into v_version;

  select a.financial_version
    into v_financial_version
  from public.activities a
  where a.id = v_activity_id;

  return query select p_expense_id, v_version, v_financial_version, v_financial_locked;
end;
$function$;

create or replace function public.update_expense_presentation(
  expense_id uuid,
  title text,
  note text default null,
  icon_key text default 'money',
  expected_version bigint default null
)
returns table(
  updated_expense_id uuid,
  version bigint,
  financial_version bigint,
  financial_locked boolean
)
language sql
volatile
security invoker
set search_path = ''
as $function$
select * from private.update_expense_presentation_impl($1,$2,$3,$4,$5);
$function$;

revoke all on function private.update_expense_presentation_impl(uuid,text,text,text,bigint)
  from public, anon, authenticated, service_role;
grant execute on function private.update_expense_presentation_impl(uuid,text,text,text,bigint)
  to authenticated;
revoke all on function public.update_expense_presentation(uuid,text,text,text,bigint)
  from public, anon, authenticated, service_role;
grant execute on function public.update_expense_presentation(uuid,text,text,text,bigint)
  to authenticated;

commit;
