\set ON_ERROR_STOP on
\ir .dbtest_env.sql

begin;
create extension if not exists pgtap with schema extensions;
create extension if not exists dblink with schema extensions;
select extensions.plan(1);

create function pg_temp.assert_true(p_condition boolean, p_message text)
returns void language plpgsql as $function$
begin
  if p_condition is not true then raise exception 'assertion failed: %', p_message; end if;
end;
$function$;

-- Commit all fixtures in an independent session. The outer test runner owns an
-- isolated, disposable Supabase project; each race below uses two independent
-- authenticated dblink sessions and the production Activity lock.
select extensions.dblink_connect('cm_setup', :'db_conninfo');
select extensions.dblink_exec('cm_setup', 'begin');
select extensions.dblink_exec('cm_setup', $sql$
  insert into auth.users(instance_id,id,aud,role,email,encrypted_password,raw_app_meta_data,raw_user_meta_data,created_at,updated_at) values
    ('00000000-0000-0000-0000-000000000000','c3900000-0000-0000-0000-000000000001','authenticated','authenticated','concurrency.a@example.invalid',crypt('x',gen_salt('bf')),'{}','{}',now(),now()),
    ('00000000-0000-0000-0000-000000000000','c3900000-0000-0000-0000-000000000002','authenticated','authenticated','concurrency.b@example.invalid',crypt('x',gen_salt('bf')),'{}','{}',now(),now());

  insert into public.activities(id,join_code,name,type,base_currency,created_by) values
    ('c3000000-0000-0000-0000-000000000101','99100101','targeted race','normal','CNY','c3900000-0000-0000-0000-000000000001'),
    ('c3000000-0000-0000-0000-000000000102','99100102','refund race','normal','CNY','c3900000-0000-0000-0000-000000000001'),
    ('c3000000-0000-0000-0000-000000000103','99100103','return and source void race','normal','CNY','c3900000-0000-0000-0000-000000000001'),
    ('c3000000-0000-0000-0000-000000000104','99100104','final and expense race','normal','CNY','c3900000-0000-0000-0000-000000000001'),
    ('c3000000-0000-0000-0000-000000000105','99100105','void and settlement race','normal','CNY','c3900000-0000-0000-0000-000000000001');
  insert into public.activity_members(activity_id,user_id)
  select a.id,u.id from public.activities a cross join auth.users u
  where u.id in ('c3900000-0000-0000-0000-000000000001','c3900000-0000-0000-0000-000000000002');
  insert into public.ledger_units(id,activity_id,name,type) values
    ('c3100000-0000-0000-0000-000000000101','c3000000-0000-0000-0000-000000000101','targeted','default'),
    ('c3100000-0000-0000-0000-000000000102','c3000000-0000-0000-0000-000000000102','refund','default'),
    ('c3100000-0000-0000-0000-000000000103','c3000000-0000-0000-0000-000000000103','prepayment','default'),
    ('c3100000-0000-0000-0000-000000000104','c3000000-0000-0000-0000-000000000104','final','default'),
    ('c3100000-0000-0000-0000-000000000105','c3000000-0000-0000-0000-000000000105','settlement','default');
  insert into public.participants(id,activity_id,name,participant_order) values
    ('c3200000-0000-0000-0000-000000000101','c3000000-0000-0000-0000-000000000101','debtor',0),('c3200000-0000-0000-0000-000000000102','c3000000-0000-0000-0000-000000000101','creditor',1),
    ('c3200000-0000-0000-0000-000000000201','c3000000-0000-0000-0000-000000000102','debtor',0),('c3200000-0000-0000-0000-000000000202','c3000000-0000-0000-0000-000000000102','creditor',1),
    ('c3200000-0000-0000-0000-000000000301','c3000000-0000-0000-0000-000000000103','owner',0),('c3200000-0000-0000-0000-000000000302','c3000000-0000-0000-0000-000000000103','custodian',1),
    ('c3200000-0000-0000-0000-000000000401','c3000000-0000-0000-0000-000000000104','debtor',0),('c3200000-0000-0000-0000-000000000402','c3000000-0000-0000-0000-000000000104','creditor',1),
    ('c3200000-0000-0000-0000-000000000501','c3000000-0000-0000-0000-000000000105','debtor',0),('c3200000-0000-0000-0000-000000000502','c3000000-0000-0000-0000-000000000105','creditor',1);
  insert into public.participant_claims(activity_id,participant_id,user_id) values
    ('c3000000-0000-0000-0000-000000000101','c3200000-0000-0000-0000-000000000101','c3900000-0000-0000-0000-000000000001'),
    ('c3000000-0000-0000-0000-000000000102','c3200000-0000-0000-0000-000000000201','c3900000-0000-0000-0000-000000000001'),
    ('c3000000-0000-0000-0000-000000000103','c3200000-0000-0000-0000-000000000302','c3900000-0000-0000-0000-000000000001'),
    ('c3000000-0000-0000-0000-000000000104','c3200000-0000-0000-0000-000000000401','c3900000-0000-0000-0000-000000000001'),
    ('c3000000-0000-0000-0000-000000000105','c3200000-0000-0000-0000-000000000501','c3900000-0000-0000-0000-000000000001');

  create function public.cm_targeted_attempt(p_request_id uuid) returns text
  language plpgsql volatile security invoker set search_path=''
  as $f$ begin
    perform * from public.create_expense_repayment_v2('c3000000-0000-0000-0000-000000000101','c3200000-0000-0000-0000-000000000101','c3200000-0000-0000-0000-000000000102',60,'CNY','TARGETED',array[(select id from public.expenses where title='targeted source')],now(),null,1,p_request_id);
    return 'ok'; exception when others then return sqlstate; end $f$;
  create function public.cm_refund_attempt(p_title text) returns text
  language plpgsql volatile security invoker set search_path=''
  as $f$ begin
    perform * from public.create_expense_auto_rate('c3100000-0000-0000-0000-000000000102',p_title,-60,'CNY','manual','[{"participant_id":"c3200000-0000-0000-0000-000000000201","amount":"-60"}]','[{"participant_id":"c3200000-0000-0000-0000-000000000202","amount":"-60"}]','{}',now(),null,(select id from public.expenses where title='refund source'),'money');
    return 'ok'; exception when others then return sqlstate; end $f$;
  create function public.cm_return_attempt(p_request_id uuid) returns text
  language plpgsql volatile security invoker set search_path=''
  as $f$ begin
    perform * from public.create_prepayment_return_v2('c3000000-0000-0000-0000-000000000103','c3200000-0000-0000-0000-000000000301','c3200000-0000-0000-0000-000000000302',60,'CNY',now(),null,1,p_request_id);
    return 'ok'; exception when others then return sqlstate; end $f$;
  create function public.cm_void_source_attempt() returns text
  language plpgsql volatile security invoker set search_path=''
  as $f$ declare v_source uuid; begin
    select id into v_source from public.transfers where activity_id='c3000000-0000-0000-0000-000000000103' and type='prepayment' order by created_at limit 1;
    perform * from public.void_prepayment_transfer(v_source,'concurrent source correction');
    return 'ok'; exception when others then return sqlstate; end $f$;
  create function public.cm_final_attempt(p_request_id uuid) returns text
  language plpgsql volatile security invoker set search_path=''
  as $f$ begin
    perform * from public.execute_final_settlement_v2('c3000000-0000-0000-0000-000000000104','c3200000-0000-0000-0000-000000000401','c3200000-0000-0000-0000-000000000402',100,'CNY','base_unified',1,p_request_id,now(),null);
    return 'ok'; exception when others then return sqlstate; end $f$;
  create function public.cm_post_final_expense_attempt() returns text
  language plpgsql volatile security invoker set search_path=''
  as $f$ begin
    perform * from public.create_expense_auto_rate('c3100000-0000-0000-0000-000000000104','expense concurrent with Final',10,'CNY','manual','[{"participant_id":"c3200000-0000-0000-0000-000000000402","amount":"10"}]','[{"participant_id":"c3200000-0000-0000-0000-000000000401","amount":"10"}]','{}',now(),null,null,'money');
    return 'ok'; exception when others then return sqlstate; end $f$;
  create function public.cm_void_settlement_attempt() returns text
  language plpgsql volatile security invoker set search_path=''
  as $f$ declare v_transfer uuid; begin
    select id into v_transfer from public.transfers where activity_id='c3000000-0000-0000-0000-000000000105' and type='settlement' and not is_voided order by created_at limit 1;
    perform * from public.void_settlement_transfer(v_transfer,'concurrent settlement correction');
    return 'ok'; exception when others then return sqlstate; end $f$;
  create function public.cm_new_settlement_attempt(p_request_id uuid) returns text
  language plpgsql volatile security invoker set search_path=''
  as $f$ begin
    perform * from public.create_expense_repayment_v2('c3000000-0000-0000-0000-000000000105','c3200000-0000-0000-0000-000000000501','c3200000-0000-0000-0000-000000000502',40,'CNY','TARGETED',array[(select id from public.expenses where title='void settlement source')],now(),null,2,p_request_id);
    return 'ok'; exception when others then return sqlstate; end $f$;

  revoke all on function public.cm_targeted_attempt(uuid),public.cm_refund_attempt(text),public.cm_return_attempt(uuid),public.cm_void_source_attempt(),public.cm_final_attempt(uuid),public.cm_post_final_expense_attempt(),public.cm_void_settlement_attempt(),public.cm_new_settlement_attempt(uuid) from public,anon,authenticated;
  grant execute on function public.cm_targeted_attempt(uuid),public.cm_refund_attempt(text),public.cm_return_attempt(uuid),public.cm_void_source_attempt(),public.cm_final_attempt(uuid),public.cm_post_final_expense_attempt(),public.cm_void_settlement_attempt(),public.cm_new_settlement_attempt(uuid) to authenticated;

  set local role authenticated;
  do $seed$
  begin
    perform set_config('request.jwt.claims','{"sub":"c3900000-0000-0000-0000-000000000001","role":"authenticated"}',true);
    perform * from public.create_expense_auto_rate('c3100000-0000-0000-0000-000000000101','targeted source',100,'CNY','manual','[{"participant_id":"c3200000-0000-0000-0000-000000000102","amount":"100"}]','[{"participant_id":"c3200000-0000-0000-0000-000000000101","amount":"100"}]','{}',now(),null,null,'money');
    perform * from public.create_expense_auto_rate('c3100000-0000-0000-0000-000000000102','refund source',100,'CNY','manual','[{"participant_id":"c3200000-0000-0000-0000-000000000202","amount":"100"}]','[{"participant_id":"c3200000-0000-0000-0000-000000000201","amount":"100"}]','{}',now(),null,null,'money');
    perform * from public.create_expense_auto_rate('c3100000-0000-0000-0000-000000000104','final source',100,'CNY','manual','[{"participant_id":"c3200000-0000-0000-0000-000000000402","amount":"100"}]','[{"participant_id":"c3200000-0000-0000-0000-000000000401","amount":"100"}]','{}',now(),null,null,'money');
    perform * from public.create_expense_auto_rate('c3100000-0000-0000-0000-000000000105','void settlement source',100,'CNY','manual','[{"participant_id":"c3200000-0000-0000-0000-000000000502","amount":"100"}]','[{"participant_id":"c3200000-0000-0000-0000-000000000501","amount":"100"}]','{}',now(),null,null,'money');
    perform * from public.create_expense_repayment_v2('c3000000-0000-0000-0000-000000000105','c3200000-0000-0000-0000-000000000501','c3200000-0000-0000-0000-000000000502',60,'CNY','TARGETED',array[(select id from public.expenses where title='void settlement source')],now(),null,1,'c3400000-0000-0000-0000-000000000105');
    perform * from public.create_prepayment_v2('c3000000-0000-0000-0000-000000000103','c3200000-0000-0000-0000-000000000301','c3200000-0000-0000-0000-000000000302',100,'CNY',now(),null,0,'c3500000-0000-0000-0000-000000000103');
  end $seed$;
$sql$);
select extensions.dblink_exec('cm_setup','commit');
select extensions.dblink_disconnect('cm_setup');

-- The dblink setup above is the only writer using the two concurrent sessions' fixtures.
-- For each case, release two requests from the same real transaction lock.

-- Two TARGETED settlements submitted against one financial version.
select extensions.dblink_connect('cm_t_lock',:'db_conninfo');
select extensions.dblink_connect('cm_t_a',:'db_conninfo');
select extensions.dblink_connect('cm_t_b',:'db_conninfo');
select extensions.dblink_exec('cm_t_a','set role authenticated');
select extensions.dblink_exec('cm_t_b','set role authenticated');
select extensions.dblink_exec('cm_t_a',$sql$do $c$ begin perform set_config('request.jwt.claims','{"sub":"c3900000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $c$;$sql$);
select extensions.dblink_exec('cm_t_b',$sql$do $c$ begin perform set_config('request.jwt.claims','{"sub":"c3900000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $c$;$sql$);
select extensions.dblink_exec('cm_t_lock','begin');
select extensions.dblink_exec('cm_t_lock',$sql$do $l$ begin perform private.lock_debt_projection_activity('c3000000-0000-0000-0000-000000000101'); end $l$;$sql$);
select extensions.dblink_send_query('cm_t_a','select public.cm_targeted_attempt(''c3600000-0000-0000-0000-000000000101'')');
select extensions.dblink_send_query('cm_t_b','select public.cm_targeted_attempt(''c3600000-0000-0000-0000-000000000102'')');
select pg_catalog.pg_sleep(0.2);
select pg_temp.assert_true(extensions.dblink_is_busy('cm_t_a')=1 and extensions.dblink_is_busy('cm_t_b')=1,'both TARGETED calls queue behind the Activity lock');
select extensions.dblink_exec('cm_t_lock','commit');
do $w$ begin while extensions.dblink_is_busy('cm_t_a')=1 or extensions.dblink_is_busy('cm_t_b')=1 loop perform pg_catalog.pg_sleep(0.02); end loop; end $w$;
create temporary table cm_targeted_results(result text);
insert into cm_targeted_results select result from extensions.dblink_get_result('cm_t_a') as x(result text);
insert into cm_targeted_results select result from extensions.dblink_get_result('cm_t_b') as x(result text);
select pg_temp.assert_true((select count(*)=1 from cm_targeted_results where result='ok') and (select count(*)=1 from cm_targeted_results where result='40001') and (select count(*)=1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000101' and type='settlement' and not is_voided) and (select financial_version=2 from public.activities where id='c3000000-0000-0000-0000-000000000101'),'one same-version TARGETED settlement commits and the stale call changes no facts');
select extensions.dblink_disconnect('cm_t_lock'); select extensions.dblink_disconnect('cm_t_a'); select extensions.dblink_disconnect('cm_t_b');

-- Two linked refunds of 60 against a source Expense of 100.
select extensions.dblink_connect('cm_r_lock',:'db_conninfo');
select extensions.dblink_connect('cm_r_a',:'db_conninfo');
select extensions.dblink_connect('cm_r_b',:'db_conninfo');
select extensions.dblink_exec('cm_r_a','set role authenticated'); select extensions.dblink_exec('cm_r_b','set role authenticated');
select extensions.dblink_exec('cm_r_a',$sql$do $c$ begin perform set_config('request.jwt.claims','{"sub":"c3900000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $c$;$sql$);
select extensions.dblink_exec('cm_r_b',$sql$do $c$ begin perform set_config('request.jwt.claims','{"sub":"c3900000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $c$;$sql$);
select extensions.dblink_exec('cm_r_lock','begin');
select extensions.dblink_exec('cm_r_lock',$sql$do $l$ begin perform private.lock_debt_projection_activity('c3000000-0000-0000-0000-000000000102'); end $l$;$sql$);
select extensions.dblink_send_query('cm_r_a','select public.cm_refund_attempt(''refund race A'')');
select extensions.dblink_send_query('cm_r_b','select public.cm_refund_attempt(''refund race B'')');
select pg_catalog.pg_sleep(0.2);
select pg_temp.assert_true(extensions.dblink_is_busy('cm_r_a')=1 and extensions.dblink_is_busy('cm_r_b')=1,'both Refund calls queue behind the Activity lock');
select extensions.dblink_exec('cm_r_lock','commit');
do $w$ begin while extensions.dblink_is_busy('cm_r_a')=1 or extensions.dblink_is_busy('cm_r_b')=1 loop perform pg_catalog.pg_sleep(0.02); end loop; end $w$;
create temporary table cm_refund_results(result text);
insert into cm_refund_results select result from extensions.dblink_get_result('cm_r_a') as x(result text);
insert into cm_refund_results select result from extensions.dblink_get_result('cm_r_b') as x(result text);
select pg_temp.assert_true((select count(*)=1 from cm_refund_results where result='ok') and (select count(*)=1 from cm_refund_results where result='23514') and (select count(*)=1 from public.expenses where ledger_unit_id='c3100000-0000-0000-0000-000000000102' and original_expense_id=(select id from public.expenses where title='refund source') and not is_deleted) and (select sum(abs(original_amount))=60 from public.expenses where ledger_unit_id='c3100000-0000-0000-0000-000000000102' and original_expense_id=(select id from public.expenses where title='refund source') and not is_deleted),'refund race serializes cumulative source cap; the winning partial refund is never doubled');
select extensions.dblink_disconnect('cm_r_lock'); select extensions.dblink_disconnect('cm_r_a'); select extensions.dblink_disconnect('cm_r_b');

-- PrepaymentReturn racing the void of its prepayment source. Either legal serial
-- order wins; source and return can never both remain effective after a void.
select extensions.dblink_connect('cm_p_lock',:'db_conninfo');
select extensions.dblink_connect('cm_p_a',:'db_conninfo');
select extensions.dblink_connect('cm_p_b',:'db_conninfo');
select extensions.dblink_exec('cm_p_a','set role authenticated'); select extensions.dblink_exec('cm_p_b','set role authenticated');
select extensions.dblink_exec('cm_p_a',$sql$do $c$ begin perform set_config('request.jwt.claims','{"sub":"c3900000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $c$;$sql$);
select extensions.dblink_exec('cm_p_b',$sql$do $c$ begin perform set_config('request.jwt.claims','{"sub":"c3900000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $c$;$sql$);
select extensions.dblink_exec('cm_p_lock','begin');
select extensions.dblink_exec('cm_p_lock',$sql$do $l$ begin perform private.lock_debt_projection_activity('c3000000-0000-0000-0000-000000000103'); end $l$;$sql$);
select extensions.dblink_send_query('cm_p_a','select public.cm_return_attempt(''c3600000-0000-0000-0000-000000000103'')');
select extensions.dblink_send_query('cm_p_b','select public.cm_void_source_attempt()');
select pg_catalog.pg_sleep(0.2);
select pg_temp.assert_true(extensions.dblink_is_busy('cm_p_a')=1 and extensions.dblink_is_busy('cm_p_b')=1,'return and source void both queue behind the Activity lock');
select extensions.dblink_exec('cm_p_lock','commit');
do $w$ begin while extensions.dblink_is_busy('cm_p_a')=1 or extensions.dblink_is_busy('cm_p_b')=1 loop perform pg_catalog.pg_sleep(0.02); end loop; end $w$;
create temporary table cm_prepayment_results(result text);
insert into cm_prepayment_results select result from extensions.dblink_get_result('cm_p_a') as x(result text);
insert into cm_prepayment_results select result from extensions.dblink_get_result('cm_p_b') as x(result text);
select pg_temp.assert_true(
  (select count(*)=1 from cm_prepayment_results where result='ok')
  and (
    (exists(select 1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000103' and type='prepayment' and not is_voided)
      and exists(select 1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000103' and type='prepayment_return' and not is_voided))
    or (exists(select 1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000103' and type='prepayment' and is_voided)
      and not exists(select 1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000103' and type='prepayment_return' and not is_voided))
  ),
  'source void and return leave one legal serialized state');
select pg_temp.assert_true(
  not (exists(select 1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000103' and type='prepayment' and is_voided)
    and exists(select 1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000103' and type='prepayment_return' and not is_voided)),
  'a valid return can never outlive its voided source');
select extensions.dblink_disconnect('cm_p_lock'); select extensions.dblink_disconnect('cm_p_a'); select extensions.dblink_disconnect('cm_p_b');

-- Final execution racing a new Expense: either final consumes the old plan
-- first, or the new version makes that preview stale.
select extensions.dblink_connect('cm_f_lock',:'db_conninfo');
select extensions.dblink_connect('cm_f_a',:'db_conninfo');
select extensions.dblink_connect('cm_f_b',:'db_conninfo');
select extensions.dblink_exec('cm_f_a','set role authenticated'); select extensions.dblink_exec('cm_f_b','set role authenticated');
select extensions.dblink_exec('cm_f_a',$sql$do $c$ begin perform set_config('request.jwt.claims','{"sub":"c3900000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $c$;$sql$);
select extensions.dblink_exec('cm_f_b',$sql$do $c$ begin perform set_config('request.jwt.claims','{"sub":"c3900000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $c$;$sql$);
select extensions.dblink_exec('cm_f_lock','begin');
select extensions.dblink_exec('cm_f_lock',$sql$do $l$ begin perform private.lock_debt_projection_activity('c3000000-0000-0000-0000-000000000104'); end $l$;$sql$);
select extensions.dblink_send_query('cm_f_a','select public.cm_final_attempt(''c3600000-0000-0000-0000-000000000104'')');
select extensions.dblink_send_query('cm_f_b','select public.cm_post_final_expense_attempt()');
select pg_catalog.pg_sleep(0.2);
select pg_temp.assert_true(extensions.dblink_is_busy('cm_f_a')=1 and extensions.dblink_is_busy('cm_f_b')=1,'Final execution and Expense state change queue behind the Activity lock');
select extensions.dblink_exec('cm_f_lock','commit');
do $w$ begin while extensions.dblink_is_busy('cm_f_a')=1 or extensions.dblink_is_busy('cm_f_b')=1 loop perform pg_catalog.pg_sleep(0.02); end loop; end $w$;
create temporary table cm_final_results(result text);
insert into cm_final_results select 'final:'||result from extensions.dblink_get_result('cm_f_a') as x(result text);
insert into cm_final_results select 'expense:'||result from extensions.dblink_get_result('cm_f_b') as x(result text);
select pg_temp.assert_true((select count(*)=1 from cm_final_results where result='expense:ok') and ((select count(*)=1 from cm_final_results where result='final:ok') or (select count(*)=1 from cm_final_results where result='final:40001')),'Final versus Expense resolves to one serial order and stale Final plans are rejected');
select pg_temp.assert_true(
  ((select financial_version=3 from public.activities where id='c3000000-0000-0000-0000-000000000104')
    and exists(select 1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000104' and type='final_settlement' and not is_voided)
    and exists(select 1 from public.expenses where ledger_unit_id='c3100000-0000-0000-0000-000000000104' and title='expense concurrent with Final'))
  or ((select financial_version=2 from public.activities where id='c3000000-0000-0000-0000-000000000104')
    and not exists(select 1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000104' and type='final_settlement' and not is_voided)
    and exists(select 1 from public.expenses where ledger_unit_id='c3100000-0000-0000-0000-000000000104' and title='expense concurrent with Final')),
  'Final and Expense facts, plan version and final debt match a legal serial order');
select extensions.dblink_disconnect('cm_f_lock'); select extensions.dblink_disconnect('cm_f_a'); select extensions.dblink_disconnect('cm_f_b');

-- Voiding an earlier settlement racing the final remaining targeted payment.
select extensions.dblink_connect('cm_v_lock',:'db_conninfo');
select extensions.dblink_connect('cm_v_a',:'db_conninfo');
select extensions.dblink_connect('cm_v_b',:'db_conninfo');
select extensions.dblink_exec('cm_v_a','set role authenticated'); select extensions.dblink_exec('cm_v_b','set role authenticated');
select extensions.dblink_exec('cm_v_a',$sql$do $c$ begin perform set_config('request.jwt.claims','{"sub":"c3900000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $c$;$sql$);
select extensions.dblink_exec('cm_v_b',$sql$do $c$ begin perform set_config('request.jwt.claims','{"sub":"c3900000-0000-0000-0000-000000000001","role":"authenticated"}',false); end $c$;$sql$);
select extensions.dblink_exec('cm_v_lock','begin');
select extensions.dblink_exec('cm_v_lock',$sql$do $l$ begin perform private.lock_debt_projection_activity('c3000000-0000-0000-0000-000000000105'); end $l$;$sql$);
select extensions.dblink_send_query('cm_v_a','select public.cm_void_settlement_attempt()');
select extensions.dblink_send_query('cm_v_b','select public.cm_new_settlement_attempt(''c3600000-0000-0000-0000-000000000105'')');
select pg_catalog.pg_sleep(0.2);
select pg_temp.assert_true(extensions.dblink_is_busy('cm_v_a')=1 and extensions.dblink_is_busy('cm_v_b')=1,'void and new settlement queue behind the Activity lock');
select extensions.dblink_exec('cm_v_lock','commit');
do $w$ begin while extensions.dblink_is_busy('cm_v_a')=1 or extensions.dblink_is_busy('cm_v_b')=1 loop perform pg_catalog.pg_sleep(0.02); end loop; end $w$;
create temporary table cm_void_results(result text);
insert into cm_void_results select 'void:'||result from extensions.dblink_get_result('cm_v_a') as x(result text);
insert into cm_void_results select 'settle:'||result from extensions.dblink_get_result('cm_v_b') as x(result text);
select pg_temp.assert_true((select count(*)=1 from cm_void_results where result='void:ok') and ((select count(*)=1 from cm_void_results where result='settle:40001') or (select count(*)=1 from cm_void_results where result='settle:ok')),'void and new settlement resolve through the same Activity serialization boundary');
select pg_temp.assert_true(
  ((select financial_version=3 from public.activities where id='c3000000-0000-0000-0000-000000000105')
    and exists(select 1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000105' and type='settlement' and is_voided)
    and not exists(select 1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000105' and type='settlement' and not is_voided)
    and exists(select 1 from public.bilateral_debts where activity_id='c3000000-0000-0000-0000-000000000105' and amount=100))
  or ((select financial_version=4 from public.activities where id='c3000000-0000-0000-0000-000000000105')
    and exists(select 1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000105' and type='settlement' and is_voided)
    and exists(select 1 from public.transfers where activity_id='c3000000-0000-0000-0000-000000000105' and type='settlement' and not is_voided and amount=40)
    and exists(select 1 from public.bilateral_debts where activity_id='c3000000-0000-0000-0000-000000000105' and amount=60)),
  'void/new-settlement history and current debt equal one legal serial order');
select extensions.dblink_disconnect('cm_v_lock'); select extensions.dblink_disconnect('cm_v_a'); select extensions.dblink_disconnect('cm_v_b');

select pass('financial concurrency matrix preserves legal serialized outcomes');
select * from extensions.finish();
rollback;
