\set ON_ERROR_STOP on
begin;
create extension if not exists pgtap with schema extensions;
select extensions.plan(1);
create extension if not exists dblink with schema extensions;
create function pg_temp.assert_true(p_condition boolean,p_message text) returns void language plpgsql as $f$ begin if p_condition is not true then raise exception 'assertion failed: %',p_message; end if; end;$f$;
select extensions.dblink_connect('p5_setup','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_exec('p5_setup','begin');
select extensions.dblink_exec('p5_setup',$sql$
 insert into auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at) values
 ('00000000-0000-0000-0000-000000000000','f7500000-0000-0000-0000-000000000001','authenticated','authenticated','p5a@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());
 insert into public.activities(id,join_code,name,type,base_currency,created_by) values('f7600000-0000-0000-0000-000000000001','97000001','p5 concurrency','normal','CNY','f7500000-0000-0000-0000-000000000001');
 insert into public.activity_members(activity_id,user_id) values('f7600000-0000-0000-0000-000000000001','f7500000-0000-0000-0000-000000000001');
 insert into public.ledger_units(id,activity_id,name,type) values('f7700000-0000-0000-0000-000000000001','f7600000-0000-0000-0000-000000000001','p5','default');
 insert into public.participants(id,activity_id,name,participant_order) values('f7800000-0000-0000-0000-000000000001','f7600000-0000-0000-0000-000000000001','owner',0),('f7800000-0000-0000-0000-000000000002','f7600000-0000-0000-0000-000000000001','custodian',1);
 insert into public.participant_claims(activity_id,participant_id,user_id) values('f7600000-0000-0000-0000-000000000001','f7800000-0000-0000-0000-000000000001','f7500000-0000-0000-0000-000000000001');
 create function public.p5_return_attempt() returns text language plpgsql volatile security invoker set search_path='' as $attempt$ begin perform * from public.create_prepayment_return('f7600000-0000-0000-0000-000000000001','f7800000-0000-0000-0000-000000000001','f7800000-0000-0000-0000-000000000002',60,now(),null); return 'ok'; exception when others then return sqlstate; end;$attempt$;
 revoke all on function public.p5_return_attempt() from public, anon, authenticated; grant execute on function public.p5_return_attempt() to authenticated;
 set role authenticated; select set_config('request.jwt.claims','{"sub":"f7500000-0000-0000-0000-000000000001","role":"authenticated"}',false);
 do $seed$ begin perform * from public.create_prepayment('f7600000-0000-0000-0000-000000000001','f7800000-0000-0000-0000-000000000001','f7800000-0000-0000-0000-000000000002',100,now(),null); end $seed$;
 commit
$sql$); select extensions.dblink_disconnect('p5_setup');
select extensions.dblink_connect('p5_lock','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_connect('p5_a','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_connect('p5_b','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_exec('p5_a',$sql$set role authenticated; do $claims$ begin perform set_config('request.jwt.claims','{"sub":"f7500000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $claims$;$sql$);
select extensions.dblink_exec('p5_b',$sql$set role authenticated; do $claims$ begin perform set_config('request.jwt.claims','{"sub":"f7500000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $claims$;$sql$);
select extensions.dblink_exec('p5_lock','begin'); select extensions.dblink_exec('p5_lock','do $lock$ begin perform private.lock_debt_projection_activity(''f7600000-0000-0000-0000-000000000001''); end $lock$');
select extensions.dblink_send_query('p5_a','select public.p5_return_attempt()'); select extensions.dblink_send_query('p5_b','select public.p5_return_attempt()'); select pg_sleep(.2);
select pg_temp.assert_true(extensions.dblink_is_busy('p5_a')=1 and extensions.dblink_is_busy('p5_b')=1,'both returns queue behind Activity lock');
select extensions.dblink_exec('p5_lock','commit');
do $wait$ begin while extensions.dblink_is_busy('p5_a')=1 or extensions.dblink_is_busy('p5_b')=1 loop perform pg_sleep(.02); end loop; end;$wait$;
create temporary table p5_results(result text); insert into p5_results select result from extensions.dblink_get_result('p5_a') as x(result text); insert into p5_results select result from extensions.dblink_get_result('p5_b') as x(result text);
select pg_temp.assert_true((select count(*)=1 from p5_results where result='ok') and (select count(*)=1 from p5_results where result='23514'),'one 60 return succeeds and one is rejected');
select pg_temp.assert_true((select balance=40 from public.prepayment_accounts where activity_id='f7600000-0000-0000-0000-000000000001') and (select count(*)=1 from public.transfers where activity_id='f7600000-0000-0000-0000-000000000001' and not is_voided and type='prepayment_return') and (select financial_version=2 from public.activities where id='f7600000-0000-0000-0000-000000000001'),'balance, facts and version are updated once');
select extensions.dblink_disconnect('p5_lock'); select extensions.dblink_disconnect('p5_a'); select extensions.dblink_disconnect('p5_b');
select extensions.dblink_connect('p5_cleanup','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres'); select extensions.dblink_exec('p5_cleanup','begin; delete from public.transfer_components where activity_id=''f7600000-0000-0000-0000-000000000001''; delete from public.transfers where activity_id=''f7600000-0000-0000-0000-000000000001''; delete from public.prepayment_accounts where activity_id=''f7600000-0000-0000-0000-000000000001''; delete from public.activity_members where activity_id=''f7600000-0000-0000-0000-000000000001''; delete from public.participant_claims where activity_id=''f7600000-0000-0000-0000-000000000001''; delete from public.participants where activity_id=''f7600000-0000-0000-0000-000000000001''; delete from public.ledger_units where activity_id=''f7600000-0000-0000-0000-000000000001''; delete from public.activities where id=''f7600000-0000-0000-0000-000000000001''; delete from auth.users where id=''f7500000-0000-0000-0000-000000000001''; drop function public.p5_return_attempt(); commit'); select extensions.dblink_disconnect('p5_cleanup'); select pass('Phase 5 concurrency assertions'); select * from extensions.finish(); rollback;
