\set ON_ERROR_STOP on

create extension if not exists pgtap with schema extensions;

begin;

\ir legacy_rpc_fixture_adapters.sql
select extensions.plan(8);

create function pg_temp.assert_true(p_condition boolean, p_message text)
returns void language plpgsql as $function$
begin
  if p_condition is not true then raise exception 'assertion failed: %', p_message; end if;
end;
$function$;

create function pg_temp.authenticate(p_user_id uuid)
returns void language plpgsql as $function$
begin
  perform set_config('request.jwt.claims', json_build_object('sub', p_user_id, 'role', 'authenticated')::text, true);
end;
$function$;

insert into auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
values
 ('00000000-0000-0000-0000-000000000000','f1100000-0000-0000-0000-000000000001','authenticated','authenticated','phase11.a@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','f1100000-0000-0000-0000-000000000002','authenticated','authenticated','phase11.b@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());

insert into public.activities(id,join_code,name,type,base_currency,multi_currency_enabled,created_by)
values('f1000000-0000-0000-0000-000000000001','91110001','Multi-currency settlement','normal','CNY',true,'f1100000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id)
values ('f1000000-0000-0000-0000-000000000001','f1100000-0000-0000-0000-000000000001'),
       ('f1000000-0000-0000-0000-000000000001','f1100000-0000-0000-0000-000000000002');
insert into public.ledger_units(id,activity_id,name,type)
values('f1200000-0000-0000-0000-000000000001','f1000000-0000-0000-0000-000000000001','Main','default');
insert into public.participants(id,activity_id,name,participant_order)
values('f1300000-0000-0000-0000-000000000001','f1000000-0000-0000-0000-000000000001','A',0),
      ('f1300000-0000-0000-0000-000000000002','f1000000-0000-0000-0000-000000000001','B',1),
      ('f1300000-0000-0000-0000-000000000003','f1000000-0000-0000-0000-000000000001','C',2);
insert into public.participant_claims(activity_id,participant_id,user_id)
values('f1000000-0000-0000-0000-000000000001','f1300000-0000-0000-0000-000000000001','f1100000-0000-0000-0000-000000000001'),
      ('f1000000-0000-0000-0000-000000000001','f1300000-0000-0000-0000-000000000002','f1100000-0000-0000-0000-000000000002');

select pg_temp.authenticate('f1100000-0000-0000-0000-000000000002');
create temporary table phase11_ids(label text primary key, object_id uuid) on commit drop;

-- B owes A 100 USD (6.7 snapshot) and 100 CNY.
select expense_id from pg_temp.create_expense_fixture(
 'f1200000-0000-0000-0000-000000000001','USD bill',100,'USD',6.7,'manual',
 '[{"participant_id":"f1300000-0000-0000-0000-000000000001","amount":"100"}]',
 '[{"participant_id":"f1300000-0000-0000-0000-000000000002","amount":"100"}]','{}','2026-09-20 09:00:00+08',null,null);
select expense_id from pg_temp.create_expense_fixture(
 'f1200000-0000-0000-0000-000000000001','CNY bill',100,'CNY',1,'manual',
 '[{"participant_id":"f1300000-0000-0000-0000-000000000001","amount":"100"}]',
 '[{"participant_id":"f1300000-0000-0000-0000-000000000002","amount":"100"}]','{}','2026-09-20 10:00:00+08',null,null);

select ok(
  (select count(*)=2 and sum(original_amount) filter(where currency='USD')=100 and sum(original_amount) filter(where currency='CNY')=100
   from public.list_settlement_options('f1000000-0000-0000-0000-000000000001')),
  'options expose only the directed debt currencies');

-- A multi-party Expense must split its original amount across debt rows rather
-- than copying the full bill amount into every row.
select expense_id from pg_temp.create_expense_fixture(
 'f1200000-0000-0000-0000-000000000001','Multi debt bill',90,'USD',6.7,'manual',
 '[{"participant_id":"f1300000-0000-0000-0000-000000000003","amount":"90"}]',
 '[{"participant_id":"f1300000-0000-0000-0000-000000000001","amount":"45"},{"participant_id":"f1300000-0000-0000-0000-000000000002","amount":"45"}]','{}','2026-09-20 10:30:00+08',null,null);
select ok(
 (select count(*)=2 and sum(original_amount)=90 from public.expense_debts where expense_id=(select id from public.expenses where title='Multi debt bill')),
 'multi-party debt rows conserve the bill original amount');

-- External settlement is capped and allocated in the same currency only.
with x as (select * from pg_temp.create_settlement_transfer_fixture(
 'f1000000-0000-0000-0000-000000000001','f1300000-0000-0000-0000-000000000002','f1300000-0000-0000-0000-000000000001',
 50,'USD','2026-09-20 11:00:00+08',null,'f1400000-0000-0000-0000-000000000001'))
insert into phase11_ids select 'usd50', transfer_id from x;
select ok(
 (select original_amount=50 and amount=335 from public.bilateral_debts where activity_id='f1000000-0000-0000-0000-000000000001' and currency='USD' and debtor_participant_id='f1300000-0000-0000-0000-000000000002' and creditor_participant_id='f1300000-0000-0000-0000-000000000001')
 and (select sum(original_amount)=50 and sum(base_amount)=335 from public.transfer_allocations where transfer_id=(select object_id from phase11_ids where label='usd50')),
 'USD settlement consumes USD and records original/base allocation');

-- Base settlement may consume all currency buckets by base value.
with x as (select * from pg_temp.create_settlement_transfer_fixture(
 'f1000000-0000-0000-0000-000000000001','f1300000-0000-0000-0000-000000000002','f1300000-0000-0000-0000-000000000001',
 50,'CNY','2026-09-20 12:00:00+08',null,'f1400000-0000-0000-0000-000000000002'))
insert into phase11_ids select 'cny50', transfer_id from x;
select ok(
 (select original_amount=100 from public.bilateral_debts where activity_id='f1000000-0000-0000-0000-000000000001' and currency='CNY' and debtor_participant_id='f1300000-0000-0000-0000-000000000002' and creditor_participant_id='f1300000-0000-0000-0000-000000000001')
 and (select sum(base_amount)=50 from public.transfer_allocations where transfer_id=(select object_id from phase11_ids where label='cny50')),
 'base settlement consumes mixed-currency debts in stable FIFO order');

do $test$
begin
  begin
    perform * from pg_temp.create_settlement_transfer_fixture(
      'f1000000-0000-0000-0000-000000000001','f1300000-0000-0000-0000-000000000002','f1300000-0000-0000-0000-000000000001',
      1,'EUR',now(),null,'f1400000-0000-0000-0000-000000000003');
    raise exception 'unsupported settlement currency unexpectedly succeeded';
  exception when check_violation then null;
  end;
end;
$test$;

-- A reverse USD debt nets by original USD amount, not by differing snapshots.
select expense_id from pg_temp.create_expense_fixture(
 'f1200000-0000-0000-0000-000000000001','Reverse USD',20,'USD',6.9,'manual',
 '[{"participant_id":"f1300000-0000-0000-0000-000000000002","amount":"20"}]',
 '[{"participant_id":"f1300000-0000-0000-0000-000000000001","amount":"20"}]','{}','2026-09-20 13:00:00+08',null,null);
select ok(
 (select original_amount=22.5373 and amount=151 from public.bilateral_debts where activity_id='f1000000-0000-0000-0000-000000000001' and currency='USD' and debtor_participant_id='f1300000-0000-0000-0000-000000000002' and creditor_participant_id='f1300000-0000-0000-0000-000000000001'),
 'same-currency reverse debt nets original units without FX ghost debt');

-- Replaying a request id returns the same fact without incrementing the count.
select count(*) as before_count into temporary phase11_before from public.transfers;
with x as (select * from pg_temp.create_settlement_transfer_fixture(
 'f1000000-0000-0000-0000-000000000001','f1300000-0000-0000-0000-000000000002','f1300000-0000-0000-0000-000000000001',
  10,'USD','2026-09-20 14:00:00+08',null,'f1400000-0000-0000-0000-000000000004'))
insert into phase11_ids select 'usd10', transfer_id from x;
select * from pg_temp.create_settlement_transfer_fixture(
 'f1000000-0000-0000-0000-000000000001','f1300000-0000-0000-0000-000000000002','f1300000-0000-0000-0000-000000000001',
 10,'USD','2026-09-20 14:00:00+08',null,'f1400000-0000-0000-0000-000000000004');
select ok((select count(*)=(select before_count+1 from phase11_before) from public.transfers),'request id replay is idempotent');

do $test$
declare v_expense uuid;
begin
  select e.id into v_expense from public.expenses e where e.title='USD bill';
  begin
    perform * from public.delete_expense(v_expense);
    raise exception 'settled expense unexpectedly deleted';
  exception when check_violation then null;
  end;
end;
$test$;
select ok((select not is_deleted from public.expenses where title='USD bill'),'settled expense remains after rejected delete');

select ok(
  (select not has_function_privilege('anon','public.restore_expense(uuid)','EXECUTE')
      and not has_function_privilege('authenticated','public.restore_expense(uuid)','EXECUTE')
      and not has_function_privilege('service_role','public.restore_expense(uuid)','EXECUTE')
      and not has_function_privilege('authenticated','private.restore_expense_impl(uuid)','EXECUTE')
      and not has_function_privilege('service_role','private.restore_expense_impl(uuid)','EXECUTE')),
  'restore expense has no client or service entry point');

select * from extensions.finish();
rollback;
