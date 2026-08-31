\set ON_ERROR_STOP on

begin;

create extension if not exists dblink with schema extensions;

create function pg_temp.assert_true(p_condition boolean, p_message text)
returns void
language plpgsql
as $function$
begin
  if p_condition is not true then
    raise exception 'assertion failed: %', p_message;
  end if;
end;
$function$;

-- The fixture is committed by an independent setup session so both competing
-- sessions can see it. It is removed by an independent cleanup session before
-- this test transaction rolls back.
select extensions.dblink_connect(
  'phase4_setup',
  'host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres'
);
select extensions.dblink_exec('phase4_setup', 'begin');
select extensions.dblink_exec(
  'phase4_setup',
  $sql$
    insert into auth.users (
      instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
      raw_app_meta_data, raw_user_meta_data, created_at, updated_at
    ) values
      ('00000000-0000-0000-0000-000000000000', 'f5300000-0000-0000-0000-000000000001', 'authenticated', 'authenticated', 'phase4.concurrent.a@example.invalid', crypt('phase4-password', gen_salt('bf')), now(), '{}', '{}', now(), now()),
      ('00000000-0000-0000-0000-000000000000', 'f5300000-0000-0000-0000-000000000002', 'authenticated', 'authenticated', 'phase4.concurrent.b@example.invalid', crypt('phase4-password', gen_salt('bf')), now(), '{}', '{}', now(), now())
  $sql$
);
select extensions.dblink_exec(
  'phase4_setup',
  $sql$
    insert into public.activities (
      id, join_code, name, type, base_currency, created_by
    ) values (
      'f5000000-0000-0000-0000-000000000001', '95000001',
      'Concurrent settlement', 'normal', 'CNY',
      'f5300000-0000-0000-0000-000000000001'
    )
  $sql$
);
select extensions.dblink_exec(
  'phase4_setup',
  $sql$
    insert into public.activity_members (activity_id, user_id) values
      ('f5000000-0000-0000-0000-000000000001', 'f5300000-0000-0000-0000-000000000001'),
      ('f5000000-0000-0000-0000-000000000001', 'f5300000-0000-0000-0000-000000000002');
    insert into public.ledger_units (id, activity_id, name, type) values
      ('f5100000-0000-0000-0000-000000000001', 'f5000000-0000-0000-0000-000000000001', 'Concurrent ledger', 'default');
    insert into public.participants (id, activity_id, name, participant_order) values
      ('f5200000-0000-0000-0000-000000000001', 'f5000000-0000-0000-0000-000000000001', 'Creditor', 0),
      ('f5200000-0000-0000-0000-000000000002', 'f5000000-0000-0000-0000-000000000001', 'Debtor', 1);
    insert into public.participant_claims (activity_id, participant_id, user_id) values
      ('f5000000-0000-0000-0000-000000000001', 'f5200000-0000-0000-0000-000000000001', 'f5300000-0000-0000-0000-000000000001'),
      ('f5000000-0000-0000-0000-000000000001', 'f5200000-0000-0000-0000-000000000002', 'f5300000-0000-0000-0000-000000000002')
  $sql$
);
select extensions.dblink_exec(
  'phase4_setup',
  $sql$
    create function public.phase4_concurrency_attempt()
    returns text
    language plpgsql
    volatile
    security invoker
    set search_path = ''
    as $attempt$
    begin
      perform * from public.create_settlement_transfer(
        'f5000000-0000-0000-0000-000000000001',
        'f5200000-0000-0000-0000-000000000002',
        'f5200000-0000-0000-0000-000000000001',
        60,
        pg_catalog.now(),
        null
      );
      return 'ok';
    exception when others then
      return sqlstate;
    end;
    $attempt$;
    revoke all on function public.phase4_concurrency_attempt() from public, anon, authenticated;
    grant execute on function public.phase4_concurrency_attempt() to authenticated
  $sql$
);
select extensions.dblink_exec('phase4_setup', 'set local role authenticated');
select extensions.dblink_exec(
  'phase4_setup',
  $sql$
    do $setup$
    begin
      perform set_config(
        'request.jwt.claims',
        '{"sub":"f5300000-0000-0000-0000-000000000001","role":"authenticated"}',
        true
      );
      perform * from public.create_expense(
        'f5100000-0000-0000-0000-000000000001',
        'Concurrent debt', 100, 'CNY', 1, 'manual',
        '[{"participant_id":"f5200000-0000-0000-0000-000000000001","amount":"100"}]',
        '[{"participant_id":"f5200000-0000-0000-0000-000000000002","amount":"100"}]',
        '{}', pg_catalog.now(), null, null
      );
    end;
    $setup$
  $sql$
);
select extensions.dblink_exec('phase4_setup', 'commit');
select extensions.dblink_disconnect('phase4_setup');

select extensions.dblink_connect(
  'phase4_locker',
  'host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres'
);
select extensions.dblink_connect(
  'phase4_attempt_a',
  'host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres'
);
select extensions.dblink_connect(
  'phase4_attempt_b',
  'host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres'
);

select extensions.dblink_exec('phase4_attempt_a', 'set role authenticated');
select extensions.dblink_exec(
  'phase4_attempt_a',
  $sql$
    do $claims$ begin
      perform set_config('request.jwt.claims', '{"sub":"f5300000-0000-0000-0000-000000000001","role":"authenticated"}', false);
    end $claims$
  $sql$
);
select extensions.dblink_exec('phase4_attempt_b', 'set role authenticated');
select extensions.dblink_exec(
  'phase4_attempt_b',
  $sql$
    do $claims$ begin
      perform set_config('request.jwt.claims', '{"sub":"f5300000-0000-0000-0000-000000000002","role":"authenticated"}', false);
    end $claims$
  $sql$
);

-- Queue both real RPC transactions behind the same advisory lock, then release
-- them together. One commits 60; the other re-reads the remaining 40 and fails.
select extensions.dblink_exec('phase4_locker', 'begin');
select extensions.dblink_exec(
  'phase4_locker',
  $sql$
    do $lock$ begin
      perform private.lock_debt_projection_activity('f5000000-0000-0000-0000-000000000001');
    end $lock$
  $sql$
);

select extensions.dblink_send_query(
  'phase4_attempt_a',
  'select public.phase4_concurrency_attempt()'
);
select extensions.dblink_send_query(
  'phase4_attempt_b',
  'select public.phase4_concurrency_attempt()'
);
select pg_catalog.pg_sleep(0.2);

select pg_temp.assert_true(
  extensions.dblink_is_busy('phase4_attempt_a') = 1
  and extensions.dblink_is_busy('phase4_attempt_b') = 1,
  'both settlement RPCs must wait behind the Activity advisory lock'
);

select extensions.dblink_exec('phase4_locker', 'commit');

do $wait$
begin
  while extensions.dblink_is_busy('phase4_attempt_a') = 1
     or extensions.dblink_is_busy('phase4_attempt_b') = 1 loop
    perform pg_catalog.pg_sleep(0.02);
  end loop;
end;
$wait$;

create temporary table phase4_concurrency_results (
  attempt text primary key,
  result text not null
) on commit drop;

insert into phase4_concurrency_results
select 'a', result
from extensions.dblink_get_result('phase4_attempt_a') as completed(result text);
insert into phase4_concurrency_results
select 'b', result
from extensions.dblink_get_result('phase4_attempt_b') as completed(result text);

select pg_temp.assert_true(
  (select count(*) = 1 from phase4_concurrency_results where result = 'ok')
  and (select count(*) = 1 from phase4_concurrency_results where result = '23514'),
  'exactly one concurrent 60 settlement may consume a debt of 100'
);

select pg_temp.assert_true(
  (
    select count(*) = 1 and pg_catalog.sum(amount) = 60
    from public.transfers
    where activity_id = 'f5000000-0000-0000-0000-000000000001'
      and not is_voided
  )
  and exists (
    select 1 from public.bilateral_debts
    where activity_id = 'f5000000-0000-0000-0000-000000000001'
      and amount = 40
  )
  and (
    select financial_version = 2
    from public.activities
    where id = 'f5000000-0000-0000-0000-000000000001'
  ),
  'concurrent calls must not exceed debt and the rejected call must not increment version'
);

select extensions.dblink_disconnect('phase4_locker');
select extensions.dblink_disconnect('phase4_attempt_a');
select extensions.dblink_disconnect('phase4_attempt_b');

select extensions.dblink_connect(
  'phase4_cleanup',
  'host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres'
);
select extensions.dblink_exec('phase4_cleanup', 'begin');
select extensions.dblink_exec(
  'phase4_cleanup',
  $sql$
    delete from public.transfer_allocations where activity_id = 'f5000000-0000-0000-0000-000000000001';
    delete from public.transfers where activity_id = 'f5000000-0000-0000-0000-000000000001';
    delete from public.bilateral_debts where activity_id = 'f5000000-0000-0000-0000-000000000001';
    delete from public.expense_debts where activity_id = 'f5000000-0000-0000-0000-000000000001';
    delete from public.payments where expense_id in (
      select e.id from public.expenses as e
      where e.ledger_unit_id = 'f5100000-0000-0000-0000-000000000001'
    );
    delete from public.splits where expense_id in (
      select e.id from public.expenses as e
      where e.ledger_unit_id = 'f5100000-0000-0000-0000-000000000001'
    );
    delete from public.expenses where ledger_unit_id = 'f5100000-0000-0000-0000-000000000001';
    delete from public.participant_claims where activity_id = 'f5000000-0000-0000-0000-000000000001';
    delete from public.participants where activity_id = 'f5000000-0000-0000-0000-000000000001';
    delete from public.ledger_units where activity_id = 'f5000000-0000-0000-0000-000000000001';
    delete from public.activity_members where activity_id = 'f5000000-0000-0000-0000-000000000001';
    delete from public.activities where id = 'f5000000-0000-0000-0000-000000000001';
    delete from auth.users where id in (
      'f5300000-0000-0000-0000-000000000001',
      'f5300000-0000-0000-0000-000000000002'
    );
    drop function public.phase4_concurrency_attempt()
  $sql$
);
select extensions.dblink_exec('phase4_cleanup', 'commit');
select extensions.dblink_disconnect('phase4_cleanup');

rollback;
