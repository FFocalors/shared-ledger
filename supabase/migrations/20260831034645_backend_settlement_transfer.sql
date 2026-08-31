begin;

-- Stabilize the existing Expense RPC object identities before replacing their
-- projection-aware implementations. In-flight calls finish before the table
-- locks below; later calls resume with the new lock-first bodies.
alter function public.create_expense(
  uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) parallel unsafe;
alter function public.update_expense(
  uuid, uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) parallel unsafe;
alter function public.delete_expense(uuid) parallel unsafe;

lock table public.expenses in share row exclusive mode;
lock table public.payments in share row exclusive mode;
lock table public.splits in share row exclusive mode;
lock table public.expense_debts in share row exclusive mode;
lock table public.bilateral_debts in share row exclusive mode;

create type public.transfer_type as enum (
  'settlement',
  'prepayment',
  'prepayment_return',
  'final_settlement'
);

alter table public.activities
  add column financial_version bigint not null default 0
    check (financial_version >= 0);

-- Phase 1 granted table-wide UPDATE. Replace it with equivalent column grants
-- for every pre-existing column so clients cannot forge financial_version.
revoke update on table public.activities from authenticated;
grant update (
  id,
  join_code,
  name,
  type,
  base_currency,
  multi_currency_enabled,
  created_by,
  created_at,
  updated_at,
  archived_at,
  is_deleted,
  deleted_at,
  deleted_by
) on public.activities to authenticated;

create table public.transfers (
  id uuid primary key default extensions.gen_random_uuid(),
  activity_id uuid not null references public.activities(id) on delete restrict,
  from_participant_id uuid not null,
  to_participant_id uuid not null,
  type public.transfer_type not null,
  amount numeric(20,1) not null check (amount > 0),
  currency character(3) not null check (currency ~ '^[A-Z]{3}$'),
  occurred_at timestamptz not null default pg_catalog.now(),
  recorded_by uuid not null references auth.users(id) on delete restrict,
  on_behalf_of_participant_id uuid,
  created_at timestamptz not null default pg_catalog.now(),
  is_voided boolean not null default false,
  voided_at timestamptz,
  voided_by uuid references auth.users(id) on delete restrict,
  void_reason text,
  constraint transfers_id_activity_id_key unique (id, activity_id),
  constraint transfers_from_activity_fk
    foreign key (activity_id, from_participant_id)
    references public.participants(activity_id, id) on delete restrict,
  constraint transfers_to_activity_fk
    foreign key (activity_id, to_participant_id)
    references public.participants(activity_id, id) on delete restrict,
  constraint transfers_on_behalf_activity_fk
    foreign key (activity_id, on_behalf_of_participant_id)
    references public.participants(activity_id, id) on delete restrict,
  constraint transfers_distinct_participants
    check (from_participant_id <> to_participant_id),
  constraint transfers_on_behalf_is_party
    check (
      on_behalf_of_participant_id is null
      or on_behalf_of_participant_id in (from_participant_id, to_participant_id)
    ),
  constraint transfers_void_lifecycle_consistency
    check (
      (
        is_voided
        and voided_at is not null
        and voided_by is not null
        and void_reason is not null
        and pg_catalog.length(pg_catalog.btrim(void_reason)) > 0
      )
      or
      (
        not is_voided
        and voided_at is null
        and voided_by is null
        and void_reason is null
      )
    )
);

alter table public.expense_debts
  add constraint expense_debts_activity_id_id_key unique (activity_id, id);

create table public.transfer_allocations (
  id uuid primary key default extensions.gen_random_uuid(),
  activity_id uuid not null references public.activities(id) on delete restrict,
  transfer_id uuid not null,
  expense_debt_id uuid not null,
  amount numeric(20,1) not null check (amount > 0),
  created_at timestamptz not null default pg_catalog.now(),
  constraint transfer_allocations_transfer_activity_fk
    foreign key (transfer_id, activity_id)
    references public.transfers(id, activity_id) on delete cascade,
  constraint transfer_allocations_expense_debt_activity_fk
    foreign key (activity_id, expense_debt_id)
    references public.expense_debts(activity_id, id) on delete cascade,
  constraint transfer_allocations_unique_projection
    unique (transfer_id, expense_debt_id)
);

create index transfers_activity_from_idx
  on public.transfers (activity_id, from_participant_id);
create index transfers_activity_to_idx
  on public.transfers (activity_id, to_participant_id);
create index transfers_activity_on_behalf_idx
  on public.transfers (activity_id, on_behalf_of_participant_id);
create index transfers_recorded_by_idx on public.transfers (recorded_by);
create index transfers_voided_by_idx
  on public.transfers (voided_by);
create index transfers_activity_effective_order_idx
  on public.transfers (activity_id, type, is_voided, occurred_at, created_at, id);

create index transfer_allocations_transfer_activity_idx
  on public.transfer_allocations (transfer_id, activity_id);
create index transfer_allocations_activity_expense_debt_idx
  on public.transfer_allocations (activity_id, expense_debt_id);

alter table public.transfers enable row level security;
alter table public.transfer_allocations enable row level security;

create policy transfers_select_member
on public.transfers
for select
to authenticated
using ((select private.is_activity_member(activity_id)));

create policy transfer_allocations_select_member
on public.transfer_allocations
for select
to authenticated
using ((select private.is_activity_member(activity_id)));

revoke all on table public.transfers, public.transfer_allocations
  from public, anon, authenticated;
grant select on table public.transfers, public.transfer_allocations
  to authenticated;
grant all on table public.transfers, public.transfer_allocations
  to service_role;

-- Caller holds the Activity advisory lock. First consume opposite-direction
-- ExpenseDebt against same-direction ExpenseDebt FIFO inside each unordered
-- pair. Effective settlement Transfers then consume only that Expense-only
-- bilateral residual queue. Historical overpayment may legitimately leave part
-- of a real Transfer unallocated.
create or replace function private.rebuild_transfer_allocations_locked(
  p_activity_id uuid
)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_transfer record;
  v_debt record;
  v_remaining numeric(20,1);
  v_allocate numeric(20,1);
begin
  delete from public.transfer_allocations as ta
  where ta.activity_id = p_activity_id;

  for v_transfer in
    select t.id, t.from_participant_id, t.to_participant_id, t.amount
    from public.transfers as t
    join public.activities as a on a.id = t.activity_id
    where t.activity_id = p_activity_id
      and t.type = 'settlement'::public.transfer_type
      and not t.is_voided
      and not a.is_deleted
    order by t.occurred_at, t.created_at, t.id
  loop
    v_remaining := v_transfer.amount;

    for v_debt in
      with directional_debts as (
        select
          ed.id,
          ed.amount,
          e.occurred_at,
          e.created_at,
          e.id as expense_id,
          coalesce(
            pg_catalog.sum(ed.amount) over (
              order by e.occurred_at, e.created_at, e.id
              rows between unbounded preceding and 1 preceding
            ),
            0::numeric
          ) as prior_direction_amount,
          coalesce((
            select pg_catalog.sum(reverse_ed.amount)
            from public.expense_debts as reverse_ed
            where reverse_ed.activity_id = p_activity_id
              and reverse_ed.debtor_participant_id = v_transfer.to_participant_id
              and reverse_ed.creditor_participant_id = v_transfer.from_participant_id
          ), 0::numeric) as reverse_total
        from public.expense_debts as ed
        join public.expenses as e on e.id = ed.expense_id
        where ed.activity_id = p_activity_id
          and ed.debtor_participant_id = v_transfer.from_participant_id
          and ed.creditor_participant_id = v_transfer.to_participant_id
      )
      select
        directional.id,
        directional.amount
          - least(
              directional.amount,
              greatest(
                directional.reverse_total - directional.prior_direction_amount,
                0::numeric
              )
            )
          - coalesce((
          select pg_catalog.sum(existing.amount)
          from public.transfer_allocations as existing
          where existing.expense_debt_id = directional.id
        ), 0::numeric) as available_amount
      from directional_debts as directional
      order by directional.occurred_at, directional.created_at, directional.expense_id
    loop
      if v_debt.available_amount > 0 then
        v_allocate := least(v_remaining, v_debt.available_amount)::numeric(20,1);

        insert into public.transfer_allocations (
          activity_id,
          transfer_id,
          expense_debt_id,
          amount
        ) values (
          p_activity_id,
          v_transfer.id,
          v_debt.id,
          v_allocate
        );

        v_remaining := v_remaining - v_allocate;
        exit when v_remaining = 0;
      end if;
    end loop;
  end loop;
end;
$function$;

-- Bilateral debt is same-pair signed ExpenseDebt net minus every effective
-- settlement Transfer. Overpayment after history edits naturally reverses the
-- pair; there is never any three-party path optimization.
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
  with signed_facts as (
    select
      ed.activity_id,
      least(ed.debtor_participant_id, ed.creditor_participant_id) as low_participant_id,
      greatest(ed.debtor_participant_id, ed.creditor_participant_id) as high_participant_id,
      case
        when ed.debtor_participant_id < ed.creditor_participant_id then ed.amount
        else -ed.amount
      end as signed_amount
    from public.expense_debts as ed
    where ed.activity_id = p_activity_id

    union all

    select
      t.activity_id,
      least(t.from_participant_id, t.to_participant_id),
      greatest(t.from_participant_id, t.to_participant_id),
      case
        when t.from_participant_id < t.to_participant_id then -t.amount
        else t.amount
      end
    from public.transfers as t
    join public.activities as a on a.id = t.activity_id
    where t.activity_id = p_activity_id
      and t.type = 'settlement'::public.transfer_type
      and not t.is_voided
      and not a.is_deleted
  ),
  canonical_net as (
    select
      sf.activity_id,
      sf.low_participant_id,
      sf.high_participant_id,
      pg_catalog.sum(sf.signed_amount) as signed_amount
    from signed_facts as sf
    group by sf.activity_id, sf.low_participant_id, sf.high_participant_id
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

-- Incremental Expense projection work shares the same Activity lock as
-- Transfers, rejects archived Activities after acquiring it, rebuilds all
-- allocation explanations, and advances the financial concurrency token.
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
begin
  perform private.lock_debt_projection_activity(p_activity_id);

  select a.archived_at into v_archived_at
  from public.activities as a
  where a.id = p_activity_id and not a.is_deleted
  for update of a;
  if not found then
    raise exception using errcode = 'P0002', message = 'activity was not found for financial write';
  end if;
  if v_archived_at is not null then
    raise exception using errcode = '55000', message = 'archived activity is read-only';
  end if;

  perform private.rebuild_expense_debts_locked(p_expense_id, p_activity_id);
  perform private.rebuild_transfer_allocations_locked(p_activity_id);
  perform private.rebuild_bilateral_debts_locked(p_activity_id);

  update public.activities as a
  set financial_version = a.financial_version + 1
  where a.id = p_activity_id;
end;
$function$;

-- Repair primitive: reconstruct every projection from immutable/current facts
-- under the shared lock. Repairs intentionally do not change financial_version.
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

  delete from public.transfer_allocations as ta
  where ta.activity_id = p_activity_id;
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

  perform private.rebuild_transfer_allocations_locked(p_activity_id);
  perform private.rebuild_bilateral_debts_locked(p_activity_id);
end;
$function$;

-- Lock-first wrappers keep Expense facts and all affected financial projections
-- in one Activity-serialized transaction.
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
  v_archived_at timestamptz;
begin
  select lu.activity_id into v_activity_id
  from public.ledger_units as lu
  where lu.id = p_ledger_unit_id;
  if not found then
    raise exception using errcode = 'P0002', message = 'ledger unit was not found';
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

  select created.expense_id, created.base_amount, created.version
    into v_expense_id, v_base_amount, v_version
  from private.create_expense_impl(
    p_ledger_unit_id, p_title, p_original_amount, p_original_currency, p_fx_rate,
    p_split_method, p_payments, p_manual_splits, p_aa_participant_ids,
    p_occurred_at, p_note, p_original_expense_id
  ) as created;

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
  v_archived_at timestamptz;
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
  v_archived_at timestamptz;
begin
  select lu.activity_id into v_activity_id
  from public.expenses as e
  join public.ledger_units as lu on lu.id = e.ledger_unit_id
  where e.id = p_expense_id;
  if not found then
    raise exception using errcode = 'P0002', message = 'expense was not found';
  end if;

  perform private.lock_debt_projection_activity(v_activity_id);

  -- Enforce archived read-only even when delete_expense would otherwise be an
  -- idempotent no-op, without incrementing the version on a non-archived no-op.
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

  select removed.deleted_expense_id, removed.deleted, removed.version
    into v_deleted_expense_id, v_deleted, v_version
  from private.delete_expense_impl(p_expense_id) as removed;

  if v_deleted then
    perform private.rebuild_expense_and_bilateral_debts(v_deleted_expense_id, v_activity_id);
  end if;
  return query select v_deleted_expense_id, v_deleted, v_version;
end;
$function$;

create or replace function private.create_settlement_transfer_impl(
  p_activity_id uuid,
  p_from_participant_id uuid,
  p_to_participant_id uuid,
  p_amount numeric(20,1),
  p_occurred_at timestamptz,
  p_on_behalf_of_participant_id uuid
)
returns table(
  transfer_id uuid,
  amount numeric(20,1),
  currency character(3),
  financial_version bigint
)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_user_id uuid;
  v_is_creator boolean;
  v_claimed_participant_id uuid;
  v_base_currency character(3);
  v_archived_at timestamptz;
  v_current_debt numeric(20,1);
  v_transfer_id uuid;
  v_financial_version bigint;
  v_participant_count integer;
begin
  v_user_id := (select auth.uid());
  if v_user_id is null then
    raise exception using errcode = '28000', message = 'authentication is required';
  end if;
  if p_amount is null or p_amount <= 0 then
    raise exception using errcode = '22023', message = 'transfer amount must be positive';
  end if;
  if p_from_participant_id is null or p_to_participant_id is null
     or p_from_participant_id = p_to_participant_id then
    raise exception using errcode = '22023', message = 'transfer parties must be distinct';
  end if;
  if p_occurred_at is null then
    raise exception using errcode = '22004', message = 'transfer occurred_at is required';
  end if;

  perform private.lock_debt_projection_activity(p_activity_id);

  select a.base_currency, a.archived_at, a.created_by = v_user_id
    into v_base_currency, v_archived_at, v_is_creator
  from public.activities as a
  where a.id = p_activity_id and not a.is_deleted
  for update of a;
  if not found then
    raise exception using errcode = 'P0002', message = 'activity was not found';
  end if;
  if v_archived_at is not null then
    raise exception using errcode = '55000', message = 'archived activity is read-only';
  end if;
  if not exists (
    select 1 from public.activity_members as am
    where am.activity_id = p_activity_id and am.user_id = v_user_id
  ) then
    raise exception using errcode = '42501', message = 'caller is not an activity member';
  end if;
  -- UUID order is the global participant row-lock order. Besides protecting
  -- active status, these locks serialize concurrent claim INSERTs through the
  -- claim FK before identity authorization is read below.
  perform 1
  from public.participants as p
  where p.activity_id = p_activity_id
    and p.id in (p_from_participant_id, p_to_participant_id)
  order by p.id
  for update of p;
  get diagnostics v_participant_count = row_count;

  if v_participant_count <> 2 or exists (
    select 1 from public.participants as p
    where p.activity_id = p_activity_id
      and p.id in (p_from_participant_id, p_to_participant_id)
      and p.is_deleted
  ) then
    raise exception using errcode = 'P0002', message = 'transfer participant was not found';
  end if;

  select pc.participant_id into v_claimed_participant_id
  from public.participant_claims as pc
  where pc.activity_id = p_activity_id and pc.user_id = v_user_id;

  if v_is_creator then
    if p_on_behalf_of_participant_id is not null then
      if p_on_behalf_of_participant_id not in (p_from_participant_id, p_to_participant_id) then
        raise exception using errcode = '22023', message = 'on-behalf participant must be a transfer party';
      end if;
      if exists (
        select 1 from public.participant_claims as pc
        where pc.participant_id = p_on_behalf_of_participant_id
      ) then
        raise exception using errcode = '42501', message = 'creator may act only for an unclaimed participant';
      end if;
    elsif v_claimed_participant_id is null
       or v_claimed_participant_id not in (p_from_participant_id, p_to_participant_id) then
      raise exception using errcode = '42501', message = 'creator must be a transfer party or explicitly act on behalf';
    end if;
  else
    if p_on_behalf_of_participant_id is not null then
      raise exception using errcode = '42501', message = 'only the activity creator may act on behalf';
    end if;
    if v_claimed_participant_id is null
       or v_claimed_participant_id not in (p_from_participant_id, p_to_participant_id) then
      raise exception using errcode = '42501', message = 'caller claimed participant must be a transfer party';
    end if;
  end if;

  select bd.amount into v_current_debt
  from public.bilateral_debts as bd
  where bd.activity_id = p_activity_id
    and bd.debtor_participant_id = p_from_participant_id
    and bd.creditor_participant_id = p_to_participant_id;

  if v_current_debt is null or p_amount > v_current_debt then
    raise exception using errcode = '23514', message = 'settlement exceeds current bilateral debt';
  end if;

  insert into public.transfers (
    activity_id,
    from_participant_id,
    to_participant_id,
    type,
    amount,
    currency,
    occurred_at,
    recorded_by,
    on_behalf_of_participant_id
  ) values (
    p_activity_id,
    p_from_participant_id,
    p_to_participant_id,
    'settlement'::public.transfer_type,
    p_amount,
    v_base_currency,
    p_occurred_at,
    v_user_id,
    p_on_behalf_of_participant_id
  ) returning id into v_transfer_id;

  perform private.rebuild_transfer_allocations_locked(p_activity_id);
  perform private.rebuild_bilateral_debts_locked(p_activity_id);

  update public.activities as a
  set financial_version = a.financial_version + 1
  where a.id = p_activity_id
  returning a.financial_version into v_financial_version;

  return query select v_transfer_id, p_amount, v_base_currency, v_financial_version;
end;
$function$;

create or replace function private.void_settlement_transfer_impl(
  p_transfer_id uuid,
  p_void_reason text
)
returns table(
  transfer_id uuid,
  voided boolean,
  financial_version bigint
)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_user_id uuid;
  v_activity_id uuid;
  v_recorded_by uuid;
  v_is_voided boolean;
  v_is_creator boolean;
  v_archived_at timestamptz;
  v_financial_version bigint;
begin
  v_user_id := (select auth.uid());
  if v_user_id is null then
    raise exception using errcode = '28000', message = 'authentication is required';
  end if;
  if p_void_reason is null or pg_catalog.length(pg_catalog.btrim(p_void_reason)) = 0 then
    raise exception using errcode = '22023', message = 'void reason is required';
  end if;

  select t.activity_id into v_activity_id
  from public.transfers as t
  where t.id = p_transfer_id;
  if not found then
    raise exception using errcode = 'P0002', message = 'transfer was not found';
  end if;

  perform private.lock_debt_projection_activity(v_activity_id);

  select
    t.recorded_by,
    t.is_voided,
    a.created_by = v_user_id,
    a.archived_at
  into v_recorded_by, v_is_voided, v_is_creator, v_archived_at
  from public.transfers as t
  join public.activities as a on a.id = t.activity_id
  join public.participants as from_p
    on from_p.activity_id = t.activity_id and from_p.id = t.from_participant_id
  join public.participants as to_p
    on to_p.activity_id = t.activity_id and to_p.id = t.to_participant_id
  where t.id = p_transfer_id
    and t.type = 'settlement'::public.transfer_type
    and not a.is_deleted
    and not from_p.is_deleted
    and not to_p.is_deleted
  for update of a, t;
  if not found then
    raise exception using errcode = 'P0002', message = 'settlement transfer was not found';
  end if;
  if v_archived_at is not null then
    raise exception using errcode = '55000', message = 'archived activity is read-only';
  end if;
  if not exists (
    select 1 from public.activity_members as am
    where am.activity_id = v_activity_id and am.user_id = v_user_id
  ) then
    raise exception using errcode = '42501', message = 'caller is not an activity member';
  end if;
  if v_is_voided then
    raise exception using errcode = '55000', message = 'transfer is already voided';
  end if;
  if not v_is_creator and v_recorded_by <> v_user_id then
    raise exception using errcode = '42501', message = 'member may void only a transfer they recorded';
  end if;

  update public.transfers as t
  set is_voided = true,
      voided_at = pg_catalog.now(),
      voided_by = v_user_id,
      void_reason = pg_catalog.btrim(p_void_reason)
  where t.id = p_transfer_id;

  perform private.rebuild_transfer_allocations_locked(v_activity_id);
  perform private.rebuild_bilateral_debts_locked(v_activity_id);

  update public.activities as a
  set financial_version = a.financial_version + 1
  where a.id = v_activity_id
  returning a.financial_version into v_financial_version;

  return query select p_transfer_id, true, v_financial_version;
end;
$function$;

create or replace function public.create_settlement_transfer(
  activity_id uuid,
  from_participant_id uuid,
  to_participant_id uuid,
  amount numeric(20,1),
  occurred_at timestamptz default pg_catalog.now(),
  on_behalf_of_participant_id uuid default null
)
returns table(
  transfer_id uuid,
  amount numeric(20,1),
  currency character(3),
  financial_version bigint
)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select created.transfer_id, created.amount, created.currency, created.financial_version
  from private.create_settlement_transfer_impl($1, $2, $3, $4, $5, $6) as created;
$function$;

create or replace function public.void_settlement_transfer(
  transfer_id uuid,
  void_reason text
)
returns table(
  transfer_id uuid,
  voided boolean,
  financial_version bigint
)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select voided_transfer.transfer_id,
         voided_transfer.voided,
         voided_transfer.financial_version
  from private.void_settlement_transfer_impl($1, $2) as voided_transfer;
$function$;

revoke all on function private.rebuild_transfer_allocations_locked(uuid)
  from public, anon, authenticated;
revoke all on function private.rebuild_bilateral_debts_locked(uuid)
  from public, anon, authenticated;
revoke all on function private.rebuild_expense_and_bilateral_debts(uuid, uuid)
  from public, anon, authenticated;
revoke all on function private.rebuild_activity_debt_projection(uuid)
  from public, anon, authenticated;
revoke all on function private.create_settlement_transfer_impl(
  uuid, uuid, uuid, numeric(20,1), timestamptz, uuid
) from public, anon, authenticated;
revoke all on function private.void_settlement_transfer_impl(uuid, text)
  from public, anon, authenticated;

-- Existing private Expense wrappers remain reachable only through their public
-- SECURITY INVOKER endpoints. New Transfer implementations follow that pattern.
grant execute on function private.create_settlement_transfer_impl(
  uuid, uuid, uuid, numeric(20,1), timestamptz, uuid
) to authenticated;
grant execute on function private.void_settlement_transfer_impl(uuid, text)
  to authenticated;
grant execute on function private.rebuild_activity_debt_projection(uuid)
  to service_role;

revoke all on function public.create_settlement_transfer(
  uuid, uuid, uuid, numeric(20,1), timestamptz, uuid
) from public, anon, authenticated;
revoke all on function public.void_settlement_transfer(uuid, text)
  from public, anon, authenticated;
grant execute on function public.create_settlement_transfer(
  uuid, uuid, uuid, numeric(20,1), timestamptz, uuid
) to authenticated;
grant execute on function public.void_settlement_transfer(uuid, text)
  to authenticated;

commit;
