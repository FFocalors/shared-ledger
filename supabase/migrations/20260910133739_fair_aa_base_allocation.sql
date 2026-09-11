begin;

-- Equal splits use the Activity's stable participant order.  Work in the
-- base currency's 0.1 unit so every allocated value is representable by the
-- persisted numeric(20,1) contract and the sum always equals Expense.base_amount.
create or replace function private.redistribute_aa_split_base_amounts(p_expense_id uuid)
returns void
language sql
volatile
security definer
set search_path = ''
as $function$
  with ranked as (
    select
      s.id as split_id,
      pg_catalog.row_number() over (
        order by p.participant_order, p.id
      )::bigint as allocation_index,
      pg_catalog.count(*) over ()::bigint as participant_count,
      (e.base_amount * 10)::bigint as total_units
    from public.expenses as e
    join public.splits as s on s.expense_id = e.id
    join public.ledger_units as lu on lu.id = e.ledger_unit_id
    join public.participants as p
      on p.activity_id = lu.activity_id
     and p.id = s.participant_id
    where e.id = $1
      and e.split_method = 'aa'::public.expense_split_method
      and not e.is_deleted
  ),
  allocation as (
    select
      split_id,
      allocation_index,
      total_units / participant_count as quotient_units,
      total_units % participant_count as remainder_units
    from ranked
  )
  update public.splits as s
  set base_amount = (
    (
      a.quotient_units
      + case
          when a.allocation_index <= pg_catalog.abs(a.remainder_units)
            then pg_catalog.sign(a.remainder_units)::bigint
          else 0
        end
    )::numeric / 10
  )::numeric(20,1)
  from allocation as a
  where s.id = a.split_id;
$function$;

-- Expense create, update, delete, and restore all pass through this helper.
-- Normalize the AA facts before rebuilding the authoritative projections.
create or replace function private.rebuild_expense_and_bilateral_debts(
  p_expense_id uuid,
  p_activity_id uuid
)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_archived_at timestamptz;
  v_deleted boolean;
begin
  perform private.lock_debt_projection_activity(p_activity_id);

  select a.archived_at, a.is_deleted
    into v_archived_at, v_deleted
  from public.activities as a
  where a.id = p_activity_id
  for update;

  if not found or v_deleted then
    raise exception using errcode = 'P0002', message = 'activity was not found';
  end if;
  if v_archived_at is not null then
    raise exception using errcode = '55000', message = 'archived activity is read-only';
  end if;

  perform private.redistribute_aa_split_base_amounts(p_expense_id);
  perform private.rebuild_expense_debts_locked(p_expense_id, p_activity_id);
  perform private.rebuild_transfer_allocations_locked(p_activity_id);
  perform private.rebuild_prepayment_projections_locked(p_activity_id);
  perform private.rebuild_bilateral_debts_locked(p_activity_id);

  update public.activities as a
  set financial_version = a.financial_version + 1
  where a.id = p_activity_id;
end;
$function$;

-- The repair path applies the same allocation before deriving every debt row,
-- so a full rebuild cannot revive the former "all remainder to last person"
-- result.  Like the established repair primitive, it remains version-neutral.
create or replace function private.rebuild_activity_debt_projection(p_activity_id uuid)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_expense_id uuid;
begin
  if not exists (
    select 1 from public.activities as a where a.id = p_activity_id
  ) then
    raise exception using errcode = 'P0002', message = 'activity was not found for debt rebuild';
  end if;

  perform private.lock_debt_projection_activity(p_activity_id);

  delete from public.prepayment_usages as pu where pu.activity_id = p_activity_id;
  delete from public.prepayment_accounts as pa where pa.activity_id = p_activity_id;
  delete from public.transfer_allocations as ta where ta.activity_id = p_activity_id;
  delete from public.expense_debts as ed where ed.activity_id = p_activity_id;

  for v_expense_id in
    select e.id
    from public.expenses as e
    join public.ledger_units as lu on lu.id = e.ledger_unit_id
    join public.activities as a on a.id = lu.activity_id
    where lu.activity_id = p_activity_id
      and not e.is_deleted
      and not lu.is_deleted
      and not a.is_deleted
    order by e.id
  loop
    perform private.redistribute_aa_split_base_amounts(v_expense_id);
    perform private.rebuild_expense_debts_locked(v_expense_id, p_activity_id);
  end loop;

  perform private.rebuild_transfer_allocations_locked(p_activity_id);
  perform private.rebuild_prepayment_projections_locked(p_activity_id);
  perform private.rebuild_bilateral_debts_locked(p_activity_id);
end;
$function$;

revoke all on function private.redistribute_aa_split_base_amounts(uuid)
  from public, anon, authenticated;
revoke all on function private.rebuild_expense_and_bilateral_debts(uuid, uuid)
  from public, anon, authenticated;
revoke all on function private.rebuild_activity_debt_projection(uuid)
  from public, anon, authenticated;
grant execute on function private.rebuild_activity_debt_projection(uuid)
  to service_role;

-- Existing active AA expenses are test data, so normalize them in place and
-- rebuild their projections.  Advancing financial_version invalidates any
-- cached settlement preview that was calculated from the old allocation.
do $backfill$
declare
  v_activity_id uuid;
begin
  for v_activity_id in
    select distinct lu.activity_id
    from public.expenses as e
    join public.ledger_units as lu on lu.id = e.ledger_unit_id
    join public.activities as a on a.id = lu.activity_id
    where e.split_method = 'aa'::public.expense_split_method
      and not e.is_deleted
      and not lu.is_deleted
      and not a.is_deleted
    order by lu.activity_id
  loop
    perform private.rebuild_activity_debt_projection(v_activity_id);
    update public.activities as a
    set financial_version = a.financial_version + 1
    where a.id = v_activity_id;
  end loop;
end;
$backfill$;

commit;
