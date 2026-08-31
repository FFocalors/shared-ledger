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

-- Extended Phase 5 coverage: old-debt-only funding, reverse debt isolation,
-- linked refund excess and cumulative caps, expense update/delete rebuilds,
-- prepayment/return/settlement voids, archived and actor authorization,
-- full rebuild invariants, financial_version, RLS and direct-DML boundaries.
select pg_temp.authenticate('f6300000-0000-0000-0000-000000000001');
select pg_temp.assert_true(
 (select count(*)=1 from public.transfer_components where transfer_id=(select object_id from phase5_ids where label='mixed_prepaid') and component_type='settlement' and amount=60)
 and (select count(*)=1 from public.transfer_components where transfer_id=(select object_id from phase5_ids where label='mixed_prepaid') and component_type='prepayment' and amount=40),
 'prepayment against existing debt emits exact settlement and residual components');
-- Reverse ordinary debt is never consumed by owner->custodian Usage.
select pg_temp.assert_true(
  not exists(select 1 from public.prepayment_usages pu join public.expense_debts ed on ed.id=pu.expense_debt_id
    where ed.debtor_participant_id='f6200000-0000-0000-0000-000000000021' and ed.creditor_participant_id='f6200000-0000-0000-0000-000000000022'),
  'reverse ordinary debt does not consume the account');

-- Two linked refunds cumulatively restore at most the original gross Usage;
-- excess becomes a reverse debt and never creates duplicate account Usage.
with x as (select * from public.create_expense('f6100000-0000-0000-0000-000000000002','refund excess',-40,'CNY',1,'manual','[{"participant_id":"f6200000-0000-0000-0000-000000000021","amount":"-40"}]','[{"participant_id":"f6200000-0000-0000-0000-000000000022","amount":"-40"}]','{}','2026-08-31 18:00+08',null,(select object_id from phase5_ids where label='refund_original'))) insert into phase5_ids select 'refund_excess',expense_id from x;
select pg_temp.assert_true((select exists(select 1 from public.expenses where id=(select object_id from phase5_ids where label='refund_excess') and original_expense_id=(select object_id from phase5_ids where label='refund_original') and base_amount=-40)), 'linked refund excess is persisted');
with x as (select * from public.create_expense('f6100000-0000-0000-0000-000000000002','refund second',-20,'CNY',1,'manual','[{"participant_id":"f6200000-0000-0000-0000-000000000021","amount":"-20"}]','[{"participant_id":"f6200000-0000-0000-0000-000000000022","amount":"-20"}]','{}','2026-08-31 19:00+08',null,(select object_id from phase5_ids where label='refund_original'))) insert into phase5_ids select 'refund_second',expense_id from x;
select pg_temp.assert_true((select exists(select 1 from public.expenses where id=(select object_id from phase5_ids where label='refund_second') and original_expense_id=(select object_id from phase5_ids where label='refund_original') and base_amount=-20)), 'second linked refund is persisted');
select pg_temp.assert_true(
  (select coalesce(sum(pu.amount),0)=0 from public.prepayment_usages pu where pu.activity_id='f6000000-0000-0000-0000-000000000002')
  and (select count(*)=1 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000002')
  and exists(select 1 from public.bilateral_debts where activity_id='f6000000-0000-0000-0000-000000000002' and amount=30),
  'linked refund excess and multi-refund cap produce reverse debt once');

-- update_expense and delete_expense must rebuild projections without changing
-- immutable transfer/components facts.
select count(*) into temporary table phase5_fact_count from public.transfers where activity_id='f6000000-0000-0000-0000-000000000002';
select pg_temp.assert_true((select count(*)=1 from public.update_expense(
 (select object_id from phase5_ids where label='refund_original'),'f6100000-0000-0000-0000-000000000002','original edited',50,'CNY',1,'manual',
 '[{"participant_id":"f6200000-0000-0000-0000-000000000021","amount":"50"}]','[{"participant_id":"f6200000-0000-0000-0000-000000000022","amount":"50"}]','{}', '2026-08-31 16:00+08',null,null)), 'update_expense rebuilds Usage/account/debt');
select pg_temp.assert_true((select count(*)=(select count from phase5_fact_count) from public.transfers where activity_id='f6000000-0000-0000-0000-000000000002'), 'expense update leaves transfer facts unchanged');
select pg_temp.assert_true((select count(*)=1 from public.delete_expense((select object_id from phase5_ids where label='linked_refund'))), 'delete_expense rebuilds and removes linked refund restoration');
select pg_temp.assert_true((select count(*)=(select count from phase5_fact_count) from public.transfers where activity_id='f6000000-0000-0000-0000-000000000002'), 'expense delete leaves transfer/components unchanged');

-- Void both a prepayment deposit and a return; a negative funding rebuild must
-- fail atomically when an active return remains.
do $void$ declare tid uuid; begin
 select object_id into tid from phase5_ids where label='refund_prepayment';
 perform * from public.void_prepayment_transfer(tid,'void deposit');
end $void$;
select pg_temp.assert_true(not exists(select 1 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000002'), 'void prepayment deposit rebuilds account');
do $negative$ begin begin
  perform * from public.create_prepayment_return('f6000000-0000-0000-0000-000000000002','f6200000-0000-0000-0000-000000000022','f6200000-0000-0000-0000-000000000021',1,now(),null);
  raise exception 'negative funding return unexpectedly succeeded';
exception when check_violation then null; end; end $negative$;

-- Full rebuild must preserve all projections and financial_version.
select financial_version into temporary table phase5_version from public.activities where id='f6000000-0000-0000-0000-000000000001';
create temporary table phase5_before_expense_debts on commit drop as
 select ledger_unit_id,expense_id,debtor_participant_id,creditor_participant_id,amount from public.expense_debts where activity_id='f6000000-0000-0000-0000-000000000001';
create temporary table phase5_before_allocations on commit drop as
 select ta.transfer_id,ta.settlement_component_id,ed.expense_id,ed.debtor_participant_id,ed.creditor_participant_id,ta.amount from public.transfer_allocations ta join public.expense_debts ed on ed.id=ta.expense_debt_id where ta.activity_id='f6000000-0000-0000-0000-000000000001';
create temporary table phase5_before_usages on commit drop as
 select ed.expense_id,pa.owner_participant_id,pa.custodian_participant_id,pu.gross_amount,pu.amount from public.prepayment_usages pu join public.expense_debts ed on ed.id=pu.expense_debt_id join public.prepayment_accounts pa on pa.id=pu.account_id where pu.activity_id='f6000000-0000-0000-0000-000000000001';
create temporary table phase5_before_accounts on commit drop as
 select owner_participant_id,custodian_participant_id,balance from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001';
create temporary table phase5_before_bilateral on commit drop as
 select debtor_participant_id,creditor_participant_id,amount from public.bilateral_debts where activity_id='f6000000-0000-0000-0000-000000000001';
create temporary table phase5_before_components on commit drop as
 select transfer_id,component_type,amount from public.transfer_components where activity_id='f6000000-0000-0000-0000-000000000001';
reset role; set local role service_role;
select private.rebuild_activity_debt_projection('f6000000-0000-0000-0000-000000000001');
reset role; set local role authenticated; select pg_temp.authenticate('f6300000-0000-0000-0000-000000000001');
select 'rebuild-diff' as diagnostic,
 exists ((select ledger_unit_id,expense_id,debtor_participant_id,creditor_participant_id,amount from public.expense_debts where activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_expense_debts) as ed_add,
 exists (select * from phase5_before_expense_debts except (select ledger_unit_id,expense_id,debtor_participant_id,creditor_participant_id,amount from public.expense_debts where activity_id='f6000000-0000-0000-0000-000000000001')) as ed_del,
 exists ((select ed.expense_id,pa.owner_participant_id,pa.custodian_participant_id,pu.gross_amount,pu.amount from public.prepayment_usages pu join public.expense_debts ed on ed.id=pu.expense_debt_id join public.prepayment_accounts pa on pa.id=pu.account_id where pu.activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_usages) as use_add,
 exists (select * from phase5_before_usages except (select ed.expense_id,pa.owner_participant_id,pa.custodian_participant_id,pu.gross_amount,pu.amount from public.prepayment_usages pu join public.expense_debts ed on ed.id=pu.expense_debt_id join public.prepayment_accounts pa on pa.id=pu.account_id where pu.activity_id='f6000000-0000-0000-0000-000000000001')) as use_del,
 exists ((select owner_participant_id,custodian_participant_id,balance from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_accounts) as acc_add,
 exists (select * from phase5_before_accounts except (select owner_participant_id,custodian_participant_id,balance from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001')) as acc_del;
select pg_temp.assert_true(not exists ((select ledger_unit_id,expense_id,debtor_participant_id,creditor_participant_id,amount from public.expense_debts where activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_expense_debts) and not exists (select * from phase5_before_expense_debts except (select ledger_unit_id,expense_id,debtor_participant_id,creditor_participant_id,amount from public.expense_debts where activity_id='f6000000-0000-0000-0000-000000000001')), 'rebuild expense_debts exact');
select pg_temp.assert_true(not exists ((select ta.transfer_id,ta.settlement_component_id,ed.expense_id,ed.debtor_participant_id,ed.creditor_participant_id,ta.amount from public.transfer_allocations ta join public.expense_debts ed on ed.id=ta.expense_debt_id where ta.activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_allocations) and not exists (select * from phase5_before_allocations except (select ta.transfer_id,ta.settlement_component_id,ed.expense_id,ed.debtor_participant_id,ed.creditor_participant_id,ta.amount from public.transfer_allocations ta join public.expense_debts ed on ed.id=ta.expense_debt_id where ta.activity_id='f6000000-0000-0000-0000-000000000001')), 'rebuild transfer_allocations exact');
select pg_temp.assert_true(not exists ((select ed.expense_id,pa.owner_participant_id,pa.custodian_participant_id,pu.gross_amount,pu.amount from public.prepayment_usages pu join public.expense_debts ed on ed.id=pu.expense_debt_id join public.prepayment_accounts pa on pa.id=pu.account_id where pu.activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_usages) and not exists (select * from phase5_before_usages except (select ed.expense_id,pa.owner_participant_id,pa.custodian_participant_id,pu.gross_amount,pu.amount from public.prepayment_usages pu join public.expense_debts ed on ed.id=pu.expense_debt_id join public.prepayment_accounts pa on pa.id=pu.account_id where pu.activity_id='f6000000-0000-0000-0000-000000000001')), 'rebuild prepayment_usages exact');
select pg_temp.assert_true(not exists ((select owner_participant_id,custodian_participant_id,balance from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_accounts) and not exists (select * from phase5_before_accounts except (select owner_participant_id,custodian_participant_id,balance from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001')), 'rebuild prepayment_accounts exact');
select pg_temp.assert_true(
 (select financial_version=(select financial_version from phase5_version) from public.activities where id='f6000000-0000-0000-0000-000000000001')
 and not exists ((select ledger_unit_id,expense_id,debtor_participant_id,creditor_participant_id,amount from public.expense_debts where activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_expense_debts)
 and not exists (select * from phase5_before_expense_debts except (select ledger_unit_id,expense_id,debtor_participant_id,creditor_participant_id,amount from public.expense_debts where activity_id='f6000000-0000-0000-0000-000000000001'))
 and not exists ((select ta.transfer_id,ta.settlement_component_id,ed.expense_id,ed.debtor_participant_id,ed.creditor_participant_id,ta.amount from public.transfer_allocations ta join public.expense_debts ed on ed.id=ta.expense_debt_id where ta.activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_allocations)
 and not exists (select * from phase5_before_allocations except (select ta.transfer_id,ta.settlement_component_id,ed.expense_id,ed.debtor_participant_id,ed.creditor_participant_id,ta.amount from public.transfer_allocations ta join public.expense_debts ed on ed.id=ta.expense_debt_id where ta.activity_id='f6000000-0000-0000-0000-000000000001'))
 and not exists ((select ed.expense_id,pa.owner_participant_id,pa.custodian_participant_id,pu.gross_amount,pu.amount from public.prepayment_usages pu join public.expense_debts ed on ed.id=pu.expense_debt_id join public.prepayment_accounts pa on pa.id=pu.account_id where pu.activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_usages)
 and not exists (select * from phase5_before_usages except (select ed.expense_id,pa.owner_participant_id,pa.custodian_participant_id,pu.gross_amount,pu.amount from public.prepayment_usages pu join public.expense_debts ed on ed.id=pu.expense_debt_id join public.prepayment_accounts pa on pa.id=pu.account_id where pu.activity_id='f6000000-0000-0000-0000-000000000001'))
 and not exists ((select owner_participant_id,custodian_participant_id,balance from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_accounts)
 and not exists (select * from phase5_before_accounts except (select owner_participant_id,custodian_participant_id,balance from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000001'))
 and not exists ((select debtor_participant_id,creditor_participant_id,amount from public.bilateral_debts where activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_bilateral)
 and not exists (select * from phase5_before_bilateral except (select debtor_participant_id,creditor_participant_id,amount from public.bilateral_debts where activity_id='f6000000-0000-0000-0000-000000000001'))
 and not exists ((select transfer_id,component_type,amount from public.transfer_components where activity_id='f6000000-0000-0000-0000-000000000001') except select * from phase5_before_components)
 and not exists (select * from phase5_before_components except (select transfer_id,component_type,amount from public.transfer_components where activity_id='f6000000-0000-0000-0000-000000000001')),
 'full rebuild preserves every projection fact and financial_version');

-- archived, creator proxy, claimed member, anon/outsider rejection and
-- financial_version success/failure/no-op semantics.
update public.activities set archived_at=now() where id='f6000000-0000-0000-0000-000000000001';
do $archived$ begin begin perform * from public.create_prepayment('f6000000-0000-0000-0000-000000000001','f6200000-0000-0000-0000-000000000012','f6200000-0000-0000-0000-000000000011',1,now(),null); raise exception 'archived write succeeded'; exception when sqlstate '55000' then null; end; end $archived$;
update public.activities set archived_at=null where id='f6000000-0000-0000-0000-000000000001';
-- Verify creator proxy is a real transfer fact, then verify a claimed member
-- cannot forge the proxy field.
reset role; set local role service_role;
delete from public.participant_claims where activity_id='f6000000-0000-0000-0000-000000000001' and participant_id='f6200000-0000-0000-0000-000000000013';
set local role authenticated; select pg_temp.authenticate('f6300000-0000-0000-0000-000000000001');
with x as (select * from public.create_prepayment('f6000000-0000-0000-0000-000000000001','f6200000-0000-0000-0000-000000000013','f6200000-0000-0000-0000-000000000011',5,now(),'f6200000-0000-0000-0000-000000000013'))
insert into phase5_ids select 'proxy_transfer',transfer_id from x;
grant select on phase5_ids to service_role;
reset role; set local role service_role;
select pg_temp.assert_true((select t.recorded_by='f6300000-0000-0000-0000-000000000001' and t.on_behalf_of_participant_id='f6200000-0000-0000-0000-000000000013' from public.transfers t where t.id=(select object_id from phase5_ids where label='proxy_transfer')), 'creator proxy records recorded_by and on_behalf_of');
set local role authenticated; select pg_temp.authenticate('f6300000-0000-0000-0000-000000000001');
do $proxy$ begin begin perform public.create_prepayment('f6000000-0000-0000-0000-000000000001','f6200000-0000-0000-0000-000000000012','f6200000-0000-0000-0000-000000000011',1,now(),'f6200000-0000-0000-0000-000000000013'); raise exception 'claimed member forged behalf'; exception when insufficient_privilege then null; when sqlstate '42501' then null; end; end $proxy$;
reset role;
select pg_temp.assert_true(has_function_privilege('anon','public.create_prepayment(uuid,uuid,uuid,numeric,timestamptz,uuid)','EXECUTE') is false and has_table_privilege('authenticated','public.transfer_components','INSERT') is false and has_table_privilege('authenticated','public.prepayment_accounts','UPDATE') is false,'anon and direct DML remain denied');

-- Isolated edge-case fixture: debt is created before funding, then funding,
-- returns, voiding and actor failures are checked against immutable facts.
reset role; set local role service_role;
insert into public.activities(id,join_code,name,type,base_currency,created_by) values('f6000000-0000-0000-0000-000000000004','96000004','Phase 5 edge','normal','CNY','f6300000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id) values('f6000000-0000-0000-0000-000000000004','f6300000-0000-0000-0000-000000000001'),('f6000000-0000-0000-0000-000000000004','f6300000-0000-0000-0000-000000000002');
insert into public.ledger_units(id,activity_id,name,type) values('f6100000-0000-0000-0000-000000000005','f6000000-0000-0000-0000-000000000004','edge','default');
insert into public.participants(id,activity_id,name,participant_order) values('f6200000-0000-0000-0000-000000000041','f6000000-0000-0000-0000-000000000004','Edge custodian',0),('f6200000-0000-0000-0000-000000000042','f6000000-0000-0000-0000-000000000004','Edge owner',1);
insert into public.participant_claims(activity_id,participant_id,user_id) values('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000041','f6300000-0000-0000-0000-000000000001'),('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6300000-0000-0000-0000-000000000002');
set local role authenticated; select pg_temp.authenticate('f6300000-0000-0000-0000-000000000001');
with x as (select * from public.create_expense('f6100000-0000-0000-0000-000000000005','edge debt',60,'CNY',1,'manual','[{"participant_id":"f6200000-0000-0000-0000-000000000041","amount":"60"}]','[{"participant_id":"f6200000-0000-0000-0000-000000000042","amount":"60"}]','{}',now(),null,null)) insert into phase5_ids select 'edge_expense',expense_id from x;
select pg_temp.assert_true((select amount=60 and debtor_participant_id='f6200000-0000-0000-0000-000000000042' and creditor_participant_id='f6200000-0000-0000-0000-000000000041' from public.expense_debts where expense_id=(select object_id from phase5_ids where label='edge_expense')), 'isolated edge debt is 60');
with x as (select * from public.create_prepayment('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6200000-0000-0000-0000-000000000041',60,now(),null)) insert into phase5_ids select 'edge_deposit',transfer_id from x;
select pg_temp.assert_true((select count(*)=1 from public.transfer_components where transfer_id=(select object_id from phase5_ids where label='edge_deposit') and component_type='settlement' and amount=60) and not exists(select 1 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000004'), 'full funding has one settlement and no account');
with x as (select * from public.create_prepayment('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6200000-0000-0000-0000-000000000041',100,now(),null)) insert into phase5_ids select 'edge_funded',transfer_id from x;
with x as (select * from public.create_prepayment_return('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6200000-0000-0000-0000-000000000041',40,now(),null)) insert into phase5_ids select 'edge_return',transfer_id from x;
select pg_temp.assert_true((select balance=60 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000004'), 'partial return leaves balance 60');
with x as (select * from public.create_prepayment_return('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6200000-0000-0000-0000-000000000041',60,now(),null)) insert into phase5_ids select 'edge_return_all',transfer_id from x;
select pg_temp.assert_true(coalesce((select balance from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000004'),0)=0, 'complete return zeros account balance');
do $edge_over$ begin begin perform public.create_prepayment_return('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6200000-0000-0000-0000-000000000041',1,now(),null); raise exception 'over return succeeded'; exception when check_violation then null; end; end $edge_over$;
with x as (select * from public.create_prepayment('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6200000-0000-0000-0000-000000000041',100,now(),null)) insert into phase5_ids select 'edge_deposit_active',transfer_id from x;
with x as (select * from public.create_prepayment_return('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6200000-0000-0000-0000-000000000041',40,now(),null)) insert into phase5_ids select 'edge_return_active',transfer_id from x;
select financial_version into temporary table edge_version_before from public.activities where id='f6000000-0000-0000-0000-000000000004';
do $edge_void$ begin begin perform * from public.void_prepayment_transfer((select object_id from phase5_ids where label='edge_deposit_active'),'void active deposit'); raise exception 'active deposit void succeeded'; exception when check_violation then null; end; end $edge_void$;
select pg_temp.assert_true((select not is_voided from public.transfers where id=(select object_id from phase5_ids where label='edge_deposit_active')) and (select not is_voided from public.transfers where id=(select object_id from phase5_ids where label='edge_return_active')) and (select balance=60 from public.prepayment_accounts where activity_id='f6000000-0000-0000-0000-000000000004') and (select financial_version=(select financial_version from edge_version_before) from public.activities where id='f6000000-0000-0000-0000-000000000004'), 'active return blocks deposit void without mutation');
reset role; set local role authenticated; select pg_temp.authenticate('f6300000-0000-0000-0000-000000000002');
select pg_temp.assert_true((select count(*)=1 from public.create_prepayment('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6200000-0000-0000-0000-000000000041',1,now(),null)), 'claimed member can create using own participant');
do $edge_behalf$ begin begin perform public.create_prepayment('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6200000-0000-0000-0000-000000000041',1,now(),'f6200000-0000-0000-0000-000000000041'); raise exception 'member forged behalf'; exception when sqlstate '42501' then null; end; end $edge_behalf$;
set local role authenticated; select pg_temp.authenticate('f6300000-0000-0000-0000-000000000004');
do $edge_outsider$ begin begin perform public.create_prepayment('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6200000-0000-0000-0000-000000000041',1,now(),null); raise exception 'outsider succeeded'; exception when sqlstate '42501' then null; end; end $edge_outsider$;
reset role; set local role service_role; update public.activities set archived_at=now() where id='f6000000-0000-0000-0000-000000000004'; select financial_version into temporary table edge_arch_version from public.activities where id='f6000000-0000-0000-0000-000000000004'; grant select on edge_arch_version to authenticated; set local role authenticated; select pg_temp.authenticate('f6300000-0000-0000-0000-000000000001');
do $edge_arch$ begin begin perform public.create_prepayment('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6200000-0000-0000-0000-000000000041',1,now(),null); raise exception 'archived create succeeded'; exception when sqlstate '55000' then null; end; begin perform public.create_prepayment_return('f6000000-0000-0000-0000-000000000004','f6200000-0000-0000-0000-000000000042','f6200000-0000-0000-0000-000000000041',1,now(),null); raise exception 'archived return succeeded'; exception when sqlstate '55000' then null; end; begin perform public.void_prepayment_transfer((select object_id from phase5_ids where label='edge_return_active'),'archived void'); raise exception 'archived void succeeded'; exception when sqlstate '55000' then null; end; end $edge_arch$;
select pg_temp.assert_true((select financial_version=(select financial_version from edge_arch_version) from public.activities where id='f6000000-0000-0000-0000-000000000004'), 'archived failures preserve version');
select pass('Phase 5 extended behavior assertions');
select * from extensions.finish();
rollback;
