\set ON_ERROR_STOP on

begin;

create extension if not exists pgtap with schema extensions;
select extensions.plan(1);

create function pg_temp.assert_true(p_condition boolean, p_message text)
returns void language plpgsql as $function$
begin
  if p_condition is not true then raise exception 'assertion failed: %', p_message; end if;
end;
$function$;

create function pg_temp.authenticate(p_user uuid) returns void language plpgsql as $function$
begin
  perform set_config('request.jwt.claims', json_build_object('sub',p_user,'role','authenticated')::text, true);
end;
$function$;

insert into auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
values
 ('00000000-0000-0000-0000-000000000000','f6300000-0000-0000-0000-000000000001','authenticated','authenticated','phase5.creator@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','f6300000-0000-0000-0000-000000000002','authenticated','authenticated','phase5.owner@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','f6300000-0000-0000-0000-000000000003','authenticated','authenticated','phase5.third@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','f6300000-0000-0000-0000-000000000004','authenticated','authenticated','phase5.outsider@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());

insert into public.activities(id,join_code,name,type,base_currency,created_by) values
 ('f6000000-0000-0000-0000-000000000001','96000001','Phase 5 normal','normal','CNY','f6300000-0000-0000-0000-000000000001'),
 ('f6000000-0000-0000-0000-000000000002','96000002','Phase 5 refund','normal','CNY','f6300000-0000-0000-0000-000000000001'),
 ('f6000000-0000-0000-0000-000000000003','96000003','Phase 5 large','large','CNY','f6300000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id)
select a.id,u.id from public.activities a cross join auth.users u
where a.id in ('f6000000-0000-0000-0000-000000000001','f6000000-0000-0000-0000-000000000002','f6000000-0000-0000-0000-000000000003')
and u.id in ('f6300000-0000-0000-0000-000000000001','f6300000-0000-0000-0000-000000000002','f6300000-0000-0000-0000-000000000003');
insert into public.ledger_units(id,activity_id,name,type) values
 ('f6100000-0000-0000-0000-000000000001','f6000000-0000-0000-0000-000000000001','normal','default'),
 ('f6100000-0000-0000-0000-000000000002','f6000000-0000-0000-0000-000000000002','refund','default'),
 ('f6100000-0000-0000-0000-000000000003','f6000000-0000-0000-0000-000000000003','root','root'),
 ('f6100000-0000-0000-0000-000000000004','f6000000-0000-0000-0000-000000000003','child','sub_activity');
insert into public.participants(id,activity_id,name,participant_order) values
 ('f6200000-0000-0000-0000-000000000011','f6000000-0000-0000-0000-000000000001','Custodian',0),('f6200000-0000-0000-0000-000000000012','f6000000-0000-0000-0000-000000000001','Owner',1),('f6200000-0000-0000-0000-000000000013','f6000000-0000-0000-0000-000000000001','Third',2),
 ('f6200000-0000-0000-0000-000000000021','f6000000-0000-0000-0000-000000000002','Refund custodian',0),('f6200000-0000-0000-0000-000000000022','f6000000-0000-0000-0000-000000000002','Refund owner',1),
 ('f6200000-0000-0000-0000-000000000031','f6000000-0000-0000-0000-000000000003','Large custodian',0),('f6200000-0000-0000-0000-000000000032','f6000000-0000-0000-0000-000000000003','Large owner',1);
insert into public.participant_claims(activity_id,participant_id,user_id) values
 ('f6000000-0000-0000-0000-000000000001','f6200000-0000-0000-0000-000000000011','f6300000-0000-0000-0000-000000000001'),('f6000000-0000-0000-0000-000000000001','f6200000-0000-0000-0000-000000000012','f6300000-0000-0000-0000-000000000002'),('f6000000-0000-0000-0000-000000000001','f6200000-0000-0000-0000-000000000013','f6300000-0000-0000-0000-000000000003'),
 ('f6000000-0000-0000-0000-000000000002','f6200000-0000-0000-0000-000000000021','f6300000-0000-0000-0000-000000000001'),('f6000000-0000-0000-0000-000000000002','f6200000-0000-0000-0000-000000000022','f6300000-0000-0000-0000-000000000002'),
 ('f6000000-0000-0000-0000-000000000003','f6200000-0000-0000-0000-000000000031','f6300000-0000-0000-0000-000000000001'),('f6000000-0000-0000-0000-000000000003','f6200000-0000-0000-0000-000000000032','f6300000-0000-0000-0000-000000000002');

set local role authenticated;
select pg_temp.authenticate('f6300000-0000-0000-0000-000000000001');
create temporary table phase5_ids(label text primary key, object_id uuid not null) on commit drop;

-- A new prepayment with no old debt is entirely a prepayment component.
with x as (select * from public.create_prepayment('f6000000-0000-0000-0000-000000000001','f6200000-0000-0000-0000-000000000012','f6200000-0000-0000-0000-000000000011',100,'2026-08-31 09:00+08',null))
insert into phase5_ids select 'normal_prepaid',transfer_id from x;
select pg_temp.assert_true(
 (select settlement_amount=0 and prepayment_amount=50 and currency='CNY' and financial_version=1 from public.create_prepayment('f6000000-0000-0000-0000-000000000003','f6200000-0000-0000-0000-000000000032','f6200000-0000-0000-0000-000000000031',50,'2026-08-31 09:01+08',null)),
 'large activity prepayment result');
select pg_temp.assert_true((select balance=100 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001'),'normal account balance');
select pg_temp.assert_true((select count(*)=1 from public.transfer_components where transfer_id=(select object_id from phase5_ids where label='normal_prepaid') and component_type='prepayment' and amount=100),'normal component');

-- Deterministic Usage consumes the owner-to-custodian ExpenseDebt, leaving no
-- normal debt until the prepayment is exhausted.
with x as (select * from public.create_expense('f6100000-0000-0000-0000-000000000001','first',60,'CNY',1,'manual','[{"participant_id":"f6200000-0000-0000-0000-000000000011","amount":"60"}]','[{"participant_id":"f6200000-0000-0000-0000-000000000012","amount":"60"}]','{}','2026-08-31 10:00+08',null,null)) insert into phase5_ids select 'first_expense',expense_id from x;
select pg_temp.assert_true((select balance=40 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001') and (select sum(amount)=60 from public.prepayment_usages where activity_id='f6000000-0000-0000-0000-000000000001') and not exists(select 1 from public.bilateral_debts where activity_id='f6000000-0000-0000-0000-000000000001'), 'usage must automatically consume the oldest eligible debt before bilateral debt');
with x as (select * from public.create_expense('f6100000-0000-0000-0000-000000000001','second',100,'CNY',1,'manual','[{"participant_id":"f6200000-0000-0000-0000-000000000011","amount":"100"}]','[{"participant_id":"f6200000-0000-0000-0000-000000000012","amount":"100"}]','{}','2026-08-31 11:00+08',null,null)) insert into phase5_ids select 'second_expense',expense_id from x;
select pg_temp.assert_true((select balance=0 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001') and exists(select 1 from public.bilateral_debts where activity_id='f6000000-0000-0000-0000-000000000001' and debtor_participant_id='f6200000-0000-0000-0000-000000000012' and creditor_participant_id='f6200000-0000-0000-0000-000000000011' and amount=60), 'insufficient prepayment must leave exactly the residual ordinary debt');

-- A prepayment first settles that existing direct debt, and only its remainder
-- becomes prepayment.  A fully consumed prepayment still remains type=prepayment.
with x as (select * from public.create_prepayment('f6000000-0000-0000-0000-000000000001','f6200000-0000-0000-0000-000000000012','f6200000-0000-0000-0000-000000000011',100,'2026-08-31 12:00+08',null)) insert into phase5_ids select 'mixed_prepaid',transfer_id from x;
select pg_temp.assert_true((select type='prepayment' and amount=100 from public.transfers where id=(select object_id from phase5_ids where label='mixed_prepaid')) and (select count(*)=2 from public.transfer_components where transfer_id=(select object_id from phase5_ids where label='mixed_prepaid')) and (select balance=40 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001'), 'prepayment must split settlement and prepayment components against old debt');

-- Custodian can return a partial or full available balance, but cannot exceed it
-- and returns do not settle an unrelated reverse ordinary debt.
with x as (select * from public.create_prepayment_return('f6000000-0000-0000-0000-000000000001','f6200000-0000-0000-0000-000000000012','f6200000-0000-0000-0000-000000000011',20,'2026-08-31 13:00+08',null)) insert into phase5_ids select 'partial_return',transfer_id from x;
select pg_temp.assert_true((select balance=20 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001') and (select type='prepayment_return' from public.transfers where id=(select object_id from phase5_ids where label='partial_return')), 'partial return must reduce only the available prepayment balance');
do $test$ begin begin perform public.create_prepayment_return('f6000000-0000-0000-0000-000000000001','f6200000-0000-0000-0000-000000000012','f6200000-0000-0000-0000-000000000011',21,now(),null); raise exception 'over-return succeeded'; exception when check_violation then null; end; end $test$;

select pg_temp.assert_true(voided, 'recorded prepayment return may be voided') from public.void_prepayment_transfer((select object_id from phase5_ids where label='partial_return'),'test correction');
select pg_temp.assert_true((select balance=40 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001'), 'void must rebuild available balance from immutable components');

-- Large-Activity balances are Activity scoped, not LedgerUnit scoped.
with x as (select * from public.create_expense('f6100000-0000-0000-0000-000000000004','child debt',30,'CNY',1,'manual','[{"participant_id":"f6200000-0000-0000-0000-000000000031","amount":"30"}]','[{"participant_id":"f6200000-0000-0000-0000-000000000032","amount":"30"}]','{}','2026-08-31 14:00+08',null,null)) insert into phase5_ids select 'large_child_expense',expense_id from x;
select pg_temp.assert_true((select balance=20 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000003') and not exists(select 1 from public.bilateral_debts where activity_id='f6000000-0000-0000-0000-000000000003'), 'large Activity prepayment must cover an eligible child-Activity debt');

-- Linked refund restores only the original Usage.  Amount beyond the restored
-- usage remains a normal negative Expense result.
with x as (select * from public.create_prepayment('f6000000-0000-0000-0000-000000000002','f6200000-0000-0000-0000-000000000022','f6200000-0000-0000-0000-000000000021',100,'2026-08-31 15:00+08',null)) insert into phase5_ids select 'refund_prepayment',transfer_id from x;
with x as (select * from public.create_expense('f6100000-0000-0000-0000-000000000002','original',50,'CNY',1,'manual','[{"participant_id":"f6200000-0000-0000-0000-000000000021","amount":"50"}]','[{"participant_id":"f6200000-0000-0000-0000-000000000022","amount":"50"}]','{}','2026-08-31 16:00+08',null,null)) insert into phase5_ids select 'refund_original',expense_id from x;
with x as (select * from public.create_expense('f6100000-0000-0000-0000-000000000002','partial refund',-20,'CNY',1,'manual','[{"participant_id":"f6200000-0000-0000-0000-000000000021","amount":"-20"}]','[{"participant_id":"f6200000-0000-0000-0000-000000000022","amount":"-20"}]','{}','2026-08-31 17:00+08',null,(select object_id from phase5_ids where label='refund_original'))) insert into phase5_ids select 'linked_refund',expense_id from x;
select pg_temp.assert_true((select balance=70 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000002') and (select amount=30 and gross_amount=50 from public.prepayment_usages where activity_id='f6000000-0000-0000-0000-000000000002'), 'linked refund must restore only original actual Usage');

-- Projection facts are member-readable but never client-writable; anonymous
-- callers have no RPC entry point, and full rebuild remains service-role only.
reset role;
select pg_temp.assert_true(not has_table_privilege('authenticated','public.transfer_components','INSERT') and not has_table_privilege('authenticated','public.prepayment_accounts','UPDATE') and not has_table_privilege('anon','public.prepayment_usages','SELECT') and not has_function_privilege('anon','public.create_prepayment(uuid,uuid,uuid,numeric,timestamptz,uuid)','EXECUTE') and has_function_privilege('service_role','private.rebuild_activity_debt_projection(uuid)','EXECUTE'), 'Phase 5 projection DML/RPC privileges must preserve the definer boundary');

set local role authenticated; select pg_temp.authenticate('f6300000-0000-0000-0000-000000000004');
select pg_temp.assert_true((select count(*)=0 from public.transfer_components) and (select count(*)=0 from public.prepayment_accounts) and (select count(*)=0 from public.prepayment_usages), 'outsider RLS must hide all Phase 5 projections');
select pass('Phase 5 baseline behavior assertions');
select * from extensions.finish();

rollback;
