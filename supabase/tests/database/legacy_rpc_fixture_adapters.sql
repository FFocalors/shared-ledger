-- Test-only adapters for older phase fixtures that deliberately exercise the
-- shared implementation with a fixed FX input. Keep this file out of
-- migrations: these SECURITY DEFINER helpers exist only in pg_temp for the
-- current transaction and are never exposed through PostgREST.
--
-- Current client-contract tests must call auto_rate/v2 RPCs directly and must
-- separately assert that legacy authenticated EXECUTE grants are revoked.

create function pg_temp.create_expense_fixture(
  p_ledger_unit_id uuid,
  p_title text,
  p_original_amount numeric,
  p_original_currency character,
  p_fx_rate numeric,
  p_split_method public.expense_split_method,
  p_payments jsonb default '[]'::jsonb,
  p_manual_splits jsonb default '[]'::jsonb,
  p_aa_participant_ids uuid[] default '{}'::uuid[],
  p_occurred_at timestamp with time zone default now(),
  p_note text default null,
  p_original_expense_id uuid default null,
  p_icon_key text default 'money'
)
returns table(expense_id uuid, base_amount numeric, version bigint)
language sql
security definer
set search_path = ''
as $function$
  select *
  from public.create_expense(
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
    p_original_expense_id,
    p_icon_key
  )
$function$;

create function pg_temp.update_expense_fixture(
  p_expense_id uuid,
  p_ledger_unit_id uuid,
  p_title text,
  p_original_amount numeric,
  p_original_currency character,
  p_fx_rate numeric,
  p_split_method public.expense_split_method,
  p_payments jsonb default '[]'::jsonb,
  p_manual_splits jsonb default '[]'::jsonb,
  p_aa_participant_ids uuid[] default '{}'::uuid[],
  p_occurred_at timestamp with time zone default now(),
  p_note text default null,
  p_original_expense_id uuid default null,
  p_icon_key text default 'money'
)
returns table(updated_expense_id uuid, base_amount numeric, version bigint)
language sql
security definer
set search_path = ''
as $function$
  select *
  from public.update_expense(
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
    p_original_expense_id,
    p_icon_key
  )
$function$;

create function pg_temp.create_settlement_transfer_fixture(
  p_activity_id uuid,
  p_from_participant_id uuid,
  p_to_participant_id uuid,
  p_amount numeric,
  p_occurred_at timestamp with time zone default now(),
  p_on_behalf_of_participant_id uuid default null
)
returns table(transfer_id uuid, amount numeric, currency character, financial_version bigint)
language sql
security definer
set search_path = ''
as $function$
  select *
  from public.create_settlement_transfer(
    p_activity_id,
    p_from_participant_id,
    p_to_participant_id,
    p_amount,
    p_occurred_at,
    p_on_behalf_of_participant_id
  )
$function$;

create function pg_temp.create_settlement_transfer_fixture(
  p_activity_id uuid,
  p_from_participant_id uuid,
  p_to_participant_id uuid,
  p_amount numeric,
  p_currency character,
  p_occurred_at timestamp with time zone,
  p_on_behalf_of_participant_id uuid,
  p_request_id uuid
)
returns table(transfer_id uuid, amount numeric, currency character, financial_version bigint)
language sql
security definer
set search_path = ''
as $function$
  select *
  from public.create_settlement_transfer(
    p_activity_id,
    p_from_participant_id,
    p_to_participant_id,
    p_amount,
    p_currency,
    p_occurred_at,
    p_on_behalf_of_participant_id,
    p_request_id
  )
$function$;

create function pg_temp.create_prepayment_fixture(
  p_activity_id uuid,
  p_owner_participant_id uuid,
  p_custodian_participant_id uuid,
  p_amount numeric,
  p_occurred_at timestamp with time zone default now(),
  p_on_behalf_of_participant_id uuid default null
)
returns table(transfer_id uuid, settlement_amount numeric, prepayment_amount numeric, currency character, financial_version bigint)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_currency character(3);
  v_expected_version bigint;
begin
  select a.base_currency, a.financial_version
    into v_currency, v_expected_version
    from public.activities a
    where a.id = p_activity_id;
  if not found then
    raise exception using errcode = 'P0002', message = 'activity was not found';
  end if;
  return query
    select r.transfer_id, r.settlement_amount, r.prepayment_amount,
           r.currency, r.financial_version
    from public.create_prepayment_v2(
      p_activity_id,
      p_owner_participant_id,
      p_custodian_participant_id,
      p_amount,
      v_currency,
      p_occurred_at,
      p_on_behalf_of_participant_id,
      v_expected_version,
      pg_catalog.gen_random_uuid()
    ) as r;
end;
$function$;

create function pg_temp.create_prepayment_return_fixture(
  p_activity_id uuid,
  p_owner_participant_id uuid,
  p_custodian_participant_id uuid,
  p_amount numeric,
  p_occurred_at timestamp with time zone default now(),
  p_on_behalf_of_participant_id uuid default null
)
returns table(transfer_id uuid, amount numeric, currency character, financial_version bigint)
language sql
security definer
set search_path = ''
as $function$
  select *
  from public.create_prepayment_return(
    p_activity_id,
    p_owner_participant_id,
    p_custodian_participant_id,
    p_amount,
    p_occurred_at,
    p_on_behalf_of_participant_id
  )
$function$;

create function pg_temp.execute_final_settlement_fixture(
  p_activity_id uuid,
  p_from_participant_id uuid,
  p_to_participant_id uuid,
  p_amount numeric,
  p_occurred_at timestamp with time zone default now(),
  p_on_behalf_of_participant_id uuid default null
)
returns table(transfer_id uuid, amount numeric, currency character, financial_version bigint)
language sql
security definer
set search_path = ''
as $function$
  select *
  from public.execute_final_settlement(
    p_activity_id,
    p_from_participant_id,
    p_to_participant_id,
    p_amount,
    p_occurred_at,
    p_on_behalf_of_participant_id
  )
$function$;

create function pg_temp.create_final_settlement_fixture(
  p_activity_id uuid,
  p_from_participant_id uuid,
  p_to_participant_id uuid,
  p_amount numeric,
  p_occurred_at timestamp with time zone default now(),
  p_on_behalf_of_participant_id uuid default null
)
returns table(transfer_id uuid, amount numeric, currency character, financial_version bigint)
language sql
security definer
set search_path = ''
as $function$
  select *
  from public.create_final_settlement(
    p_activity_id,
    p_from_participant_id,
    p_to_participant_id,
    p_amount,
    p_occurred_at,
    p_on_behalf_of_participant_id
  )
$function$;
