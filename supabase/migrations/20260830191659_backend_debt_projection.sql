begin;

-- Lock the stable public RPC objects before taking fact-table locks. Existing
-- calls finish first; later calls wait until this transaction commits and then
-- execute the replaced body on the same function OID. This prevents an old
-- RPC body from resuming after the one-time projection backfill.
alter function public.create_expense(
  uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) parallel unsafe;
alter function public.update_expense(
  uuid, uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) parallel unsafe;
alter function public.delete_expense(uuid) parallel unsafe;

-- Close the deployment race between the one-time backfill and swapping the
-- Phase 2 public RPC bodies for projection-aware wrappers. Take locks in
-- the established parent-to-child write order so in-flight old RPCs finish
-- first, while new old-code writes wait until backfill + wrapper swap commit.
-- SHARE ROW EXCLUSIVE conflicts with the ROW EXCLUSIVE mode used by INSERT,
-- UPDATE, and DELETE while continuing to allow read-only traffic.
lock table public.expenses in share row exclusive mode;
lock table public.payments in share row exclusive mode;
lock table public.splits in share row exclusive mode;

-- Redundant parent keys let projection rows express cross-table Activity
-- consistency with ordinary foreign keys, without adding mutable Activity
-- columns to the source-of-truth Expense rows.
alter table public.ledger_units
  add constraint ledger_units_id_activity_id_key unique (id, activity_id);
alter table public.expenses
  add constraint expenses_id_ledger_unit_id_key unique (id, ledger_unit_id);

create table public.expense_debts (
  id uuid primary key default extensions.gen_random_uuid(),
  activity_id uuid not null references public.activities(id) on delete restrict,
  ledger_unit_id uuid not null,
  expense_id uuid not null,
  debtor_participant_id uuid not null,
  creditor_participant_id uuid not null,
  amount numeric(20,1) not null check (amount > 0),
  created_at timestamptz not null default now(),
  constraint expense_debts_expense_ledger_unit_fk
    foreign key (expense_id, ledger_unit_id)
    references public.expenses(id, ledger_unit_id) on delete restrict,
  constraint expense_debts_ledger_unit_activity_fk
    foreign key (ledger_unit_id, activity_id)
    references public.ledger_units(id, activity_id) on delete restrict,
  constraint expense_debts_debtor_activity_fk
    foreign key (activity_id, debtor_participant_id)
    references public.participants(activity_id, id) on delete restrict,
  constraint expense_debts_creditor_activity_fk
    foreign key (activity_id, creditor_participant_id)
    references public.participants(activity_id, id) on delete restrict,
  constraint expense_debts_distinct_participants
    check (debtor_participant_id <> creditor_participant_id),
  constraint expense_debts_unique_result
    unique (expense_id, debtor_participant_id, creditor_participant_id)
);

create table public.bilateral_debts (
  id uuid primary key default extensions.gen_random_uuid(),
  activity_id uuid not null references public.activities(id) on delete restrict,
  debtor_participant_id uuid not null,
  creditor_participant_id uuid not null,
  amount numeric(20,1) not null check (amount > 0),
  created_at timestamptz not null default now(),
  constraint bilateral_debts_debtor_activity_fk
    foreign key (activity_id, debtor_participant_id)
    references public.participants(activity_id, id) on delete restrict,
  constraint bilateral_debts_creditor_activity_fk
    foreign key (activity_id, creditor_participant_id)
    references public.participants(activity_id, id) on delete restrict,
  constraint bilateral_debts_distinct_participants
    check (debtor_participant_id <> creditor_participant_id)
);

create index expense_debts_activity_id_idx
  on public.expense_debts (activity_id, expense_id);
create index expense_debts_expense_ledger_unit_idx
  on public.expense_debts (expense_id, ledger_unit_id);
create index expense_debts_ledger_unit_activity_idx
  on public.expense_debts (ledger_unit_id, activity_id);
create index expense_debts_activity_debtor_idx
  on public.expense_debts (activity_id, debtor_participant_id);
create index expense_debts_activity_creditor_idx
  on public.expense_debts (activity_id, creditor_participant_id);

create unique index bilateral_debts_activity_unordered_pair_key
  on public.bilateral_debts (
    activity_id,
    least(debtor_participant_id, creditor_participant_id),
    greatest(debtor_participant_id, creditor_participant_id)
  );
create index bilateral_debts_activity_debtor_idx
  on public.bilateral_debts (activity_id, debtor_participant_id);
create index bilateral_debts_activity_creditor_idx
  on public.bilateral_debts (activity_id, creditor_participant_id);

alter table public.expense_debts enable row level security;
alter table public.bilateral_debts enable row level security;

create policy expense_debts_select_member
on public.expense_debts
for select
to authenticated
using ((select private.is_activity_member(activity_id)));

create policy bilateral_debts_select_member
on public.bilateral_debts
for select
to authenticated
using ((select private.is_activity_member(activity_id)));

revoke all on table public.expense_debts, public.bilateral_debts
  from public, anon, authenticated;
grant select on table public.expense_debts, public.bilateral_debts
  to authenticated;

-- Every incremental and full rebuild for an Activity takes this same
-- transaction-scoped lock. The namespaced UUID hash is stable for identical
-- inputs, while keeping this lock family separate from future advisory locks.
create or replace function private.lock_debt_projection_activity(p_activity_id uuid)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
begin
  if p_activity_id is null then
    raise exception using errcode = '22004', message = 'activity id is required';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'shared-ledger:debt-projection:' || p_activity_id::text,
      0
    )
  );
end;
$function$;

-- Caller must already hold the Activity advisory lock. This function derives
-- participant net amounts only from normalized base amounts; FX is never
-- applied again while building debt projections.
create or replace function private.rebuild_expense_debts_locked(
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
  v_actual_activity_id uuid;
  v_ledger_unit_id uuid;
  v_is_effective boolean;
  v_net_total numeric;
  v_creditor_ids uuid[];
  v_creditor_amounts numeric[];
  v_debtor_ids uuid[];
  v_debtor_amounts numeric[];
  v_creditor_index integer := 1;
  v_debtor_index integer := 1;
  v_creditor_remaining numeric(20,1);
  v_debtor_remaining numeric(20,1);
  v_match_amount numeric(20,1);
begin
  select
    lu.activity_id,
    lu.id,
    not e.is_deleted and not lu.is_deleted and not a.is_deleted
  into v_actual_activity_id, v_ledger_unit_id, v_is_effective
  from public.expenses as e
  join public.ledger_units as lu on lu.id = e.ledger_unit_id
  join public.activities as a on a.id = lu.activity_id
  where e.id = p_expense_id;

  if not found then
    raise exception using errcode = 'P0002', message = 'expense was not found for debt rebuild';
  end if;
  if v_actual_activity_id is distinct from p_activity_id then
    raise exception using errcode = '23514', message = 'expense debt activity mismatch';
  end if;

  delete from public.expense_debts as ed
  where ed.expense_id = p_expense_id;

  if not v_is_effective then
    return;
  end if;

  with payment_totals as (
    select pay.participant_id, pg_catalog.sum(pay.base_amount) as paid
    from public.payments as pay
    where pay.expense_id = p_expense_id
    group by pay.participant_id
  ),
  split_totals as (
    select s.participant_id, pg_catalog.sum(s.base_amount) as owed
    from public.splits as s
    where s.expense_id = p_expense_id
    group by s.participant_id
  ),
  participant_nets as (
    select
      p.id as participant_id,
      p.participant_order,
      coalesce(pay.paid, 0::numeric) - coalesce(s.owed, 0::numeric) as net_amount
    from public.participants as p
    left join payment_totals as pay on pay.participant_id = p.id
    left join split_totals as s on s.participant_id = p.id
    where p.activity_id = p_activity_id
      and (pay.participant_id is not null or s.participant_id is not null)
  )
  select
    coalesce(pg_catalog.sum(net_amount), 0::numeric),
    pg_catalog.array_agg(participant_id order by participant_order, participant_id)
      filter (where net_amount > 0),
    pg_catalog.array_agg(net_amount order by participant_order, participant_id)
      filter (where net_amount > 0),
    pg_catalog.array_agg(participant_id order by participant_order, participant_id)
      filter (where net_amount < 0),
    pg_catalog.array_agg(-net_amount order by participant_order, participant_id)
      filter (where net_amount < 0)
  into
    v_net_total,
    v_creditor_ids,
    v_creditor_amounts,
    v_debtor_ids,
    v_debtor_amounts
  from participant_nets;

  if v_net_total <> 0 then
    raise exception using errcode = '23514', message = 'expense participant nets do not conserve base amount';
  end if;

  if coalesce(pg_catalog.array_length(v_creditor_ids, 1), 0) = 0
     and coalesce(pg_catalog.array_length(v_debtor_ids, 1), 0) = 0 then
    return;
  end if;
  if coalesce(pg_catalog.array_length(v_creditor_ids, 1), 0) = 0
     or coalesce(pg_catalog.array_length(v_debtor_ids, 1), 0) = 0 then
    raise exception using errcode = '23514', message = 'expense debt sides do not balance';
  end if;

  v_creditor_remaining := v_creditor_amounts[v_creditor_index];
  v_debtor_remaining := v_debtor_amounts[v_debtor_index];

  while v_creditor_index <= pg_catalog.array_length(v_creditor_ids, 1)
    and v_debtor_index <= pg_catalog.array_length(v_debtor_ids, 1)
  loop
    v_match_amount := least(v_creditor_remaining, v_debtor_remaining);

    if v_match_amount <= 0 then
      raise exception using errcode = '23514', message = 'expense debt match must be positive';
    end if;

    insert into public.expense_debts (
      activity_id,
      ledger_unit_id,
      expense_id,
      debtor_participant_id,
      creditor_participant_id,
      amount
    )
    values (
      p_activity_id,
      v_ledger_unit_id,
      p_expense_id,
      v_debtor_ids[v_debtor_index],
      v_creditor_ids[v_creditor_index],
      v_match_amount
    );

    v_creditor_remaining := v_creditor_remaining - v_match_amount;
    v_debtor_remaining := v_debtor_remaining - v_match_amount;

    if v_creditor_remaining = 0 then
      v_creditor_index := v_creditor_index + 1;
      if v_creditor_index <= pg_catalog.array_length(v_creditor_ids, 1) then
        v_creditor_remaining := v_creditor_amounts[v_creditor_index];
      end if;
    end if;

    if v_debtor_remaining = 0 then
      v_debtor_index := v_debtor_index + 1;
      if v_debtor_index <= pg_catalog.array_length(v_debtor_ids, 1) then
        v_debtor_remaining := v_debtor_amounts[v_debtor_index];
      end if;
    end if;
  end loop;

  if v_creditor_index <= pg_catalog.array_length(v_creditor_ids, 1)
     or v_debtor_index <= pg_catalog.array_length(v_debtor_ids, 1) then
    raise exception using errcode = '23514', message = 'expense debt matching did not conserve base amount';
  end if;
end;
$function$;

-- Bilateral projection performs only same-pair directional netting. Each
-- unordered pair produces at most one positive directed row; no participant
-- path or activity-wide balance optimization is performed.
create or replace function private.rebuild_bilateral_debts_locked(p_activity_id uuid)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
begin
  delete from public.bilateral_debts as bd
  where bd.activity_id = p_activity_id;

  insert into public.bilateral_debts (
    activity_id,
    debtor_participant_id,
    creditor_participant_id,
    amount
  )
  with canonical_net as (
    select
      ed.activity_id,
      least(ed.debtor_participant_id, ed.creditor_participant_id) as low_participant_id,
      greatest(ed.debtor_participant_id, ed.creditor_participant_id) as high_participant_id,
      pg_catalog.sum(
        case
          when ed.debtor_participant_id < ed.creditor_participant_id then ed.amount
          else -ed.amount
        end
      ) as signed_amount
    from public.expense_debts as ed
    where ed.activity_id = p_activity_id
    group by
      ed.activity_id,
      least(ed.debtor_participant_id, ed.creditor_participant_id),
      greatest(ed.debtor_participant_id, ed.creditor_participant_id)
  )
  select
    n.activity_id,
    case when n.signed_amount > 0 then n.low_participant_id else n.high_participant_id end,
    case when n.signed_amount > 0 then n.high_participant_id else n.low_participant_id end,
    pg_catalog.abs(n.signed_amount)::numeric(20,1)
  from canonical_net as n
  where n.signed_amount <> 0;
end;
$function$;

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
begin
  perform private.lock_debt_projection_activity(p_activity_id);
  perform private.rebuild_expense_debts_locked(p_expense_id, p_activity_id);
  perform private.rebuild_bilateral_debts_locked(p_activity_id);
end;
$function$;

-- Internal/test-only repair primitive. It takes the same Activity lock as the
-- incremental path, rebuilds every current ExpenseDebt from facts, then derives
-- the Activity's bilateral rows from those per-expense results.
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

  delete from public.expense_debts as ed
  where ed.activity_id = p_activity_id;

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
    perform private.rebuild_expense_debts_locked(v_expense_id, p_activity_id);
  end loop;

  perform private.rebuild_bilateral_debts_locked(p_activity_id);
end;
$function$;

-- Backfill any facts that predate this projection migration.
do $backfill$
declare
  v_activity_id uuid;
begin
  for v_activity_id in
    select a.id from public.activities as a order by a.id
  loop
    perform private.rebuild_activity_debt_projection(v_activity_id);
  end loop;
end;
$backfill$;

-- Keep all established Phase 2B/2C fact validation, refund protection,
-- expense row locking, and version/LWW behavior in the existing private fact
-- implementations. Projection-aware wrappers add rebuilds to the same RPC
-- transaction without changing the fact functions' identity.
create or replace function private.create_expense_projected_impl(
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
returns table(expense_id uuid, base_amount numeric(20,1), version bigint)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_expense_id uuid;
  v_base_amount numeric(20,1);
  v_version bigint;
  v_activity_id uuid;
begin
  select created.expense_id, created.base_amount, created.version
    into v_expense_id, v_base_amount, v_version
  from private.create_expense_impl(
    p_ledger_unit_id,
    p_title,
    p_original_amount,
    p_original_currency,
    p_fx_rate,
    p_split_method,
    p_payments,
    p_manual_splits,
    p_aa_participant_ids,
    p_occurred_at,
    p_note,
    p_original_expense_id
  ) as created;

  select lu.activity_id into strict v_activity_id
  from public.expenses as e
  join public.ledger_units as lu on lu.id = e.ledger_unit_id
  where e.id = v_expense_id;

  perform private.rebuild_expense_and_bilateral_debts(v_expense_id, v_activity_id);
  return query select v_expense_id, v_base_amount, v_version;
end;
$function$;

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
begin
  select updated.updated_expense_id, updated.base_amount, updated.version
    into v_updated_expense_id, v_base_amount, v_version
  from private.update_expense_impl(
    p_expense_id,
    p_ledger_unit_id,
    p_title,
    p_original_amount,
    p_original_currency,
    p_fx_rate,
    p_split_method,
    p_payments,
    p_manual_splits,
    p_aa_participant_ids,
    p_occurred_at,
    p_note,
    p_original_expense_id
  ) as updated;

  select lu.activity_id into strict v_activity_id
  from public.expenses as e
  join public.ledger_units as lu on lu.id = e.ledger_unit_id
  where e.id = v_updated_expense_id;

  perform private.rebuild_expense_and_bilateral_debts(v_updated_expense_id, v_activity_id);
  return query select v_updated_expense_id, v_base_amount, v_version;
end;
$function$;

create or replace function private.delete_expense_projected_impl(p_expense_id uuid)
returns table(deleted_expense_id uuid, deleted boolean, version bigint)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_deleted_expense_id uuid;
  v_deleted boolean;
  v_version bigint;
  v_activity_id uuid;
begin
  select deleted.deleted_expense_id, deleted.deleted, deleted.version
    into v_deleted_expense_id, v_deleted, v_version
  from private.delete_expense_impl(p_expense_id) as deleted;

  select lu.activity_id into strict v_activity_id
  from public.expenses as e
  join public.ledger_units as lu on lu.id = e.ledger_unit_id
  where e.id = v_deleted_expense_id;

  perform private.rebuild_expense_and_bilateral_debts(v_deleted_expense_id, v_activity_id);
  return query select v_deleted_expense_id, v_deleted, v_version;
end;
$function$;

create or replace function public.create_expense(
  ledger_unit_id uuid,
  title text,
  original_amount numeric(20,4),
  original_currency character(3),
  fx_rate numeric(20,10),
  split_method public.expense_split_method,
  payments jsonb default '[]'::jsonb,
  manual_splits jsonb default '[]'::jsonb,
  aa_participant_ids uuid[] default '{}'::uuid[],
  occurred_at timestamptz default pg_catalog.now(),
  note text default null,
  original_expense_id uuid default null
)
returns table(expense_id uuid, base_amount numeric(20,1), version bigint)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select created.expense_id, created.base_amount, created.version
  from private.create_expense_projected_impl(
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
  ) as created;
$function$;

create or replace function public.update_expense(
  expense_id uuid,
  ledger_unit_id uuid,
  title text,
  original_amount numeric(20,4),
  original_currency character(3),
  fx_rate numeric(20,10),
  split_method public.expense_split_method,
  payments jsonb default '[]'::jsonb,
  manual_splits jsonb default '[]'::jsonb,
  aa_participant_ids uuid[] default '{}'::uuid[],
  occurred_at timestamptz default pg_catalog.now(),
  note text default null,
  original_expense_id uuid default null
)
returns table(updated_expense_id uuid, base_amount numeric(20,1), version bigint)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select updated.updated_expense_id, updated.base_amount, updated.version
  from private.update_expense_projected_impl(
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
  ) as updated;
$function$;

create or replace function public.delete_expense(expense_id uuid)
returns table(deleted_expense_id uuid, deleted boolean, version bigint)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select deleted.deleted_expense_id, deleted.deleted, deleted.version
  from private.delete_expense_projected_impl($1) as deleted;
$function$;

revoke all on schema private from public, anon;
grant usage on schema private to authenticated, service_role;

revoke all on function private.lock_debt_projection_activity(uuid)
  from public, anon, authenticated;
revoke all on function private.rebuild_expense_debts_locked(uuid, uuid)
  from public, anon, authenticated;
revoke all on function private.rebuild_bilateral_debts_locked(uuid)
  from public, anon, authenticated;
revoke all on function private.rebuild_expense_and_bilateral_debts(uuid, uuid)
  from public, anon, authenticated;
revoke all on function private.rebuild_activity_debt_projection(uuid)
  from public, anon, authenticated;

-- Fact implementations are now reachable only from the projection-aware
-- SECURITY DEFINER wrappers, so authenticated clients cannot bypass rebuilds.
revoke all on function private.create_expense_impl(
  uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) from public, anon, authenticated;
revoke all on function private.update_expense_impl(
  uuid, uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) from public, anon, authenticated;
revoke all on function private.delete_expense_impl(uuid)
  from public, anon, authenticated;

revoke all on function private.create_expense_projected_impl(
  uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) from public, anon, authenticated;
revoke all on function private.update_expense_projected_impl(
  uuid, uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) from public, anon, authenticated;
revoke all on function private.delete_expense_projected_impl(uuid)
  from public, anon, authenticated;

grant execute on function private.create_expense_projected_impl(
  uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) to authenticated;
grant execute on function private.update_expense_projected_impl(
  uuid, uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) to authenticated;
grant execute on function private.delete_expense_projected_impl(uuid) to authenticated;
grant execute on function private.rebuild_activity_debt_projection(uuid)
  to service_role;

revoke all on function public.create_expense(
  uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) from public, anon, authenticated;
revoke all on function public.update_expense(
  uuid, uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) from public, anon, authenticated;
revoke all on function public.delete_expense(uuid) from public, anon, authenticated;

grant execute on function public.create_expense(
  uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) to authenticated;
grant execute on function public.update_expense(
  uuid, uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) to authenticated;
grant execute on function public.delete_expense(uuid) to authenticated;

commit;
