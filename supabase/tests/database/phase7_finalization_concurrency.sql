\set ON_ERROR_STOP on
begin;
create extension if not exists pgtap with schema extensions;
create extension if not exists dblink with schema extensions;
select extensions.plan(4);
create function pg_temp.assert_true(p boolean,m text) returns void language plpgsql as $$begin if p is not true then raise exception '%',m; end if; end$$;
select extensions.dblink_connect('p7_setup','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_exec('p7_setup',$sql$
 insert into auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at) values
 ('00000000-0000-0000-0000-000000000000','fa700000-0000-0000-0000-000000000001','authenticated','authenticated','p7a@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','fa700000-0000-0000-0000-000000000002','authenticated','authenticated','p7b@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());
 insert into public.activities(id,join_code,name,type,base_currency,created_by) values('fa710000-0000-0000-0000-000000000001','97000701','p7 concurrency','normal','CNY','fa700000-0000-0000-0000-000000000001');
 insert into public.activity_members(activity_id,user_id) values('fa710000-0000-0000-0000-000000000001','fa700000-0000-0000-0000-000000000001'),('fa710000-0000-0000-0000-000000000001','fa700000-0000-0000-0000-000000000002');
 insert into public.participants(id,activity_id,name,participant_order) values('fa720000-0000-0000-0000-000000000001','fa710000-0000-0000-0000-000000000001','race',0);
 create function public.p7_claim_attempt(a uuid) returns text language plpgsql security invoker set search_path='' as $f$ begin perform * from public.claim_participant('fa710000-0000-0000-0000-000000000001','fa720000-0000-0000-0000-000000000001'); return 'ok'; exception when others then return sqlstate; end $f$;
 revoke all on function public.p7_claim_attempt(uuid) from public,anon,authenticated; grant execute on function public.p7_claim_attempt(uuid) to authenticated;
 commit
$sql$);
select extensions.dblink_disconnect('p7_setup');
select extensions.dblink_connect('p7_a','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_connect('p7_b','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_exec('p7_a',$sql$set role authenticated; do $claims$ begin perform set_config('request.jwt.claims','{"sub":"fa700000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $claims$;$sql$);
select extensions.dblink_exec('p7_b',$sql$set role authenticated; do $claims$ begin perform set_config('request.jwt.claims','{"sub":"fa700000-0000-0000-0000-000000000002","role":"authenticated"}',false); end $claims$;$sql$);
select extensions.dblink_send_query('p7_a','select public.p7_claim_attempt(''fa700000-0000-0000-0000-000000000001'')');
select extensions.dblink_send_query('p7_b','select public.p7_claim_attempt(''fa700000-0000-0000-0000-000000000002'')');
do $$ begin while extensions.dblink_is_busy('p7_a')=1 or extensions.dblink_is_busy('p7_b')=1 loop perform pg_sleep(.02); end loop; end$$;
create temporary table p7_results(result text);
insert into p7_results select result from extensions.dblink_get_result('p7_a') as x(result text);
insert into p7_results select result from extensions.dblink_get_result('p7_b') as x(result text);
do $$ begin perform pg_temp.assert_true((select count(*)=1 from p7_results where result='ok') and (select count(*)=1 from p7_results where result='23505'),'claim race permits exactly one owner'); end $$;
select pass('claim race permits exactly one owner');
do $$ begin perform pg_temp.assert_true((select count(*)=1 from public.participant_claims where participant_id='fa720000-0000-0000-0000-000000000001'),'claim uniqueness remains intact'); end $$;
select pass('claim uniqueness remains intact');
select extensions.dblink_disconnect('p7_a'); select extensions.dblink_disconnect('p7_b');

-- Race participant creation against the first expense that locks the list.
select extensions.dblink_connect('p7_setup_more','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_exec('p7_setup_more',$sql$
  begin;
  insert into public.activities(id,join_code,name,type,base_currency,created_by)
  values ('fa710000-0000-0000-0000-000000000002','97000702','p7 participant lock race','normal','CNY','fa700000-0000-0000-0000-000000000001'),
         ('fa710000-0000-0000-0000-000000000003','97000703','p7 attachment limit race','normal','CNY','fa700000-0000-0000-0000-000000000001');
  insert into public.activity_members(activity_id,user_id) values
    ('fa710000-0000-0000-0000-000000000002','fa700000-0000-0000-0000-000000000001'),
    ('fa710000-0000-0000-0000-000000000002','fa700000-0000-0000-0000-000000000002'),
    ('fa710000-0000-0000-0000-000000000003','fa700000-0000-0000-0000-000000000001'),
    ('fa710000-0000-0000-0000-000000000003','fa700000-0000-0000-0000-000000000002');
  insert into public.ledger_units(id,activity_id,name,type) values
    ('fa711000-0000-0000-0000-000000000002','fa710000-0000-0000-0000-000000000002','default','default'),
    ('fa711000-0000-0000-0000-000000000003','fa710000-0000-0000-0000-000000000003','default','default');
  insert into public.participants(id,activity_id,name,participant_order)
  values ('fa720000-0000-0000-0000-000000000002','fa710000-0000-0000-0000-000000000002','existing',0);
  insert into public.attachments(id,activity_id,ledger_unit_id,original_filename,mime_type,size_bytes,uploaded_by,storage_path)
  select extensions.gen_random_uuid(),'fa710000-0000-0000-0000-000000000003','fa711000-0000-0000-0000-000000000003','seed-'||g||'.jpg','image/jpeg',1000,'fa700000-0000-0000-0000-000000000001','fa710000-0000-0000-0000-000000000003/fa711000-0000-0000-0000-000000000003/seed-'||g||'.jpg'
  from generate_series(1,9) g;
  create function public.p7_add_or_expense_attempt(p_mode text) returns text language plpgsql security invoker set search_path=''
  as $attempt$ begin
    if p_mode='add' then perform * from public.create_participant('fa710000-0000-0000-0000-000000000002','raced',null);
    else perform * from public.create_expense('fa711000-0000-0000-0000-000000000002','race expense',10,'CNY',1,'manual','[{"participant_id":"fa720000-0000-0000-0000-000000000002","amount":10}]','[{"participant_id":"fa720000-0000-0000-0000-000000000002","amount":10}]','{}',pg_catalog.now(),null,null); end if;
    return 'ok'; exception when others then return sqlstate; end $attempt$;
  create function public.p7_attachment_attempt() returns text language plpgsql security invoker set search_path=''
  as $attempt$ begin
    perform * from public.create_attachment('fa710000-0000-0000-0000-000000000003','fa711000-0000-0000-0000-000000000003',null,'race.jpg','image/jpeg',1000); return 'ok'; exception when others then return sqlstate; end $attempt$;
  revoke all on function public.p7_add_or_expense_attempt(text),public.p7_attachment_attempt() from public,anon,authenticated;
  grant execute on function public.p7_add_or_expense_attempt(text),public.p7_attachment_attempt() to authenticated;
  commit;
$sql$);
select extensions.dblink_disconnect('p7_setup_more');

select extensions.dblink_connect('p7_c','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_connect('p7_d','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_connect('p7_lock','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_exec('p7_c','set role authenticated');
select extensions.dblink_exec('p7_d','set role authenticated');
select extensions.dblink_exec('p7_c',$sql$do $claims$ begin perform set_config('request.jwt.claims','{"sub":"fa700000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $claims$;$sql$);
select extensions.dblink_exec('p7_d',$sql$do $claims$ begin perform set_config('request.jwt.claims','{"sub":"fa700000-0000-0000-0000-000000000002","role":"authenticated"}',false); end $claims$;$sql$);
select extensions.dblink_exec('p7_lock','begin; do $lock$ begin perform private.lock_debt_projection_activity(''fa710000-0000-0000-0000-000000000002''); end $lock$;');
select extensions.dblink_send_query('p7_c','select public.p7_add_or_expense_attempt(''add'')');
select extensions.dblink_send_query('p7_d','select public.p7_add_or_expense_attempt(''expense'')');
select pg_catalog.pg_sleep(0.2);
select extensions.dblink_exec('p7_lock','commit');
do $$ begin while extensions.dblink_is_busy('p7_c')=1 or extensions.dblink_is_busy('p7_d')=1 loop perform pg_catalog.pg_sleep(0.02); end loop; end $$;
create temporary table p7_lock_results(result text);
insert into p7_lock_results select result from extensions.dblink_get_result('p7_c') as x(result text);
insert into p7_lock_results select result from extensions.dblink_get_result('p7_d') as x(result text);
do $$ begin perform pg_temp.assert_true((select count(*)=2 from p7_lock_results) and (select count(*) >= 1 from p7_lock_results where result='ok') and exists(select 1 from public.activities where id='fa710000-0000-0000-0000-000000000002' and participants_locked_at is not null),'participant/expense race remains serialized'); end $$;
select pass('participant/expense race remains serialized');
select extensions.dblink_disconnect('p7_c'); select extensions.dblink_disconnect('p7_d'); select extensions.dblink_disconnect('p7_lock');

-- Two concurrent uploads may consume only the final tenth attachment slot.
select extensions.dblink_connect('p7_e','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_connect('p7_f','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_exec('p7_e','set role authenticated'); select extensions.dblink_exec('p7_f','set role authenticated');
select extensions.dblink_exec('p7_e',$sql$do $claims$ begin perform set_config('request.jwt.claims','{"sub":"fa700000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $claims$;$sql$);
select extensions.dblink_exec('p7_f',$sql$do $claims$ begin perform set_config('request.jwt.claims','{"sub":"fa700000-0000-0000-0000-000000000002","role":"authenticated"}',false); end $claims$;$sql$);
select extensions.dblink_send_query('p7_e','select public.p7_attachment_attempt()'); select extensions.dblink_send_query('p7_f','select public.p7_attachment_attempt()');
do $$ begin while extensions.dblink_is_busy('p7_e')=1 or extensions.dblink_is_busy('p7_f')=1 loop perform pg_catalog.pg_sleep(0.02); end loop; end $$;
create temporary table p7_attachment_results(result text);
insert into p7_attachment_results select result from extensions.dblink_get_result('p7_e') as x(result text);
insert into p7_attachment_results select result from extensions.dblink_get_result('p7_f') as x(result text);
do $$ begin perform pg_temp.assert_true((select count(*)=1 from p7_attachment_results where result='ok') and (select count(*)=1 from p7_attachment_results where result='54000') and (select count(*)=10 from public.attachments where activity_id='fa710000-0000-0000-0000-000000000003' and status in ('pending','ready')),'attachment target limit is race safe'); end $$;
select pass('attachment target limit is race safe');
select extensions.dblink_disconnect('p7_e'); select extensions.dblink_disconnect('p7_f');
select extensions.dblink_connect('p7_cleanup','host=supabase_db_shared-ledger port=5432 dbname=postgres user=postgres password=postgres');
select extensions.dblink_exec('p7_cleanup','begin; drop function public.p7_add_or_expense_attempt(text); drop function public.p7_attachment_attempt(); delete from public.attachments where activity_id in (''fa710000-0000-0000-0000-000000000003''); delete from public.splits where expense_id in (select id from public.expenses where ledger_unit_id=''fa711000-0000-0000-0000-000000000002''); delete from public.payments where expense_id in (select id from public.expenses where ledger_unit_id=''fa711000-0000-0000-0000-000000000002''); delete from public.expenses where ledger_unit_id=''fa711000-0000-0000-0000-000000000002''; delete from public.participant_claims where activity_id in (''fa710000-0000-0000-0000-000000000001'',''fa710000-0000-0000-0000-000000000002''); delete from public.participants where activity_id in (''fa710000-0000-0000-0000-000000000001'',''fa710000-0000-0000-0000-000000000002''); delete from public.activity_members where activity_id in (''fa710000-0000-0000-0000-000000000001'',''fa710000-0000-0000-0000-000000000002'',''fa710000-0000-0000-0000-000000000003''); delete from public.ledger_units where activity_id in (''fa710000-0000-0000-0000-000000000001'',''fa710000-0000-0000-0000-000000000002'',''fa710000-0000-0000-0000-000000000003''); delete from public.activities where id in (''fa710000-0000-0000-0000-000000000001'',''fa710000-0000-0000-0000-000000000002'',''fa710000-0000-0000-0000-000000000003''); delete from auth.users where id in (''fa700000-0000-0000-0000-000000000001'',''fa700000-0000-0000-0000-000000000002''); drop function public.p7_claim_attempt(uuid); commit');
select extensions.dblink_disconnect('p7_cleanup');
select * from extensions.finish(); rollback;
