begin;

-- Linked refunds are negative Expenses. Keep an append-only source marker so
-- the original Expense stays financially locked even after a refund is soft
-- deleted or later edited to a different link.
create table if not exists private.expense_refund_sources (
  activity_id uuid not null references public.activities(id) on delete restrict,
  original_expense_id uuid not null references public.expenses(id) on delete restrict,
  refund_expense_id uuid not null references public.expenses(id) on delete restrict,
  first_linked_at timestamptz not null default pg_catalog.now(),
  constraint expense_refund_sources_identity_key
    primary key (original_expense_id, refund_expense_id),
  constraint expense_refund_sources_not_self
    check (original_expense_id <> refund_expense_id)
);

comment on table private.expense_refund_sources is
  'Append-only history that permanently locks an original Expense once a linked refund has existed.';

comment on column public.expenses.financial_locked is
  'Derived read-only marker: true once a real settlement transfer has touched this expense or it has had a linked refund; prepayment_usages alone does not set it.';

alter table private.expense_refund_sources enable row level security;
revoke all on table private.expense_refund_sources
  from public, anon, authenticated, service_role;

create or replace function private.reject_expense_refund_source_mutation()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
begin
  raise exception using errcode = '23514',
    message = 'linked refund history is immutable';
end;
$function$;

drop trigger if exists expense_refund_sources_immutable
  on private.expense_refund_sources;
create trigger expense_refund_sources_immutable
before update or delete on private.expense_refund_sources
for each row execute function private.reject_expense_refund_source_mutation();

revoke all on function private.reject_expense_refund_source_mutation()
  from public, anon, authenticated, service_role;

-- Treat a refund source marker like transfer history for both financial
-- mutations and the read-only financial_locked projection. Presentation
-- fields remain editable through update_expense_presentation.
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
    from private.expense_refund_sources ers
    where ers.original_expense_id = old.id
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

  -- Only an existing append-only transfer or refund source may set this marker,
  -- and it can never be cleared.
  if new.financial_locked is distinct from old.financial_locked then
    if old.financial_locked or not new.financial_locked or not (
      exists (
        select 1 from public.transfer_source_expenses tse
        where tse.expense_id = old.id
      ) or exists (
        select 1 from private.expense_refund_sources ers
        where ers.original_expense_id = old.id
      )
    ) then
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
    or new.fx_rate_source is distinct from old.fx_rate_source
    or new.fx_rate_observed_at is distinct from old.fx_rate_observed_at
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

revoke all on function private.assert_expense_financial_mutation_allowed()
  from public, anon, authenticated, service_role;

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
    select 1 from public.transfer_source_expenses tse
    where tse.expense_id in (v_old_expense_id, v_new_expense_id)
  ) or exists (
    select 1 from private.expense_refund_sources ers
    where ers.original_expense_id in (v_old_expense_id, v_new_expense_id)
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
    raise exception using errcode = '23514',
      message = 'settled expense financial children are immutable';
  end if;
  if tg_op = 'DELETE' then return old; else return new; end if;
end;
$function$;

revoke all on function private.assert_expense_children_mutation_allowed()
  from public, anon, authenticated, service_role;

-- Serialize validation with all other writes to the Activity. The parent row
-- share lock also protects the positive, active source while the refund is
-- being checked. The trigger covers both auto-rate RPCs and any internal or
-- service write path that can insert or financially update an Expense.
create or replace function private.assert_linked_refund_integrity()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_activity_id uuid;
  v_activity_deleted boolean;
  v_unit_deleted boolean;
  v_parent_activity_id uuid;
  v_parent_activity_deleted boolean;
  v_parent_unit_deleted boolean;
  v_parent_deleted boolean;
  v_parent_original_expense_id uuid;
  v_parent_amount numeric(20,4);
  v_parent_currency character(3);
  v_parent_fx_rate numeric(20,10);
  v_active_refund_total numeric;
begin
  if tg_op = 'INSERT' then
    if new.original_expense_id is null then
      return new;
    end if;
  elsif old.original_expense_id is null and new.original_expense_id is null then
    return new;
  end if;

  select lu.activity_id, a.is_deleted, lu.is_deleted
    into v_activity_id, v_activity_deleted, v_unit_deleted
  from public.ledger_units lu
  join public.activities a on a.id = lu.activity_id
  where lu.id = new.ledger_unit_id;
  if not found then
    raise exception using errcode = '22023', message = 'refund ledger unit is unavailable';
  end if;

  perform private.lock_debt_projection_activity(v_activity_id);

  -- Soft deleting a historical refund releases its active cap; the append-only
  -- source row recorded on its original insertion keeps the parent locked.
  if new.is_deleted or new.original_expense_id is null then
    return new;
  end if;

  if v_activity_deleted or v_unit_deleted then
    raise exception using errcode = '22023', message = 'refund ledger unit is unavailable';
  end if;
  if new.original_amount >= 0 then
    raise exception using errcode = '22023', message = 'linked refund amount must be negative';
  end if;

  select plu.activity_id, pa.is_deleted, plu.is_deleted, p.is_deleted,
         p.original_expense_id, p.original_amount, p.original_currency, p.fx_rate
    into v_parent_activity_id, v_parent_activity_deleted, v_parent_unit_deleted,
         v_parent_deleted, v_parent_original_expense_id, v_parent_amount,
         v_parent_currency, v_parent_fx_rate
  from public.expenses p
  join public.ledger_units plu on plu.id = p.ledger_unit_id
  join public.activities pa on pa.id = plu.activity_id
  where p.id = new.original_expense_id
  for share of p, plu, pa;

  if not found
     or v_parent_activity_id is distinct from v_activity_id
     or v_parent_deleted
     or v_parent_unit_deleted
     or v_parent_activity_deleted
     or v_parent_original_expense_id is not null
     or v_parent_amount <= 0 then
    raise exception using errcode = '22023',
      message = 'refund reference must be an active positive expense in the same activity';
  end if;
  if new.original_currency is distinct from v_parent_currency then
    raise exception using errcode = '22023',
      message = 'linked refund currency must match original expense';
  end if;
  if new.fx_rate is distinct from v_parent_fx_rate then
    raise exception using errcode = '22023',
      message = 'linked refund must inherit the original expense FX rate';
  end if;

  if exists (
    select 1
    from public.expenses r
    where r.original_expense_id = new.original_expense_id
      and not r.is_deleted
      and (new.id is null or r.id <> new.id)
      and r.original_currency is distinct from v_parent_currency
  ) then
    raise exception using errcode = '22023',
      message = 'active linked refunds must use the original expense currency';
  end if;

  select coalesce(sum(abs(r.original_amount)), 0)
    into v_active_refund_total
  from public.expenses r
  where r.original_expense_id = new.original_expense_id
    and not r.is_deleted
    and (new.id is null or r.id <> new.id);

  if v_active_refund_total + abs(new.original_amount) > v_parent_amount then
    raise exception using errcode = '23514',
      message = 'active linked refunds cannot exceed the original expense amount';
  end if;

  return new;
end;
$function$;

drop trigger if exists expenses_linked_refund_guard on public.expenses;
create trigger expenses_linked_refund_guard
before insert or update of ledger_unit_id, original_amount, original_currency,
  fx_rate,
  original_expense_id, is_deleted
on public.expenses
for each row execute function private.assert_linked_refund_integrity();

revoke all on function private.assert_linked_refund_integrity()
  from public, anon, authenticated, service_role;

create or replace function private.mark_expense_refund_financial_locked()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
begin
  update public.expenses e
  set financial_locked = true
  where e.id = new.original_expense_id
    and not e.is_deleted
    and not e.financial_locked;
  return new;
end;
$function$;

drop trigger if exists expense_refund_sources_mark_expense_locked
  on private.expense_refund_sources;
create trigger expense_refund_sources_mark_expense_locked
after insert on private.expense_refund_sources
for each row execute function private.mark_expense_refund_financial_locked();

revoke all on function private.mark_expense_refund_financial_locked()
  from public, anon, authenticated, service_role;

create or replace function private.capture_expense_refund_source()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_activity_id uuid;
begin
  if new.original_expense_id is null or new.is_deleted then
    return new;
  end if;

  select lu.activity_id into v_activity_id
  from public.expenses p
  join public.ledger_units lu on lu.id = p.ledger_unit_id
  where p.id = new.original_expense_id;
  if not found then
    raise exception using errcode = '22023', message = 'refund source expense was not found';
  end if;

  insert into private.expense_refund_sources(
    activity_id, original_expense_id, refund_expense_id
  ) values (
    v_activity_id, new.original_expense_id, new.id
  ) on conflict (original_expense_id, refund_expense_id) do nothing;

  return new;
end;
$function$;

drop trigger if exists expenses_capture_refund_source on public.expenses;
create trigger expenses_capture_refund_source
after insert or update of original_expense_id on public.expenses
for each row execute function private.capture_expense_refund_source();

revoke all on function private.capture_expense_refund_source()
  from public, anon, authenticated, service_role;

-- Auto-rate edits write the resolved FX source and observation timestamp in a
-- second statement. Check the complete inherited snapshot at transaction end
-- so the public RPC can finish both writes atomically.
create or replace function private.assert_linked_refund_fx_snapshot()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_refund_is_deleted boolean;
  v_refund_original_expense_id uuid;
  v_refund_currency character(3);
  v_refund_fx_rate numeric(20,10);
  v_refund_fx_source text;
  v_refund_fx_observed_at timestamptz;
  v_parent_currency character(3);
  v_parent_fx_rate numeric(20,10);
  v_parent_fx_source text;
  v_parent_fx_observed_at timestamptz;
begin
  select r.is_deleted, r.original_expense_id, r.original_currency,
         r.fx_rate, r.fx_rate_source, r.fx_rate_observed_at,
         p.original_currency, p.fx_rate, p.fx_rate_source, p.fx_rate_observed_at
    into v_refund_is_deleted, v_refund_original_expense_id, v_refund_currency,
         v_refund_fx_rate, v_refund_fx_source, v_refund_fx_observed_at,
         v_parent_currency, v_parent_fx_rate, v_parent_fx_source,
         v_parent_fx_observed_at
  from public.expenses r
  join public.expenses p on p.id = r.original_expense_id
  where r.id = new.id;

  if not found or v_refund_is_deleted or v_refund_original_expense_id is null then
    return new;
  end if;
  if v_refund_currency is distinct from v_parent_currency
     or v_refund_fx_rate is distinct from v_parent_fx_rate
     or v_refund_fx_source is distinct from v_parent_fx_source
     or v_refund_fx_observed_at is distinct from v_parent_fx_observed_at then
    raise exception using errcode = '22023',
      message = 'linked refund must inherit the original expense FX snapshot';
  end if;
  return new;
end;
$function$;

create constraint trigger expenses_linked_refund_fx_snapshot_guard
after insert or update of original_expense_id, original_currency, fx_rate,
  fx_rate_source, fx_rate_observed_at
on public.expenses
deferrable initially deferred
for each row execute function private.assert_linked_refund_fx_snapshot();

revoke all on function private.assert_linked_refund_fx_snapshot()
  from public, anon, authenticated, service_role;

-- Backfill every extant link, including soft-deleted refunds, because their
-- prior active lifecycle cannot otherwise be distinguished from a deleted
-- refund created after the finance model was introduced.
insert into private.expense_refund_sources(
  activity_id, original_expense_id, refund_expense_id
)
select plu.activity_id, refund.original_expense_id, refund.id
from public.expenses refund
join public.expenses parent on parent.id = refund.original_expense_id
join public.ledger_units plu on plu.id = parent.ledger_unit_id
where refund.original_expense_id is not null
on conflict (original_expense_id, refund_expense_id) do nothing;

-- The source trigger marks active parents as it backfills; this statement also
-- repairs the denormalized flag for any preexisting marker row.
update public.expenses parent
set financial_locked = true
where not parent.is_deleted
  and not parent.financial_locked
  and exists (
    select 1 from private.expense_refund_sources ers
    where ers.original_expense_id = parent.id
  );

-- Legacy financial writes remain available to trusted server-side work but
-- are no longer authenticated or anonymous client RPCs. PUBLIC is revoked as
-- well because its default EXECUTE grant otherwise reaches both client roles.
do $revoke_legacy$
declare
  v_signature text;
  v_function regprocedure;
  v_service_role_had_execute boolean;
begin
  foreach v_signature in array array[
    'public.create_expense(uuid,text,numeric,character,numeric,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)',
    'public.create_expense(uuid,text,numeric,character,numeric,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid,text)',
    'public.update_expense(uuid,uuid,text,numeric,character,numeric,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)',
    'public.update_expense(uuid,uuid,text,numeric,character,numeric,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid,text)',
    'public.create_settlement_transfer(uuid,uuid,uuid,numeric,timestamptz,uuid)',
    'public.create_settlement_transfer(uuid,uuid,uuid,numeric,character,timestamptz,uuid,uuid)',
    'public.create_prepayment(uuid,uuid,uuid,numeric,timestamptz,uuid)',
    'public.create_prepayment_return(uuid,uuid,uuid,numeric,timestamptz,uuid)',
    'public.create_final_settlement(uuid,uuid,uuid,numeric,timestamptz,uuid)',
    'public.execute_final_settlement(uuid,uuid,uuid,numeric,timestamptz,uuid)',
    'public.execute_final_settlement_item(uuid,uuid,uuid,numeric,timestamptz,uuid)'
  ] loop
    v_function := pg_catalog.to_regprocedure(v_signature);
    if v_function is null then
      raise exception 'expected legacy RPC signature is missing: %', v_signature;
    end if;
    select pg_catalog.has_function_privilege('service_role', v_function::oid, 'EXECUTE')
      into v_service_role_had_execute;
    execute pg_catalog.format(
      'revoke all on function %s from public, anon, authenticated', v_function
    );
    if v_service_role_had_execute then
      execute pg_catalog.format(
        'grant execute on function %s to service_role', v_function
      );
    end if;
  end loop;
end;
$revoke_legacy$;

-- Reassert authenticated client access for current finance contracts after
-- closing the old entry points. Trusted server-side clients keep their access.
do $grant_current$
declare
  v_signature text;
  v_function regprocedure;
  v_service_role_had_execute boolean;
begin
  foreach v_signature in array array[
    'public.create_expense_auto_rate(uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)',
    'public.create_expense_auto_rate(uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid,text)',
    'public.update_expense_auto_rate(uuid,uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)',
    'public.update_expense_auto_rate(uuid,uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid,text)',
    'public.update_expense_presentation(uuid,text,text,text,bigint)',
    'public.create_expense_repayment_v2(uuid,uuid,uuid,numeric,character,text,uuid[],timestamptz,uuid,bigint,uuid)',
    'public.preview_expense_repayment(uuid,uuid,uuid,numeric,character,text,uuid[],bigint)',
    'public.list_transfer_expense_candidates(uuid,uuid,uuid,character)',
    'public.get_expense_repayment_progress(uuid,uuid)',
    'public.preview_prepayment(uuid,uuid,uuid,numeric,character)',
    'public.create_prepayment_v2(uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid)',
    'public.create_prepayment_return_v2(uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid)',
    'public.preview_final_settlement_v2(uuid,text)',
    'public.create_final_settlement_v2(uuid,uuid,uuid,numeric,character,text,bigint,uuid,timestamptz,uuid)',
    'public.execute_final_settlement_v2(uuid,uuid,uuid,numeric,character,text,bigint,uuid,timestamptz,uuid)'
  ] loop
    v_function := pg_catalog.to_regprocedure(v_signature);
    if v_function is null then
      raise exception 'expected current finance RPC signature is missing: %', v_signature;
    end if;
    select pg_catalog.has_function_privilege('service_role', v_function::oid, 'EXECUTE')
      into v_service_role_had_execute;
    execute pg_catalog.format(
      'revoke all on function %s from public, anon', v_function
    );
    execute pg_catalog.format(
      'grant execute on function %s to authenticated', v_function
    );
    if v_service_role_had_execute then
      execute pg_catalog.format(
        'grant execute on function %s to service_role', v_function
      );
    end if;
  end loop;
end;
$grant_current$;

commit;
