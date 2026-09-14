begin;

-- Server-owned provenance for every new Expense FX snapshot.  Existing rows
-- are deliberately classified instead of being re-valued.
alter table public.expenses
  add column fx_rate_source text not null default 'legacy_manual',
  add column fx_rate_observed_at timestamptz;

alter table public.expenses
  add constraint expenses_fx_rate_source_check
  check (fx_rate_source in ('ECB_REFERENCE', 'same_currency', 'legacy_manual'));

update public.expenses as e
set fx_rate_source = case
  when e.original_currency = a.base_currency then 'same_currency'
  else 'legacy_manual'
end,
    fx_rate_observed_at = null
from public.ledger_units as lu
join public.activities as a on a.id = lu.activity_id
where lu.id = e.ledger_unit_id;

-- The cache stores the complete decimal cross-product.  For an ECB source
-- rate r(X) = X per EUR, the stored quote-to-base rate is r(base)/r(quote).
alter table public.exchange_rate_cache
  alter column source set default 'ECB_REFERENCE';
update public.exchange_rate_cache
set source = 'ECB_REFERENCE'
where source is null;
alter table public.exchange_rate_cache
  alter column source set not null;
-- Keep non-ECB fixture/provider rows readable for the established compatibility
-- contract.  The synchronizer always writes ECB_REFERENCE and auto Expense
-- resolution deliberately accepts only that source.
create index exchange_rate_cache_observed_idx
  on public.exchange_rate_cache (observed_at desc, base_currency, quote_currency);

create table public.exchange_rate_supported_currencies (
  currency_code character(3) primary key
    check (currency_code ~ '^[A-Z]{3}$'),
  display_name text not null default '',
  source text not null default 'ECB_REFERENCE'
    check (source = 'ECB_REFERENCE'),
  observed_at timestamptz not null,
  updated_at timestamptz not null default pg_catalog.now(),
  enabled boolean not null default true
);
alter table public.exchange_rate_supported_currencies enable row level security;
create policy exchange_rate_supported_currencies_select_authenticated
  on public.exchange_rate_supported_currencies
  for select to authenticated using (true);
revoke all on public.exchange_rate_supported_currencies from public, anon, authenticated;
grant select on public.exchange_rate_supported_currencies to authenticated;
grant all on public.exchange_rate_supported_currencies to service_role;

create table public.exchange_rate_sync_state (
  singleton boolean primary key default true check (singleton),
  last_attempted_at timestamptz,
  last_succeeded_at timestamptz,
  last_ecb_observed_at timestamptz,
  next_attempt_at timestamptz,
  last_error_code text check (last_error_code is null or last_error_code ~ '^[a-z0-9_]{1,64}$'),
  updated_at timestamptz not null default pg_catalog.now()
);
insert into public.exchange_rate_sync_state (singleton)
values (true)
on conflict (singleton) do nothing;
alter table public.exchange_rate_sync_state enable row level security;
create policy exchange_rate_sync_state_select_authenticated
  on public.exchange_rate_sync_state
  for select to authenticated using (true);
revoke all on public.exchange_rate_sync_state from public, anon, authenticated;
grant select on public.exchange_rate_sync_state to authenticated;
grant all on public.exchange_rate_sync_state to service_role;

-- Only the server-side Edge Function may claim or commit a refresh.  A claim
-- is durable before the network request, so concurrent invocations merge into
-- one attempt and a crash cannot cause an unbounded retry loop.
create or replace function public.claim_exchange_rate_sync(
  p_min_interval_seconds integer default 7200
)
returns table(claimed boolean, next_attempt_at timestamptz)
language plpgsql
volatile
security invoker
set search_path = ''
as $function$
declare
  v_now timestamptz := pg_catalog.now();
  v_next timestamptz;
begin
  if current_user <> 'service_role' then
    raise exception using errcode = '42501', message = 'server sync access required';
  end if;
  if p_min_interval_seconds is null or p_min_interval_seconds < 60 then
    raise exception using errcode = '22023', message = 'minimum sync interval is invalid';
  end if;

  select s.next_attempt_at
    into v_next
  from public.exchange_rate_sync_state as s
  where s.singleton
  for update;

  if v_next is not null and v_next > v_now then
    return query select false, v_next;
    return;
  end if;

  v_next := v_now + pg_catalog.make_interval(secs => p_min_interval_seconds);
  update public.exchange_rate_sync_state as s
  set last_attempted_at = v_now,
      next_attempt_at = v_next,
      last_error_code = null,
      updated_at = v_now
  where s.singleton;
  return query select true, v_next;
end;
$function$;

-- This is intentionally a small, enumerated error vocabulary.  The Edge
-- Function never stores upstream response bodies, URLs containing credentials,
-- or database exception text.
create or replace function public.record_exchange_rate_sync_failure(
  p_error_code text
)
returns boolean
language plpgsql
volatile
security invoker
set search_path = ''
as $function$
begin
  if current_user <> 'service_role' then
    raise exception using errcode = '42501', message = 'server sync access required';
  end if;
  if p_error_code is null or p_error_code !~ '^[a-z0-9_]{1,64}$' then
    raise exception using errcode = '22023', message = 'sync error code is invalid';
  end if;
  update public.exchange_rate_sync_state as s
  set last_error_code = p_error_code,
      updated_at = pg_catalog.now()
  where s.singleton;
  return true;
end;
$function$;

-- Validate the whole payload before the first write, then upsert all pairs and
-- supported currencies in one database transaction.  Any malformed or partial
-- payload raises and therefore leaves the prior cache untouched.
create or replace function public.replace_exchange_rate_cache(
  p_ecb_date date,
  p_rates jsonb
)
returns table(currency_count integer, pair_count integer, observed_at timestamptz)
language plpgsql
volatile
security invoker
set search_path = ''
as $function$
declare
  v_now timestamptz := pg_catalog.now();
  v_observed_at timestamptz;
  v_count integer;
  v_pairs integer := 0;
  v_item record;
  v_quote record;
  v_rate numeric(20,10);
  v_quote_rate numeric(20,10);
begin
  if current_user <> 'service_role' then
    raise exception using errcode = '42501', message = 'server sync access required';
  end if;
  if p_ecb_date is null or p_ecb_date > (v_now at time zone 'UTC')::date then
    raise exception using errcode = '22023', message = 'ECB date is invalid';
  end if;
  if p_rates is null or pg_catalog.jsonb_typeof(p_rates) <> 'object' then
    raise exception using errcode = '22023', message = 'ECB payload must be an object';
  end if;
  if p_rates ->> 'EUR' is null or (p_rates ->> 'EUR')::numeric <> 1 then
    raise exception using errcode = '22023', message = 'ECB payload must contain EUR=1';
  end if;

  select count(*) into v_count from pg_catalog.jsonb_each_text(p_rates);
  if v_count < 5 or v_count > 100 then
    raise exception using errcode = '22023', message = 'ECB payload is incomplete';
  end if;
  for v_item in select key, value from pg_catalog.jsonb_each_text(p_rates)
  loop
    if v_item.key !~ '^[A-Z]{3}$' then
      raise exception using errcode = '22023', message = 'ECB currency code is invalid';
    end if;
    v_rate := v_item.value::numeric(20,10);
    if v_rate <= 0 then
      raise exception using errcode = '22023', message = 'ECB rate must be positive';
    end if;
  end loop;

  v_observed_at := (p_ecb_date::timestamp at time zone 'UTC');
  update public.exchange_rate_supported_currencies
  set enabled = false, updated_at = v_now;
  for v_item in select key, value from pg_catalog.jsonb_each_text(p_rates)
  loop
    v_rate := v_item.value::numeric(20,10);
    insert into public.exchange_rate_supported_currencies
      (currency_code, display_name, observed_at, updated_at, enabled)
    values (v_item.key, '', v_observed_at, v_now, true)
    on conflict (currency_code) do update
      set observed_at = excluded.observed_at,
          updated_at = excluded.updated_at,
          enabled = true;

    for v_quote in select key, value from pg_catalog.jsonb_each_text(p_rates)
    loop
      if v_item.key <> v_quote.key then
        v_quote_rate := v_quote.value::numeric(20,10);
        insert into public.exchange_rate_cache
          (base_currency, quote_currency, rate, observed_at, source, updated_at)
        values (
          v_item.key,
          v_quote.key,
          pg_catalog.round(v_rate / v_quote_rate, 10),
          v_observed_at,
          'ECB_REFERENCE',
          v_now
        )
        on conflict (base_currency, quote_currency) do update
          set rate = excluded.rate,
              observed_at = excluded.observed_at,
              source = excluded.source,
              updated_at = excluded.updated_at;
        v_pairs := v_pairs + 1;
      end if;
    end loop;
  end loop;

  update public.exchange_rate_sync_state as s
  set last_succeeded_at = v_now,
      last_ecb_observed_at = v_observed_at,
      last_error_code = null,
      updated_at = v_now
  where s.singleton;
  return query select v_count, v_pairs, v_observed_at;
end;
$function$;

create or replace function public.get_exchange_rate_sync_status()
returns table(
  last_attempted_at timestamptz,
  last_succeeded_at timestamptz,
  last_ecb_observed_at timestamptz,
  next_attempt_at timestamptz,
  last_error_code text
)
language sql
stable
security invoker
set search_path = ''
as $function$
  select s.last_attempted_at, s.last_succeeded_at, s.last_ecb_observed_at,
         s.next_attempt_at, s.last_error_code
  from public.exchange_rate_sync_state as s
  where s.singleton;
$function$;

create or replace function public.list_supported_exchange_currencies()
returns table(currency_code character(3), display_name text, observed_at timestamptz)
language sql
stable
security invoker
set search_path = ''
as $function$
  select c.currency_code, c.display_name, c.observed_at
  from public.exchange_rate_supported_currencies as c
  where c.enabled
  order by c.currency_code;
$function$;

-- Preserve the established read function identity while making same-currency
-- and ECB snapshot metadata explicit to Android callers.
create or replace function public.get_exchange_rate(
  p_base_currency character(3),
  p_quote_currency character(3)
)
returns table(base_currency character(3), quote_currency character(3), rate numeric(20,10), observed_at timestamptz, source text)
language plpgsql
stable
security invoker
set search_path = ''
as $function$
declare
  v_base character(3) := pg_catalog.upper(pg_catalog.btrim(p_base_currency));
  v_quote character(3) := pg_catalog.upper(pg_catalog.btrim(p_quote_currency));
begin
  if v_base is null or v_quote is null or v_base !~ '^[A-Z]{3}$' or v_quote !~ '^[A-Z]{3}$' then
    raise exception using errcode = '22023', message = 'currency must be three uppercase letters';
  end if;
  if v_base = v_quote then
    return query select v_base, v_quote, 1::numeric(20,10), null::timestamptz, 'same_currency'::text;
    return;
  end if;
  return query
  select c.base_currency, c.quote_currency, c.rate, c.observed_at, c.source
  from public.exchange_rate_cache as c
  where c.base_currency = v_base and c.quote_currency = v_quote;
end;
$function$;

create or replace function private.resolve_expense_fx_snapshot(
  p_ledger_unit_id uuid,
  p_original_currency character(3),
  p_original_expense_id uuid default null,
  p_existing_expense_id uuid default null
)
returns table(fx_rate numeric(20,10), fx_rate_source text, fx_rate_observed_at timestamptz)
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_activity_id uuid;
  v_base_currency character(3);
  v_multi_currency_enabled boolean;
  v_currency character(3) := pg_catalog.upper(pg_catalog.btrim(p_original_currency));
  v_existing_currency character(3);
  v_rate numeric(20,10);
  v_source text;
  v_observed_at timestamptz;
begin
  select lu.activity_id, a.base_currency, a.multi_currency_enabled
    into v_activity_id, v_base_currency, v_multi_currency_enabled
  from public.ledger_units as lu
  join public.activities as a on a.id = lu.activity_id
  where lu.id = p_ledger_unit_id and not lu.is_deleted and not a.is_deleted;
  if not found then
    raise exception using errcode = '42501', message = 'ledger unit is not available';
  end if;
  if not exists (
    select 1 from public.activity_members as am
    where am.activity_id = v_activity_id and am.user_id = (select auth.uid())
  ) then
    raise exception using errcode = '42501', message = 'caller is not an activity member';
  end if;
  if v_currency is null or v_currency !~ '^[A-Z]{3}$' then
    raise exception using errcode = '22023', message = 'original currency must be three uppercase letters';
  end if;

  -- A linked refund inherits the complete immutable snapshot of its original.
  if p_original_expense_id is not null then
    select e.original_currency, e.fx_rate, e.fx_rate_source, e.fx_rate_observed_at
      into v_existing_currency, v_rate, v_source, v_observed_at
    from public.expenses as e
    join public.ledger_units as lu on lu.id = e.ledger_unit_id
    join public.activities as a on a.id = lu.activity_id
    where e.id = p_original_expense_id
      and lu.activity_id = v_activity_id
      and not e.is_deleted and not lu.is_deleted and not a.is_deleted
    for share;
    if not found then
      raise exception using errcode = '22023', message = 'refund reference is not an active expense in this activity';
    end if;
    if v_existing_currency <> v_currency then
      raise exception using errcode = '22023', message = 'linked refund currency must match original expense';
    end if;
    return query select v_rate, v_source, v_observed_at;
    return;
  end if;

  -- Editing without changing currency keeps the original snapshot, including
  -- a legacy manual snapshot and an already observed ECB date.
  if p_existing_expense_id is not null then
    select e.original_currency, e.fx_rate, e.fx_rate_source, e.fx_rate_observed_at
      into v_existing_currency, v_rate, v_source, v_observed_at
    from public.expenses as e
    where e.id = p_existing_expense_id and not e.is_deleted
    for share;
    if not found then
      raise exception using errcode = '22023', message = 'expense is not active';
    end if;
    if v_existing_currency = v_currency then
      return query select v_rate, v_source, v_observed_at;
      return;
    end if;
  end if;

  if v_currency = v_base_currency then
    return query select 1::numeric(20,10), 'same_currency'::text, null::timestamptz;
    return;
  end if;
  if not v_multi_currency_enabled then
    raise exception using errcode = '22023', message = 'foreign currency is disabled for this activity';
  end if;
  select c.rate, c.source, c.observed_at
    into v_rate, v_source, v_observed_at
  from public.exchange_rate_cache as c
  where c.base_currency = v_base_currency and c.quote_currency = v_currency
    and c.source = 'ECB_REFERENCE';
  if not found then
    raise exception using errcode = '22023', message = 'no exchange rate cache available';
  end if;
  -- An old successful cache is still a usable server snapshot.  The observed
  -- date is returned so Android can warn and offer a refresh; only a missing
  -- cache blocks an external-currency write.
  return query select v_rate, v_source, v_observed_at;
end;
$function$;

create or replace function private.create_expense_auto_rate_impl(
  p_ledger_unit_id uuid,
  p_title text,
  p_original_amount numeric(20,4),
  p_original_currency character(3),
  p_split_method public.expense_split_method,
  p_payments jsonb,
  p_manual_splits jsonb,
  p_aa_participant_ids uuid[],
  p_occurred_at timestamptz,
  p_note text,
  p_original_expense_id uuid
)
returns table(expense_id uuid, base_amount numeric(20,1), version bigint, fx_rate numeric(20,10), fx_rate_source text, fx_rate_observed_at timestamptz)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_rate numeric(20,10);
  v_source text;
  v_observed_at timestamptz;
  v_expense_id uuid;
  v_base_amount numeric(20,1);
  v_version bigint;
  v_activity_id uuid;
begin
  select lu.activity_id into v_activity_id
  from public.ledger_units as lu
  join public.activities as a on a.id = lu.activity_id
  where lu.id = p_ledger_unit_id and not lu.is_deleted and not a.is_deleted;
  if not found then
    raise exception using errcode = '42501', message = 'ledger unit is not available';
  end if;
  select s.fx_rate, s.fx_rate_source, s.fx_rate_observed_at
    into v_rate, v_source, v_observed_at
  from private.resolve_expense_fx_snapshot(
    p_ledger_unit_id, p_original_currency, p_original_expense_id, null
  ) as s;
  select x.expense_id, x.base_amount, x.version
    into v_expense_id, v_base_amount, v_version
  from private.create_expense_projected_impl(
    p_ledger_unit_id, p_title, p_original_amount, p_original_currency, v_rate,
    p_split_method, p_payments, p_manual_splits, p_aa_participant_ids,
    p_occurred_at, p_note, p_original_expense_id
  ) as x;
  update public.expenses as e
  set fx_rate_source = v_source, fx_rate_observed_at = v_observed_at
  where e.id = v_expense_id;
  return query select v_expense_id, v_base_amount, v_version, v_rate, v_source, v_observed_at;
end;
$function$;

create or replace function private.update_expense_auto_rate_impl(
  p_expense_id uuid,
  p_ledger_unit_id uuid,
  p_title text,
  p_original_amount numeric(20,4),
  p_original_currency character(3),
  p_split_method public.expense_split_method,
  p_payments jsonb,
  p_manual_splits jsonb,
  p_aa_participant_ids uuid[],
  p_occurred_at timestamptz,
  p_note text,
  p_original_expense_id uuid
)
returns table(updated_expense_id uuid, base_amount numeric(20,1), version bigint, fx_rate numeric(20,10), fx_rate_source text, fx_rate_observed_at timestamptz)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_rate numeric(20,10);
  v_source text;
  v_observed_at timestamptz;
  v_updated_expense_id uuid;
  v_base_amount numeric(20,1);
  v_version bigint;
  v_activity_id uuid;
begin
  select lu.activity_id into v_activity_id
  from public.expenses as e
  join public.ledger_units as lu on lu.id = e.ledger_unit_id
  where e.id = p_expense_id;
  if not found then
    raise exception using errcode = 'P0002', message = 'expense was not found';
  end if;
  select s.fx_rate, s.fx_rate_source, s.fx_rate_observed_at
    into v_rate, v_source, v_observed_at
  from private.resolve_expense_fx_snapshot(
    p_ledger_unit_id, p_original_currency, p_original_expense_id, p_expense_id
  ) as s;
  select x.updated_expense_id, x.base_amount, x.version
    into v_updated_expense_id, v_base_amount, v_version
  from private.update_expense_projected_impl(
    p_expense_id, p_ledger_unit_id, p_title, p_original_amount,
    p_original_currency, v_rate, p_split_method, p_payments,
    p_manual_splits, p_aa_participant_ids, p_occurred_at, p_note,
    p_original_expense_id
  ) as x;
  update public.expenses as e
  set fx_rate_source = v_source, fx_rate_observed_at = v_observed_at
  where e.id = v_updated_expense_id;
  return query select v_updated_expense_id, v_base_amount, v_version, v_rate, v_source, v_observed_at;
end;
$function$;

create or replace function public.create_expense_auto_rate(
  ledger_unit_id uuid,
  title text,
  original_amount numeric(20,4),
  original_currency character(3),
  split_method public.expense_split_method,
  payments jsonb default '[]'::jsonb,
  manual_splits jsonb default '[]'::jsonb,
  aa_participant_ids uuid[] default '{}'::uuid[],
  occurred_at timestamptz default pg_catalog.now(),
  note text default null,
  original_expense_id uuid default null
)
returns table(expense_id uuid, base_amount numeric(20,1), version bigint, fx_rate numeric(20,10), fx_rate_source text, fx_rate_observed_at timestamptz)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select * from private.create_expense_auto_rate_impl(
    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11
  );
$function$;

create or replace function public.update_expense_auto_rate(
  expense_id uuid,
  ledger_unit_id uuid,
  title text,
  original_amount numeric(20,4),
  original_currency character(3),
  split_method public.expense_split_method,
  payments jsonb default '[]'::jsonb,
  manual_splits jsonb default '[]'::jsonb,
  aa_participant_ids uuid[] default '{}'::uuid[],
  occurred_at timestamptz default pg_catalog.now(),
  note text default null,
  original_expense_id uuid default null
)
returns table(updated_expense_id uuid, base_amount numeric(20,1), version bigint, fx_rate numeric(20,10), fx_rate_source text, fx_rate_observed_at timestamptz)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select * from private.update_expense_auto_rate_impl(
    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12
  );
$function$;

revoke all on function public.claim_exchange_rate_sync(integer), public.record_exchange_rate_sync_failure(text), public.replace_exchange_rate_cache(date,jsonb) from public, anon, authenticated;
grant execute on function public.claim_exchange_rate_sync(integer), public.record_exchange_rate_sync_failure(text), public.replace_exchange_rate_cache(date,jsonb) to service_role;
revoke all on function public.get_exchange_rate_sync_status(), public.list_supported_exchange_currencies(), public.get_exchange_rate(character(3),character(3)) from public, anon;
grant execute on function public.get_exchange_rate_sync_status(), public.list_supported_exchange_currencies(), public.get_exchange_rate(character(3),character(3)) to authenticated;
revoke all on function public.create_expense_auto_rate(uuid,text,numeric(20,4),character(3),public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid), public.update_expense_auto_rate(uuid,uuid,text,numeric(20,4),character(3),public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid) from public, anon;
grant execute on function public.create_expense_auto_rate(uuid,text,numeric(20,4),character(3),public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid), public.update_expense_auto_rate(uuid,uuid,text,numeric(20,4),character(3),public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid) to authenticated;
revoke all on function private.resolve_expense_fx_snapshot(uuid,character(3),uuid,uuid), private.create_expense_auto_rate_impl(uuid,text,numeric(20,4),character(3),public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid), private.update_expense_auto_rate_impl(uuid,uuid,text,numeric(20,4),character(3),public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid) from public, anon, authenticated;
-- Match the established project convention: public SECURITY INVOKER RPCs
-- may call their private SECURITY DEFINER implementation as authenticated;
-- the helper still performs its own Activity-membership check.
grant execute on function private.resolve_expense_fx_snapshot(uuid,character(3),uuid,uuid), private.create_expense_auto_rate_impl(uuid,text,numeric(20,4),character(3),public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid), private.update_expense_auto_rate_impl(uuid,uuid,text,numeric(20,4),character(3),public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid) to authenticated, service_role;

commit;
