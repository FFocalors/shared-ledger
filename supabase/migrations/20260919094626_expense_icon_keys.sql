begin;

alter table public.expenses
  add column icon_key text not null default 'money';

alter table public.expenses
  add constraint expenses_icon_key_supported
  check (icon_key in (
    'money',
    'dining',
    'shopping',
    'transport',
    'hotel',
    'ticket',
    'fuel',
    'entertainment',
    'medical',
    'gift',
    'grocery',
    'flight'
  ));

comment on column public.expenses.icon_key is
  'Stable presentation key for the expense icon. UI resource names are never persisted.';

create or replace function private.normalize_expense_icon_key(p_icon_key text)
returns text
language sql
immutable
security invoker
set search_path = ''
as $function$
  select case pg_catalog.lower(pg_catalog.btrim(coalesce($1, '')))
    when 'money' then 'money'
    when 'dining' then 'dining'
    when 'shopping' then 'shopping'
    when 'transport' then 'transport'
    when 'hotel' then 'hotel'
    when 'ticket' then 'ticket'
    when 'fuel' then 'fuel'
    when 'entertainment' then 'entertainment'
    when 'medical' then 'medical'
    when 'gift' then 'gift'
    when 'grocery' then 'grocery'
    when 'flight' then 'flight'
    else 'money'
  end;
$function$;

-- Keep the established fact/projection implementations intact. These wrappers
-- add icon persistence in the same transaction and expose new overloads, while
-- the existing RPC signatures remain available for older clients.
create or replace function private.create_expense_with_icon_impl(
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
  p_original_expense_id uuid,
  p_icon_key text
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
begin
  select created.expense_id, created.base_amount, created.version
    into v_expense_id, v_base_amount, v_version
  from private.create_expense_projected_impl(
    p_ledger_unit_id, p_title, p_original_amount, p_original_currency,
    p_fx_rate, p_split_method, p_payments, p_manual_splits,
    p_aa_participant_ids, p_occurred_at, p_note, p_original_expense_id
  ) as created;

  update public.expenses as e
  set icon_key = private.normalize_expense_icon_key(p_icon_key)
  where e.id = v_expense_id;

  return query select v_expense_id, v_base_amount, v_version;
end;
$function$;

create or replace function private.update_expense_with_icon_impl(
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
  p_original_expense_id uuid,
  p_icon_key text
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
begin
  select updated.updated_expense_id, updated.base_amount, updated.version
    into v_updated_expense_id, v_base_amount, v_version
  from private.update_expense_projected_impl(
    p_expense_id, p_ledger_unit_id, p_title, p_original_amount,
    p_original_currency, p_fx_rate, p_split_method, p_payments,
    p_manual_splits, p_aa_participant_ids, p_occurred_at, p_note,
    p_original_expense_id
  ) as updated;

  update public.expenses as e
  set icon_key = private.normalize_expense_icon_key(p_icon_key)
  where e.id = v_updated_expense_id;

  return query select v_updated_expense_id, v_base_amount, v_version;
end;
$function$;

create or replace function private.create_expense_auto_rate_with_icon_impl(
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
  p_original_expense_id uuid,
  p_icon_key text
)
returns table(
  expense_id uuid,
  base_amount numeric(20,1),
  version bigint,
  fx_rate numeric(20,10),
  fx_rate_source text,
  fx_rate_observed_at timestamptz
)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_expense_id uuid;
  v_base_amount numeric(20,1);
  v_version bigint;
  v_fx_rate numeric(20,10);
  v_fx_rate_source text;
  v_fx_rate_observed_at timestamptz;
begin
  select created.expense_id, created.base_amount, created.version,
         created.fx_rate, created.fx_rate_source, created.fx_rate_observed_at
    into v_expense_id, v_base_amount, v_version,
         v_fx_rate, v_fx_rate_source, v_fx_rate_observed_at
  from private.create_expense_auto_rate_impl(
    p_ledger_unit_id, p_title, p_original_amount, p_original_currency,
    p_split_method, p_payments, p_manual_splits, p_aa_participant_ids,
    p_occurred_at, p_note, p_original_expense_id
  ) as created;

  update public.expenses as e
  set icon_key = private.normalize_expense_icon_key(p_icon_key)
  where e.id = v_expense_id;

  return query select v_expense_id, v_base_amount, v_version,
    v_fx_rate, v_fx_rate_source, v_fx_rate_observed_at;
end;
$function$;

create or replace function private.update_expense_auto_rate_with_icon_impl(
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
  p_original_expense_id uuid,
  p_icon_key text
)
returns table(
  updated_expense_id uuid,
  base_amount numeric(20,1),
  version bigint,
  fx_rate numeric(20,10),
  fx_rate_source text,
  fx_rate_observed_at timestamptz
)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_updated_expense_id uuid;
  v_base_amount numeric(20,1);
  v_version bigint;
  v_fx_rate numeric(20,10);
  v_fx_rate_source text;
  v_fx_rate_observed_at timestamptz;
begin
  select updated.updated_expense_id, updated.base_amount, updated.version,
         updated.fx_rate, updated.fx_rate_source, updated.fx_rate_observed_at
    into v_updated_expense_id, v_base_amount, v_version,
         v_fx_rate, v_fx_rate_source, v_fx_rate_observed_at
  from private.update_expense_auto_rate_impl(
    p_expense_id, p_ledger_unit_id, p_title, p_original_amount,
    p_original_currency, p_split_method, p_payments, p_manual_splits,
    p_aa_participant_ids, p_occurred_at, p_note, p_original_expense_id
  ) as updated;

  update public.expenses as e
  set icon_key = private.normalize_expense_icon_key(p_icon_key)
  where e.id = v_updated_expense_id;

  return query select v_updated_expense_id, v_base_amount, v_version,
    v_fx_rate, v_fx_rate_source, v_fx_rate_observed_at;
end;
$function$;

create or replace function public.create_expense(
  ledger_unit_id uuid,
  title text,
  original_amount numeric(20,4),
  original_currency character(3),
  fx_rate numeric(20,10),
  split_method public.expense_split_method,
  payments jsonb,
  manual_splits jsonb,
  aa_participant_ids uuid[],
  occurred_at timestamptz,
  note text,
  original_expense_id uuid,
  icon_key text
)
returns table(expense_id uuid, base_amount numeric(20,1), version bigint)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select * from private.create_expense_with_icon_impl(
    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13
  );
$function$;

create or replace function public.update_expense(
  expense_id uuid,
  ledger_unit_id uuid,
  title text,
  original_amount numeric(20,4),
  original_currency character(3),
  fx_rate numeric(20,10),
  split_method public.expense_split_method,
  payments jsonb,
  manual_splits jsonb,
  aa_participant_ids uuid[],
  occurred_at timestamptz,
  note text,
  original_expense_id uuid,
  icon_key text
)
returns table(updated_expense_id uuid, base_amount numeric(20,1), version bigint)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select * from private.update_expense_with_icon_impl(
    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14
  );
$function$;

create or replace function public.create_expense_auto_rate(
  ledger_unit_id uuid,
  title text,
  original_amount numeric(20,4),
  original_currency character(3),
  split_method public.expense_split_method,
  payments jsonb,
  manual_splits jsonb,
  aa_participant_ids uuid[],
  occurred_at timestamptz,
  note text,
  original_expense_id uuid,
  icon_key text
)
returns table(
  expense_id uuid,
  base_amount numeric(20,1),
  version bigint,
  fx_rate numeric(20,10),
  fx_rate_source text,
  fx_rate_observed_at timestamptz
)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select * from private.create_expense_auto_rate_with_icon_impl(
    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12
  );
$function$;

create or replace function public.update_expense_auto_rate(
  expense_id uuid,
  ledger_unit_id uuid,
  title text,
  original_amount numeric(20,4),
  original_currency character(3),
  split_method public.expense_split_method,
  payments jsonb,
  manual_splits jsonb,
  aa_participant_ids uuid[],
  occurred_at timestamptz,
  note text,
  original_expense_id uuid,
  icon_key text
)
returns table(
  updated_expense_id uuid,
  base_amount numeric(20,1),
  version bigint,
  fx_rate numeric(20,10),
  fx_rate_source text,
  fx_rate_observed_at timestamptz
)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select * from private.update_expense_auto_rate_with_icon_impl(
    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13
  );
$function$;

revoke all on function private.normalize_expense_icon_key(text)
  from public, anon, authenticated;
revoke all on function private.create_expense_with_icon_impl(
  uuid,text,numeric(20,4),character(3),numeric(20,10),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) from public, anon, authenticated;
revoke all on function private.update_expense_with_icon_impl(
  uuid,uuid,text,numeric(20,4),character(3),numeric(20,10),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) from public, anon, authenticated;
revoke all on function private.create_expense_auto_rate_with_icon_impl(
  uuid,text,numeric(20,4),character(3),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) from public, anon, authenticated;
revoke all on function private.update_expense_auto_rate_with_icon_impl(
  uuid,uuid,text,numeric(20,4),character(3),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) from public, anon, authenticated;

grant execute on function private.create_expense_with_icon_impl(
  uuid,text,numeric(20,4),character(3),numeric(20,10),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) to authenticated, service_role;
grant execute on function private.update_expense_with_icon_impl(
  uuid,uuid,text,numeric(20,4),character(3),numeric(20,10),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) to authenticated, service_role;
grant execute on function private.create_expense_auto_rate_with_icon_impl(
  uuid,text,numeric(20,4),character(3),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) to authenticated, service_role;
grant execute on function private.update_expense_auto_rate_with_icon_impl(
  uuid,uuid,text,numeric(20,4),character(3),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) to authenticated, service_role;

revoke all on function public.create_expense(
  uuid,text,numeric(20,4),character(3),numeric(20,10),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) from public, anon;
revoke all on function public.update_expense(
  uuid,uuid,text,numeric(20,4),character(3),numeric(20,10),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) from public, anon;
revoke all on function public.create_expense_auto_rate(
  uuid,text,numeric(20,4),character(3),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) from public, anon;
revoke all on function public.update_expense_auto_rate(
  uuid,uuid,text,numeric(20,4),character(3),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) from public, anon;

grant execute on function public.create_expense(
  uuid,text,numeric(20,4),character(3),numeric(20,10),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) to authenticated;
grant execute on function public.update_expense(
  uuid,uuid,text,numeric(20,4),character(3),numeric(20,10),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) to authenticated;
grant execute on function public.create_expense_auto_rate(
  uuid,text,numeric(20,4),character(3),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) to authenticated;
grant execute on function public.update_expense_auto_rate(
  uuid,uuid,text,numeric(20,4),character(3),public.expense_split_method,
  jsonb,jsonb,uuid[],timestamptz,text,uuid,text
) to authenticated;

commit;
