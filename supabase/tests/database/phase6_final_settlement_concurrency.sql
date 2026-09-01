\set ON_ERROR_STOP on

begin;
create extension if not exists dblink with schema extensions;
create extension if not exists pgtap with schema extensions;
select extensions.plan(1);

create function pg_temp.assert_true(p_condition boolean, p_message text)
returns void language plpgsql as $function$
begin
  if p_condition is not true then raise exception 'assertion failed: %', p_message; end if;
end;
$function$;

-- Commit the fixture in an independent session so both real RPC sessions can
-- see it.  Cleanup is also independent because the test transaction cannot
-- roll back commits made by dblink sessions.
select extensions.dblink_connect('phase6_setup','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_exec('phase6_setup','begin');
select extensions.dblink_exec('phase6_setup',$sql$
  insert into auth.users(instance_id,id,aud,role,email,encrypted_password,raw_app_meta_data,raw_user_meta_data,created_at,updated_at) values
   ('00000000-0000-0000-0000-000000000000','f8700000-0000-0000-0000-000000000001','authenticated','authenticated','phase6.concurrent.a@example.invalid',crypt('x',gen_salt('bf')),'{}','{}',now(),now()),
   ('00000000-0000-0000-0000-000000000000','f8700000-0000-0000-0000-000000000002','authenticated','authenticated','phase6.concurrent.b@example.invalid',crypt('x',gen_salt('bf')),'{}','{}',now(),now());
  insert into public.activities(id,join_code,name,type,base_currency,created_by) values ('f8700000-0000-0000-0000-000000000001','87000001','Phase 6 concurrent final','large','CNY','f8700000-0000-0000-0000-000000000001');
  insert into public.activity_members(activity_id,user_id) values
   ('f8700000-0000-0000-0000-000000000001','f8700000-0000-0000-0000-000000000001'),
   ('f8700000-0000-0000-0000-000000000001','f8700000-0000-0000-0000-000000000002');
  insert into public.ledger_units(id,activity_id,name,type) values ('f8710000-0000-0000-0000-000000000001','f8700000-0000-0000-0000-000000000001','root','root'),('f8710000-0000-0000-0000-000000000002','f8700000-0000-0000-0000-000000000001','child','sub_activity');
  insert into public.participants(id,activity_id,name,participant_order) values
   ('f8720000-0000-0000-0000-000000000001','f8700000-0000-0000-0000-000000000001','A',0),
   ('f8720000-0000-0000-0000-000000000002','f8700000-0000-0000-0000-000000000001','B',1),
   ('f8720000-0000-0000-0000-000000000003','f8700000-0000-0000-0000-000000000001','C',2);
  insert into public.participant_claims(activity_id,participant_id,user_id) values
   ('f8700000-0000-0000-0000-000000000001','f8720000-0000-0000-0000-000000000001','f8700000-0000-0000-0000-000000000001'),
   ('f8700000-0000-0000-0000-000000000001','f8720000-0000-0000-0000-000000000003','f8700000-0000-0000-0000-000000000002');
  create function public.phase6_final_attempt() returns text language plpgsql volatile security invoker set search_path='' as $attempt$
  begin
    perform * from public.execute_final_settlement('f8700000-0000-0000-0000-000000000001','f8720000-0000-0000-0000-000000000001','f8720000-0000-0000-0000-000000000003',100,now(),null);
    return 'ok';
  exception when others then return sqlstate;
  end;
  $attempt$;
  revoke all on function public.phase6_final_attempt() from public,anon,authenticated;
  grant execute on function public.phase6_final_attempt() to authenticated;
  set local role authenticated;
  select set_config('request.jwt.claims','{"sub":"f8700000-0000-0000-0000-000000000001","role":"authenticated"}',true);
  do $setup_expenses$
  begin
    perform * from public.create_expense('f8710000-0000-0000-0000-000000000001','root debt',100,'CNY',1,'manual','[{"participant_id":"f8720000-0000-0000-0000-000000000002","amount":"100"}]','[{"participant_id":"f8720000-0000-0000-0000-000000000001","amount":"100"}]','{}',now(),null,null);
    perform * from public.create_expense('f8710000-0000-0000-0000-000000000002','child debt',100,'CNY',1,'manual','[{"participant_id":"f8720000-0000-0000-0000-000000000003","amount":"100"}]','[{"participant_id":"f8720000-0000-0000-0000-000000000002","amount":"100"}]','{}',now(),null,null);
  end
  $setup_expenses$;
$sql$);
select extensions.dblink_exec('phase6_setup','commit');
select extensions.dblink_disconnect('phase6_setup');

select extensions.dblink_connect('phase6_lock','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_connect('phase6_attempt_a','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_connect('phase6_attempt_b','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_exec('phase6_attempt_a','set role authenticated');
select extensions.dblink_exec('phase6_attempt_a',$sql$do $claims$ begin perform set_config('request.jwt.claims','{"sub":"f8700000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $claims$;$sql$);
select extensions.dblink_exec('phase6_attempt_b','set role authenticated');
select extensions.dblink_exec('phase6_attempt_b',$sql$do $claims$ begin perform set_config('request.jwt.claims','{"sub":"f8700000-0000-0000-0000-000000000002","role":"authenticated"}',false); end $claims$;$sql$);

select extensions.dblink_exec('phase6_lock','begin');
select extensions.dblink_exec('phase6_lock',$sql$do $lock$ begin perform private.lock_debt_projection_activity('f8700000-0000-0000-0000-000000000001'); end $lock$;$sql$);
select extensions.dblink_send_query('phase6_attempt_a','select public.phase6_final_attempt()');
select extensions.dblink_send_query('phase6_attempt_b','select public.phase6_final_attempt()');
select pg_catalog.pg_sleep(0.2);
select pg_temp.assert_true(extensions.dblink_is_busy('phase6_attempt_a')=1 and extensions.dblink_is_busy('phase6_attempt_b')=1,'both final RPCs wait on the shared Activity lock');
select extensions.dblink_exec('phase6_lock','commit');
do $wait$ begin while extensions.dblink_is_busy('phase6_attempt_a')=1 or extensions.dblink_is_busy('phase6_attempt_b')=1 loop perform pg_catalog.pg_sleep(0.02); end loop; end $wait$;

create temporary table phase6_concurrency_results(attempt text primary key,result text not null) on commit drop;
insert into phase6_concurrency_results select 'a',result from extensions.dblink_get_result('phase6_attempt_a') as x(result text);
insert into phase6_concurrency_results select 'b',result from extensions.dblink_get_result('phase6_attempt_b') as x(result text);
select pg_temp.assert_true((select count(*)=1 from phase6_concurrency_results where result='ok') and (select count(*)=1 from phase6_concurrency_results where result='23514'),'exactly one concurrent final execution succeeds and the loser sees the current-plan conflict');
select pg_temp.assert_true((select count(*)=1 from public.transfers where activity_id='f8700000-0000-0000-0000-000000000001' and type='final_settlement' and not is_voided) and (select count(*)=2 and sum(amount)=200 from public.final_settlement_paths where activity_id='f8700000-0000-0000-0000-000000000001') and (select financial_version=3 from public.activities where id='f8700000-0000-0000-0000-000000000001'),'concurrent final execution creates one fact, two-edge path, and one version increment');

select extensions.dblink_disconnect('phase6_lock');
select extensions.dblink_disconnect('phase6_attempt_a');
select extensions.dblink_disconnect('phase6_attempt_b');
select extensions.dblink_connect('phase6_cleanup','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_exec('phase6_cleanup','begin');
select extensions.dblink_exec('phase6_cleanup',$sql$
  delete from public.final_settlement_paths where activity_id='f8700000-0000-0000-0000-000000000001';
  delete from public.transfer_components where activity_id='f8700000-0000-0000-0000-000000000001';
  delete from public.transfers where activity_id='f8700000-0000-0000-0000-000000000001';
  delete from public.bilateral_debts where activity_id='f8700000-0000-0000-0000-000000000001';
  delete from public.expense_debts where activity_id='f8700000-0000-0000-0000-000000000001';
  delete from public.payments where expense_id in (select e.id from public.expenses e join public.ledger_units l on l.id=e.ledger_unit_id where l.activity_id='f8700000-0000-0000-0000-000000000001');
  delete from public.splits where expense_id in (select e.id from public.expenses e join public.ledger_units l on l.id=e.ledger_unit_id where l.activity_id='f8700000-0000-0000-0000-000000000001');
  delete from public.expenses where ledger_unit_id in (select id from public.ledger_units where activity_id='f8700000-0000-0000-0000-000000000001');
  delete from public.participant_claims where activity_id='f8700000-0000-0000-0000-000000000001';
  delete from public.participants where activity_id='f8700000-0000-0000-0000-000000000001';
  delete from public.ledger_units where activity_id='f8700000-0000-0000-0000-000000000001';
  delete from public.activity_members where activity_id='f8700000-0000-0000-0000-000000000001';
  delete from public.activities where id='f8700000-0000-0000-0000-000000000001';
  delete from auth.users where id in ('f8700000-0000-0000-0000-000000000001','f8700000-0000-0000-0000-000000000002');
  drop function public.phase6_final_attempt()
$sql$);
select extensions.dblink_exec('phase6_cleanup','commit');
select extensions.dblink_disconnect('phase6_cleanup');
select pass('Phase 6 final settlement concurrency assertions');
select * from extensions.finish();
rollback;
