\set ON_ERROR_STOP on

begin;
create extension if not exists pgtap with schema extensions;
select extensions.plan(14);

create function pg_temp.authenticate(p_user uuid) returns void language plpgsql as $function$
begin
  perform set_config('request.jwt.claims',json_build_object('sub',p_user,'role','authenticated')::text,true);
end;
$function$;

insert into auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
values
 ('00000000-0000-0000-0000-000000000000','e5100000-0000-0000-0000-000000000001','authenticated','authenticated','u03.a@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','e5100000-0000-0000-0000-000000000002','authenticated','authenticated','u03.b@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());

insert into public.activities(id,join_code,name,type,base_currency,multi_currency_enabled,created_by) values
 ('e5000000-0000-0000-0000-000000000001','95000101','U03 repayment','normal','CNY',true,'e5100000-0000-0000-0000-000000000001'),
 ('e5000000-0000-0000-0000-000000000002','95000102','U03 prepayment return','normal','CNY',true,'e5100000-0000-0000-0000-000000000001'),
 ('e5000000-0000-0000-0000-000000000003','95000103','U03 final ordinary','normal','CNY',true,'e5100000-0000-0000-0000-000000000001'),
 ('e5000000-0000-0000-0000-000000000004','95000104','U03 final return','normal','CNY',true,'e5100000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id)
select a.id,u.id from public.activities a cross join auth.users u
where a.id::text like 'e5000000-0000-0000-0000-00000000000%'
  and u.id in ('e5100000-0000-0000-0000-000000000001','e5100000-0000-0000-0000-000000000002');
insert into public.ledger_units(id,activity_id,name,type) values
 ('e5200000-0000-0000-0000-000000000001','e5000000-0000-0000-0000-000000000001','default','default'),
 ('e5200000-0000-0000-0000-000000000002','e5000000-0000-0000-0000-000000000002','default','default'),
 ('e5200000-0000-0000-0000-000000000003','e5000000-0000-0000-0000-000000000003','default','default'),
 ('e5200000-0000-0000-0000-000000000004','e5000000-0000-0000-0000-000000000004','default','default');
insert into public.participants(id,activity_id,name,participant_order) values
 ('e5300000-0000-0000-0000-000000000001','e5000000-0000-0000-0000-000000000001','A',0),
 ('e5300000-0000-0000-0000-000000000002','e5000000-0000-0000-0000-000000000001','B',1),
 ('e5300000-0000-0000-0000-000000000003','e5000000-0000-0000-0000-000000000002','A',0),
 ('e5300000-0000-0000-0000-000000000004','e5000000-0000-0000-0000-000000000002','B',1),
 ('e5300000-0000-0000-0000-000000000005','e5000000-0000-0000-0000-000000000003','A',0),
 ('e5300000-0000-0000-0000-000000000006','e5000000-0000-0000-0000-000000000003','B',1),
 ('e5300000-0000-0000-0000-000000000007','e5000000-0000-0000-0000-000000000004','A',0),
 ('e5300000-0000-0000-0000-000000000008','e5000000-0000-0000-0000-000000000004','B',1);
insert into public.participant_claims(activity_id,participant_id,user_id) values
 ('e5000000-0000-0000-0000-000000000001','e5300000-0000-0000-0000-000000000001','e5100000-0000-0000-0000-000000000001'),
 ('e5000000-0000-0000-0000-000000000001','e5300000-0000-0000-0000-000000000002','e5100000-0000-0000-0000-000000000002'),
 ('e5000000-0000-0000-0000-000000000002','e5300000-0000-0000-0000-000000000003','e5100000-0000-0000-0000-000000000001'),
 ('e5000000-0000-0000-0000-000000000002','e5300000-0000-0000-0000-000000000004','e5100000-0000-0000-0000-000000000002'),
 ('e5000000-0000-0000-0000-000000000003','e5300000-0000-0000-0000-000000000005','e5100000-0000-0000-0000-000000000001'),
 ('e5000000-0000-0000-0000-000000000003','e5300000-0000-0000-0000-000000000006','e5100000-0000-0000-0000-000000000002'),
 ('e5000000-0000-0000-0000-000000000004','e5300000-0000-0000-0000-000000000007','e5100000-0000-0000-0000-000000000001'),
 ('e5000000-0000-0000-0000-000000000004','e5300000-0000-0000-0000-000000000008','e5100000-0000-0000-0000-000000000002');

set local role service_role;
select * from public.replace_exchange_rate_cache('2026-09-23','{"EUR":"1","USD":"1.25","CNY":"7.10","JPY":"170.00","GBP":"0.86"}'::jsonb);
reset role;

create temporary table u03_ids(label text primary key,id uuid not null) on commit drop;
grant select,insert,update,delete on u03_ids to authenticated,service_role;
create temporary table u03_final_results(label text primary key,transfer_id uuid,amount numeric,currency character(3),mode text) on commit drop;
grant select,insert,update,delete on u03_final_results to authenticated,service_role;

set local role authenticated;
select pg_temp.authenticate('e5100000-0000-0000-0000-000000000001');
with x as (select * from public.create_expense_auto_rate('e5200000-0000-0000-0000-000000000001','FIFO USD debt',20,'USD','manual','[{"participant_id":"e5300000-0000-0000-0000-000000000001","amount":"20"}]','[{"participant_id":"e5300000-0000-0000-0000-000000000002","amount":"20"}]','{}',now(),null,null,'money'))
insert into u03_ids values('fifo_expense',(select expense_id from x));
with x as (select * from public.create_expense_auto_rate('e5200000-0000-0000-0000-000000000001','target USD debt',20,'USD','manual','[{"participant_id":"e5300000-0000-0000-0000-000000000001","amount":"20"}]','[{"participant_id":"e5300000-0000-0000-0000-000000000002","amount":"20"}]','{}',now(),null,null,'money'))
insert into u03_ids values('target_expense',(select expense_id from x));
with x as (select * from public.create_expense_auto_rate('e5200000-0000-0000-0000-000000000001','refund USD parent',20,'USD','manual','[{"participant_id":"e5300000-0000-0000-0000-000000000001","amount":"20"}]','[{"participant_id":"e5300000-0000-0000-0000-000000000002","amount":"20"}]','{}',now(),null,null,'money'))
insert into u03_ids values('refund_parent',(select expense_id from x));
with x as (select * from public.create_expense_auto_rate('e5200000-0000-0000-0000-000000000003','final USD debt',20,'USD','manual','[{"participant_id":"e5300000-0000-0000-0000-000000000005","amount":"20"}]','[{"participant_id":"e5300000-0000-0000-0000-000000000006","amount":"20"}]','{}',now(),null,null,'money'))
insert into u03_ids values('final_expense',(select expense_id from x));
with x as (select * from public.create_prepayment_v2('e5000000-0000-0000-0000-000000000002','e5300000-0000-0000-0000-000000000003','e5300000-0000-0000-0000-000000000004',20,'USD',now(),null,(select financial_version from public.activities where id='e5000000-0000-0000-0000-000000000002'),'e5400000-0000-0000-0000-000000000001'))
insert into u03_ids values('return_deposit',(select transfer_id from x));
with x as (select * from public.create_prepayment_v2('e5000000-0000-0000-0000-000000000004','e5300000-0000-0000-0000-000000000007','e5300000-0000-0000-0000-000000000008',20,'USD',now(),null,(select financial_version from public.activities where id='e5000000-0000-0000-0000-000000000004'),'e5400000-0000-0000-0000-000000000002'))
insert into u03_ids values('final_return_deposit',(select transfer_id from x));

reset role;
set local role service_role;
update public.activities set multi_currency_enabled=false where id in (
 'e5000000-0000-0000-0000-000000000001','e5000000-0000-0000-0000-000000000002',
 'e5000000-0000-0000-0000-000000000003','e5000000-0000-0000-0000-000000000004');
reset role;
set local role authenticated;
select pg_temp.authenticate('e5100000-0000-0000-0000-000000000002');

select extensions.ok((select count(*)=4 and bool_and(not multi_currency_enabled) from public.activities where id::text like 'e5000000-0000-0000-0000-00000000000%'),
  'all four fixtures disable new foreign-currency facts after creating historical USD records');

with x as (select * from public.create_expense_repayment_v2('e5000000-0000-0000-0000-000000000001','e5300000-0000-0000-0000-000000000002','e5300000-0000-0000-0000-000000000001',5,'USD','FIFO',null,now(),null,(select financial_version from public.activities where id='e5000000-0000-0000-0000-000000000001'),'e5400000-0000-0000-0000-000000000003'))
insert into u03_ids values('fifo_transfer',(select transfer_id from x));
select extensions.ok((select count(*)=1 and sum(ta.original_amount)=5
  from public.transfer_allocations ta join public.expense_debts ed on ed.id=ta.expense_debt_id
  join public.expenses e on e.id=ed.expense_id
  where ta.transfer_id=(select id from u03_ids where label='fifo_transfer') and e.original_currency='USD'),
  'existing foreign debt remains payable through the ordinary FIFO v2 path');

with x as (select * from public.create_expense_repayment_v2('e5000000-0000-0000-0000-000000000001','e5300000-0000-0000-0000-000000000002','e5300000-0000-0000-0000-000000000001',5,'USD','TARGETED',array[(select id from u03_ids where label='target_expense')],now(),null,(select financial_version from public.activities where id='e5000000-0000-0000-0000-000000000001'),'e5400000-0000-0000-0000-000000000004'))
insert into u03_ids values('target_transfer',(select transfer_id from x));
select extensions.ok((select count(*)=1 and bool_and(ed.expense_id=(select id from u03_ids where label='target_expense') and ta.original_amount=5 and e.original_currency='USD')
  from public.transfer_allocations ta join public.expense_debts ed on ed.id=ta.expense_debt_id join public.expenses e on e.id=ed.expense_id
  where ta.transfer_id=(select id from u03_ids where label='target_transfer')),
  'existing foreign debt remains payable through the targeted v2 path');

select extensions.ok((select remaining_balance=15 and currency='USD' from public.create_prepayment_return_v2(
  'e5000000-0000-0000-0000-000000000002','e5300000-0000-0000-0000-000000000003','e5300000-0000-0000-0000-000000000004',5,'USD',now(),null,
  (select financial_version from public.activities where id='e5000000-0000-0000-0000-000000000002'),'e5400000-0000-0000-0000-000000000005')),
  'an existing foreign prepayment account can still be returned');

do $final_ordinary$
declare v record; r record;
begin
  select * into v from public.preview_final_settlement_v2('e5000000-0000-0000-0000-000000000003','original_currency')
   where currency='USD' and not is_prepayment_return;
  if not found then raise exception 'historical USD final ordinary plan was missing'; end if;
  select * into r from public.execute_final_settlement_v2(v.activity_id,v.from_participant_id,v.to_participant_id,
    v.amount,v.currency,v.mode,v.source_financial_version,'e5400000-0000-0000-0000-000000000006',now(),null);
  insert into u03_final_results values('ordinary',r.transfer_id,r.amount,r.currency,r.mode);
end;
$final_ordinary$;
select extensions.ok((select amount=20 and currency='USD' and mode='original_currency' from u03_final_results where label='ordinary')
 and (select count(*)=1 and sum(original_amount)=20 and bool_and(path_currency='USD') from public.final_settlement_paths where transfer_id=(select transfer_id from u03_final_results where label='ordinary')),
 'existing foreign debt can be finalized in its original currency after multi-currency is disabled');

do $final_return$
declare v record; r record;
begin
  select * into v from public.preview_final_settlement_v2('e5000000-0000-0000-0000-000000000004','original_currency')
   where is_prepayment_return;
  if not found then raise exception 'historical USD final return plan was missing'; end if;
  select * into r from public.execute_final_settlement_v2(v.activity_id,v.from_participant_id,v.to_participant_id,
    v.amount,v.currency,v.mode,v.source_financial_version,'e5400000-0000-0000-0000-000000000007',now(),null);
  insert into u03_final_results values('return',r.transfer_id,r.amount,r.currency,r.mode);
end;
$final_return$;
select extensions.ok((select amount=20 and currency='USD' from u03_final_results where label='return')
 and (select count(*)=1 and bool_and(component_type='prepayment_return' and amount=20) from public.transfer_components where transfer_id=(select transfer_id from u03_final_results where label='return')),
 'an existing foreign prepayment can be returned through the final-settlement path');

select extensions.throws_ok($$select * from public.create_expense_auto_rate(
  'e5200000-0000-0000-0000-000000000001','new USD debt after disable',1,'USD','manual',
  '[{"participant_id":"e5300000-0000-0000-0000-000000000001","amount":"1"}]',
  '[{"participant_id":"e5300000-0000-0000-0000-000000000002","amount":"1"}]','{}',now(),null,null,'money')$$,
  '22023',null,'new foreign Expense creation remains disabled');
select extensions.throws_ok($$select * from public.create_prepayment_v2(
  'e5000000-0000-0000-0000-000000000001','e5300000-0000-0000-0000-000000000001','e5300000-0000-0000-0000-000000000002',
  1,'USD',now(),null,(select financial_version from public.activities where id='e5000000-0000-0000-0000-000000000001'),'e5400000-0000-0000-0000-000000000008')$$,
  '22023',null,'new foreign Prepayment creation remains disabled');

select pg_temp.authenticate('e5100000-0000-0000-0000-000000000001');
with x as (select * from public.create_expense_auto_rate('e5200000-0000-0000-0000-000000000001','linked refund after disable',-1,'USD','manual',
  '[{"participant_id":"e5300000-0000-0000-0000-000000000001","amount":"-1"}]',
  '[{"participant_id":"e5300000-0000-0000-0000-000000000002","amount":"-1"}]','{}',now(),null,
  (select id from u03_ids where label='refund_parent'),'money'))
insert into u03_ids values('refund',(select expense_id from x));
select extensions.ok((select r.original_amount=-1 and r.fx_rate=p.fx_rate and r.fx_rate_source=p.fx_rate_source and r.fx_rate_observed_at=p.fx_rate_observed_at
  from public.expenses r join public.expenses p on p.id=r.original_expense_id where r.id=(select id from u03_ids where label='refund')),
  'a linked refund of an existing foreign Expense inherits its complete FX snapshot after the flag is disabled');
select extensions.throws_ok($$select * from public.create_expense_auto_rate(
  'e5200000-0000-0000-0000-000000000001','refund with missing USD parent',-1,'USD','manual',
  '[{"participant_id":"e5300000-0000-0000-0000-000000000001","amount":"-1"}]',
  '[{"participant_id":"e5300000-0000-0000-0000-000000000002","amount":"-1"}]','{}',now(),null,
  'e5300000-0000-0000-0000-000000000099','money')$$,
  '22023',null,'a linked refund still requires a valid parent after the flag is disabled');

select pg_temp.authenticate('e5100000-0000-0000-0000-000000000002');
select * from public.void_prepayment_transfer((select id from u03_ids where label='fifo_transfer'),'U03 post-disable void');
select extensions.ok((select is_voided from public.transfers where id=(select id from u03_ids where label='fifo_transfer')),
  'a pre-existing foreign-currency settlement can be voided after the flag is disabled');

reset role;
set local role service_role;
select private.rebuild_activity_debt_projection('e5000000-0000-0000-0000-000000000001');
select private.rebuild_activity_debt_projection('e5000000-0000-0000-0000-000000000002');
select private.rebuild_activity_debt_projection('e5000000-0000-0000-0000-000000000003');
select private.rebuild_activity_debt_projection('e5000000-0000-0000-0000-000000000004');
reset role;
set local role authenticated;
select extensions.ok(exists(select 1 from public.bilateral_debts
  where activity_id='e5000000-0000-0000-0000-000000000001' and currency='USD' and original_amount>0),
  'explicit rebuild retains historical USD debt projection after the flag is disabled');
select extensions.ok((select balance=15 and currency='USD' from public.prepayment_accounts
  where activity_id='e5000000-0000-0000-0000-000000000002'
    and owner_participant_id='e5300000-0000-0000-0000-000000000003'
    and custodian_participant_id='e5300000-0000-0000-0000-000000000004'),
  'explicit rebuild retains historical USD prepayment balance after the flag is disabled');
select extensions.ok(exists(select 1 from public.final_settlement_paths
    where transfer_id=(select transfer_id from u03_final_results where label='ordinary') and path_currency='USD' and original_amount=20)
  and exists(select 1 from public.transfer_components
    where transfer_id=(select transfer_id from u03_final_results where label='return') and component_type='prepayment_return' and amount=20),
  'explicit rebuild preserves both historical foreign Final Settlement sources');

select * from extensions.finish();
rollback;
