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

-- Use two independent database sessions to prove that identical Activity IDs
-- serialize on the shared transaction-scoped debt projection advisory lock.
select extensions.dblink_connect(
  'phase3_projection_locker',
  'host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres'
);
select extensions.dblink_connect(
  'phase3_projection_waiter',
  'host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres'
);

select extensions.dblink_exec('phase3_projection_locker', 'begin');
select extensions.dblink_exec(
  'phase3_projection_locker',
  'do $lock$ begin perform private.lock_debt_projection_activity(''e0000000-0000-0000-0000-00000000ff01''::uuid); end $lock$'
);

select extensions.dblink_send_query(
  'phase3_projection_waiter',
  'select private.lock_debt_projection_activity(''e0000000-0000-0000-0000-00000000ff01''::uuid)'
);
select pg_catalog.pg_sleep(0.2);

select pg_temp.assert_true(
  extensions.dblink_is_busy('phase3_projection_waiter') = 1,
  'a concurrent rebuild for the same Activity must wait on the advisory lock'
);

select extensions.dblink_exec('phase3_projection_locker', 'commit');

do $wait$
begin
  while extensions.dblink_is_busy('phase3_projection_waiter') = 1 loop
    perform pg_catalog.pg_sleep(0.02);
  end loop;
end;
$wait$;

select *
from extensions.dblink_get_result('phase3_projection_waiter')
  as completed(lock_result text);

select pg_temp.assert_true(
  pg_catalog.strpos(
    pg_catalog.lower(
      pg_catalog.pg_get_functiondef(
        'private.rebuild_expense_and_bilateral_debts(uuid,uuid)'::regprocedure
      )
    ),
    'perform private.lock_debt_projection_activity(p_activity_id)'
  ) > 0
  and pg_catalog.strpos(
    pg_catalog.lower(
      pg_catalog.pg_get_functiondef(
        'private.rebuild_activity_debt_projection(uuid)'::regprocedure
      )
    ),
    'perform private.lock_debt_projection_activity(p_activity_id)'
  ) > 0,
  'incremental and full rebuild paths must acquire the same Activity lock helper'
);

select extensions.dblink_disconnect('phase3_projection_locker');
select extensions.dblink_disconnect('phase3_projection_waiter');

rollback;
