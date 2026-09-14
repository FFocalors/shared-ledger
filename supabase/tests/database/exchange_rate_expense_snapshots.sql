\set ON_ERROR_STOP on

-- Focused server-contract fixture. Run after `supabase db reset` with psql;
-- every write is rolled back at the end.
begin;

create function pg_temp.assert_true(p_condition boolean, p_message text)
returns void language plpgsql as $function$
begin
  if p_condition is not true then raise exception 'assertion failed: %', p_message; end if;
end;
$function$;

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password,
  email_confirmed_at, raw_app_meta_data, raw_user_meta_data, created_at, updated_at
)
values (
  '00000000-0000-0000-0000-000000000000',
  'fe000000-0000-0000-0000-000000000001', 'authenticated', 'authenticated',
  'fx-snapshot@example.invalid', crypt('fx-snapshot-password', gen_salt('bf')),
  now(), '{}', '{}', now(), now()
);

insert into public.activities (
  id, join_code, name, type, base_currency, multi_currency_enabled, created_by
)
values
  ('fe100000-0000-0000-0000-000000000001', 'FE000001', 'FX CNY', 'normal', 'CNY', true, 'fe000000-0000-0000-0000-000000000001'),
  ('fe100000-0000-0000-0000-000000000002', 'FE000002', 'FX AUD no cache', 'normal', 'AUD', true, 'fe000000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id, user_id)
values
  ('fe100000-0000-0000-0000-000000000001', 'fe000000-0000-0000-0000-000000000001'),
  ('fe100000-0000-0000-0000-000000000002', 'fe000000-0000-0000-0000-000000000001');
insert into public.ledger_units(id, activity_id, name, type)
values
  ('fe110000-0000-0000-0000-000000000001', 'fe100000-0000-0000-0000-000000000001', 'root', 'default'),
  ('fe110000-0000-0000-0000-000000000002', 'fe100000-0000-0000-0000-000000000002', 'root', 'default');
insert into public.participants(id, activity_id, name, participant_order)
values
  ('fe120000-0000-0000-0000-000000000001', 'fe100000-0000-0000-0000-000000000001', 'A', 0),
  ('fe120000-0000-0000-0000-000000000002', 'fe100000-0000-0000-0000-000000000001', 'B', 1),
  ('fe120000-0000-0000-0000-000000000003', 'fe100000-0000-0000-0000-000000000002', 'GBP A', 0);

set local role service_role;
select * from public.replace_exchange_rate_cache(
  '2026-09-12',
  '{"EUR":"1","USD":"1.25","CNY":"7.10","JPY":"170.00","GBP":"0.86"}'::jsonb
);
reset role;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"fe000000-0000-0000-0000-000000000001","role":"authenticated"}', true);

select pg_temp.assert_true(
  (select rate = 5.68 and source = 'ECB_REFERENCE'
   from public.get_exchange_rate('CNY', 'USD')),
  'ECB cross rate must be base_per_EUR / quote_per_EUR with decimal precision'
);
select pg_temp.assert_true(
  (select rate = 1 and source = 'same_currency'
   from public.get_exchange_rate('CNY', 'CNY')),
  'same-currency read contract must return one'
);

create temporary table fx_ids(label text primary key, id uuid not null) on commit drop;
with created as (
  select * from public.create_expense_auto_rate(
    'fe110000-0000-0000-0000-000000000001', 'USD expense', 10.0000, 'USD', 'manual',
    '[{"participant_id":"fe120000-0000-0000-0000-000000000001","amount":"10.0000"}]'::jsonb,
    '[{"participant_id":"fe120000-0000-0000-0000-000000000002","amount":"10.0000"}]'::jsonb,
    '{}'::uuid[], now(), null, null
  )
)
insert into fx_ids select 'original', expense_id from created;
select pg_temp.assert_true(
  (select fx_rate = 5.68 and fx_rate_source = 'ECB_REFERENCE' and fx_rate_observed_at = '2026-09-12'::date::timestamptz and base_amount = 56.8 from public.expenses where id=(select id from fx_ids where label='original')),
  'auto create must return and persist the server cache snapshot'
);

-- Refresh the cache. Updating the same currency must still preserve the old
-- snapshot, while changing currency must take the new latest snapshot.
reset role;
set local role service_role;
select * from public.replace_exchange_rate_cache(
  '2026-09-13',
  '{"EUR":"1","USD":"1.10","CNY":"7.20","JPY":"170.00","GBP":"0.86"}'::jsonb
);
reset role;
set local role authenticated;
with updated as (
  select * from public.update_expense_auto_rate(
    (select id from fx_ids where label='original'), 'fe110000-0000-0000-0000-000000000001',
    'USD expense revised', 11.0000, 'USD', 'manual',
    '[{"participant_id":"fe120000-0000-0000-0000-000000000001","amount":"11.0000"}]'::jsonb,
    '[{"participant_id":"fe120000-0000-0000-0000-000000000002","amount":"11.0000"}]'::jsonb,
    '{}'::uuid[], now(), null, null
  )
)
select pg_temp.assert_true(
  fx_rate = 5.68 and fx_rate_source = 'ECB_REFERENCE' and base_amount = 62.5,
  'same-currency update must preserve the original FX snapshot'
)
from updated;
with changed as (
  select * from public.update_expense_auto_rate(
    (select id from fx_ids where label='original'), 'fe110000-0000-0000-0000-000000000001',
    'EUR expense revised', 11.0000, 'EUR', 'manual',
    '[{"participant_id":"fe120000-0000-0000-0000-000000000001","amount":"11.0000"}]'::jsonb,
    '[{"participant_id":"fe120000-0000-0000-0000-000000000002","amount":"11.0000"}]'::jsonb,
    '{}'::uuid[], now(), null, null
  )
)
select pg_temp.assert_true(
  fx_rate = 7.20 and fx_rate_observed_at = '2026-09-13'::date::timestamptz,
  'currency change must use the latest server cache snapshot'
)
from changed;

-- A linked refund inherits the original complete snapshot, even though the
-- cache now has a different USD rate (the original was changed to EUR above).
with created as (
  select * from public.create_expense_auto_rate(
    'fe110000-0000-0000-0000-000000000001', 'linked refund', -1.0000, 'EUR', 'manual',
    '[{"participant_id":"fe120000-0000-0000-0000-000000000001","amount":"-1.0000"}]'::jsonb,
    '[{"participant_id":"fe120000-0000-0000-0000-000000000002","amount":"-1.0000"}]'::jsonb,
    '{}'::uuid[], now(), null, (select id from fx_ids where label='original')
  )
)
select pg_temp.assert_true(fx_rate = 7.20, 'linked refund must inherit original snapshot') from created;

do $test$
begin
  begin
    perform public.create_expense_auto_rate(
      'fe110000-0000-0000-0000-000000000002', 'missing AUD cache', 1.0000, 'USD', 'manual',
      '[{"participant_id":"fe120000-0000-0000-0000-000000000003","amount":"1.0000"}]'::jsonb,
      '[{"participant_id":"fe120000-0000-0000-0000-000000000003","amount":"1.0000"}]'::jsonb,
      '{}'::uuid[], now(), null, null
    );
    raise exception 'missing cache unexpectedly succeeded';
  exception when sqlstate '22023' then null;
  end;
end;
$test$;

reset role;
set local role service_role;
update public.exchange_rate_cache
set observed_at = now() - interval '73 hours'
where base_currency = 'CNY' and quote_currency = 'USD';
reset role;
set local role authenticated;
with stale as (
  select * from public.create_expense_auto_rate(
    'fe110000-0000-0000-0000-000000000001', 'stale USD cache', 1.0000, 'USD', 'manual',
    '[{"participant_id":"fe120000-0000-0000-0000-000000000001","amount":"1.0000"}]'::jsonb,
    '[{"participant_id":"fe120000-0000-0000-0000-000000000001","amount":"1.0000"}]'::jsonb,
    '{}'::uuid[], now(), null, null
  )
)
select pg_temp.assert_true(
  fx_rate = 6.5454545455 and fx_rate_observed_at < now() - interval '72 hours',
  'stale cache must remain usable while exposing its observed date'
)
from stale;

select pg_temp.assert_true(
  not has_function_privilege('anon', 'public.create_expense_auto_rate(uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)', 'EXECUTE')
  and has_function_privilege('authenticated', 'public.create_expense_auto_rate(uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)', 'EXECUTE')
  and has_function_privilege('authenticated', 'public.update_expense_auto_rate(uuid,uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)', 'EXECUTE')
  and has_function_privilege('authenticated', 'private.create_expense_auto_rate_impl(uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)', 'EXECUTE')
  and has_function_privilege('authenticated', 'private.update_expense_auto_rate_impl(uuid,uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)', 'EXECUTE')
  and has_function_privilege('authenticated', 'private.resolve_expense_fx_snapshot(uuid,character,uuid,uuid)', 'EXECUTE'),
  'auto Expense RPC must be authenticated-only, expose no client FX argument, and retain its private execution chain'
);

reset role;
rollback;
