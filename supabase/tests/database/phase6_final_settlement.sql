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

-- One creator, two members, and an outsider exercise the same invoker/RLS
-- boundary as the Android client.  The large fixture has a root and two
-- sub-activities; the second component is intentionally disconnected.
insert into auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
values
 ('00000000-0000-0000-0000-000000000000','f8600000-0000-0000-0000-000000000001','authenticated','authenticated','phase6.creator@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','f8600000-0000-0000-0000-000000000002','authenticated','authenticated','phase6.member@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','f8600000-0000-0000-0000-000000000003','authenticated','authenticated','phase6.member2@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','f8600000-0000-0000-0000-000000000004','authenticated','authenticated','phase6.outsider@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());

insert into public.activities(id,join_code,name,type,base_currency,created_by) values
 ('f8600000-0000-0000-0000-000000000001','86000001','Phase 6 large','large','CNY','f8600000-0000-0000-0000-000000000001'),
 ('f8600000-0000-0000-0000-000000000002','86000002','Phase 6 normal','normal','CNY','f8600000-0000-0000-0000-000000000001'),
 ('f8600000-0000-0000-0000-000000000003','86000003','Phase 6 merge','large','CNY','f8600000-0000-0000-0000-000000000001'),
 ('f8600000-0000-0000-0000-000000000004','86000004','Phase 6 archive','large','CNY','f8600000-0000-0000-0000-000000000001'),
 ('f8600000-0000-0000-0000-000000000005','86000005','Phase 6 cycle','normal','CNY','f8600000-0000-0000-0000-000000000001'),
 ('f8600000-0000-0000-0000-000000000006','86000006','Phase 6 capacity','large','CNY','f8600000-0000-0000-0000-000000000001'),
 ('f8600000-0000-0000-0000-000000000007','86000007','Phase 6 reverse return','large','CNY','f8600000-0000-0000-0000-000000000001'),
 ('f8600000-0000-0000-0000-000000000008','86000008','Phase 6 weak graph','large','CNY','f8600000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id)
select a.id,u.id from public.activities a cross join auth.users u
where u.id in ('f8600000-0000-0000-0000-000000000001','f8600000-0000-0000-0000-000000000002','f8600000-0000-0000-0000-000000000003') and a.id::text like 'f8600000-0000-0000-0000-00000000000%';
insert into public.ledger_units(id,activity_id,name,type) values
 ('f8610000-0000-0000-0000-000000000001','f8600000-0000-0000-0000-000000000001','root','root'),
 ('f8610000-0000-0000-0000-000000000002','f8600000-0000-0000-0000-000000000001','breakfast','sub_activity'),
 ('f8610000-0000-0000-0000-000000000003','f8600000-0000-0000-0000-000000000001','tickets','sub_activity'),
 ('f8610000-0000-0000-0000-000000000004','f8600000-0000-0000-0000-000000000002','normal','default'),
 ('f8610000-0000-0000-0000-000000000005','f8600000-0000-0000-0000-000000000003','root','root'),
 ('f8610000-0000-0000-0000-000000000006','f8600000-0000-0000-0000-000000000003','child','sub_activity'),
 ('f8610000-0000-0000-0000-000000000007','f8600000-0000-0000-0000-000000000004','root','root'),
 ('f8610000-0000-0000-0000-000000000008','f8600000-0000-0000-0000-000000000005','normal','default'),
 ('f8610000-0000-0000-0000-000000000009','f8600000-0000-0000-0000-000000000006','root','root'),
 ('f8610000-0000-0000-0000-000000000010','f8600000-0000-0000-0000-000000000006','capacity child','sub_activity'),
 ('f8610000-0000-0000-0000-000000000011','f8600000-0000-0000-0000-000000000007','root','root'),
 ('f8610000-0000-0000-0000-000000000012','f8600000-0000-0000-0000-000000000007','reverse child','sub_activity'),
 ('f8610000-0000-0000-0000-000000000013','f8600000-0000-0000-0000-000000000008','root','root'),
 ('f8610000-0000-0000-0000-000000000014','f8600000-0000-0000-0000-000000000008','weak child','sub_activity');
insert into public.participants(id,activity_id,name,participant_order) values
 ('f8620000-0000-0000-0000-000000000011','f8600000-0000-0000-0000-000000000001','A',0),
 ('f8620000-0000-0000-0000-000000000012','f8600000-0000-0000-0000-000000000001','B',1),
 ('f8620000-0000-0000-0000-000000000001','f8600000-0000-0000-0000-000000000001','C',2),
 ('f8620000-0000-0000-0000-000000000014','f8600000-0000-0000-0000-000000000001','D',3),
 ('f8620000-0000-0000-0000-000000000015','f8600000-0000-0000-0000-000000000001','E',4),
 ('f8620000-0000-0000-0000-000000000021','f8600000-0000-0000-0000-000000000002','N-A',0),
 ('f8620000-0000-0000-0000-000000000022','f8600000-0000-0000-0000-000000000002','N-B',1),
 ('f8620000-0000-0000-0000-000000000031','f8600000-0000-0000-0000-000000000003','Owner',0),
 ('f8620000-0000-0000-0000-000000000032','f8600000-0000-0000-0000-000000000003','Custodian',1),
 ('f8620000-0000-0000-0000-000000000041','f8600000-0000-0000-0000-000000000004','Archive A',0),
 ('f8620000-0000-0000-0000-000000000042','f8600000-0000-0000-0000-000000000004','Archive B',1),
 ('f8620000-0000-0000-0000-000000000043','f8600000-0000-0000-0000-000000000004','Archive unclaimed',2),
 ('f8620000-0000-0000-0000-000000000051','f8600000-0000-0000-0000-000000000005','Cycle A',0),
 ('f8620000-0000-0000-0000-000000000052','f8600000-0000-0000-0000-000000000005','Cycle B',1),
 ('f8620000-0000-0000-0000-000000000053','f8600000-0000-0000-0000-000000000005','Cycle C',2),
 ('f8620000-0000-0000-0000-000000000061','f8600000-0000-0000-0000-000000000006','Capacity A',0),
 ('f8620000-0000-0000-0000-000000000062','f8600000-0000-0000-0000-000000000006','Capacity B',1),
 ('f8620000-0000-0000-0000-000000000063','f8600000-0000-0000-0000-000000000006','Capacity D',2),
 ('f8620000-0000-0000-0000-000000000064','f8600000-0000-0000-0000-000000000006','Capacity E',3),
 ('f8620000-0000-0000-0000-000000000071','f8600000-0000-0000-0000-000000000007','Return owner',0),
 ('f8620000-0000-0000-0000-000000000072','f8600000-0000-0000-0000-000000000007','Return custodian',1),
 ('f8620000-0000-0000-0000-000000000073','f8600000-0000-0000-0000-000000000007','Return middle',2),
 ('f8620000-0000-0000-0000-000000000081','f8600000-0000-0000-0000-000000000008','Weak D',0),
 ('f8620000-0000-0000-0000-000000000082','f8600000-0000-0000-0000-000000000008','Weak B',1),
 ('f8620000-0000-0000-0000-000000000083','f8600000-0000-0000-0000-000000000008','Weak A',2),
 ('f8620000-0000-0000-0000-000000000084','f8600000-0000-0000-0000-000000000008','Weak C',3);
insert into public.participant_claims(activity_id,participant_id,user_id) values
 ('f8600000-0000-0000-0000-000000000001','f8620000-0000-0000-0000-000000000011','f8600000-0000-0000-0000-000000000001'),
 ('f8600000-0000-0000-0000-000000000001','f8620000-0000-0000-0000-000000000012','f8600000-0000-0000-0000-000000000002'),
 ('f8600000-0000-0000-0000-000000000001','f8620000-0000-0000-0000-000000000001','f8600000-0000-0000-0000-000000000003'),
 ('f8600000-0000-0000-0000-000000000003','f8620000-0000-0000-0000-000000000031','f8600000-0000-0000-0000-000000000002'),
 ('f8600000-0000-0000-0000-000000000003','f8620000-0000-0000-0000-000000000032','f8600000-0000-0000-0000-000000000003'),
 ('f8600000-0000-0000-0000-000000000004','f8620000-0000-0000-0000-000000000041','f8600000-0000-0000-0000-000000000001'),
 ('f8600000-0000-0000-0000-000000000004','f8620000-0000-0000-0000-000000000042','f8600000-0000-0000-0000-000000000002'),
 ('f8600000-0000-0000-0000-000000000005','f8620000-0000-0000-0000-000000000051','f8600000-0000-0000-0000-000000000001'),
 ('f8600000-0000-0000-0000-000000000005','f8620000-0000-0000-0000-000000000052','f8600000-0000-0000-0000-000000000002'),
 ('f8600000-0000-0000-0000-000000000005','f8620000-0000-0000-0000-000000000053','f8600000-0000-0000-0000-000000000003'),
 ('f8600000-0000-0000-0000-000000000006','f8620000-0000-0000-0000-000000000061','f8600000-0000-0000-0000-000000000001'),
 ('f8600000-0000-0000-0000-000000000007','f8620000-0000-0000-0000-000000000071','f8600000-0000-0000-0000-000000000001'),
 ('f8600000-0000-0000-0000-000000000007','f8620000-0000-0000-0000-000000000072','f8600000-0000-0000-0000-000000000002'),
 ('f8600000-0000-0000-0000-000000000007','f8620000-0000-0000-0000-000000000073','f8600000-0000-0000-0000-000000000003'),
 ('f8600000-0000-0000-0000-000000000008','f8620000-0000-0000-0000-000000000083','f8600000-0000-0000-0000-000000000001');

set local role authenticated;
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000001');
create temporary table phase6_ids(label text primary key, object_id uuid not null) on commit drop;

-- Root A -> B plus child B -> C is the minimum cross-unit path.  D -> E is
-- disconnected and must remain a separate direct item, never A -> E.
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000001','root A owes B',40,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000012","amount":"40"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000011","amount":"40"}]','{}','2026-08-31 09:00+08',null,null)) insert into phase6_ids select 'root_debt',expense_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000002','child B owes C',40,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000001","amount":"40"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000012","amount":"40"}]','{}','2026-08-31 10:00+08',null,null)) insert into phase6_ids select 'child_debt',expense_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000003','disconnected D owes E',12,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000015","amount":"12"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000014","amount":"12"}]','{}','2026-08-31 11:00+08',null,null)) insert into phase6_ids select 'disconnected_debt',expense_id from x;

create temporary table phase6_plan_before on commit drop as
select activity_id,from_participant_id,to_participant_id,amount,ordinary_amount,prepayment_return_amount,currency,source_financial_version,is_prepayment_return
from public.preview_final_settlement('f8600000-0000-0000-0000-000000000001');
select pg_temp.assert_true(
 (select array_agg(from_participant_id::text||'>'||to_participant_id::text||':'||amount::text order by from_participant_id,to_participant_id) = array[
  'f8620000-0000-0000-0000-000000000011>f8620000-0000-0000-0000-000000000001:40.0',
  'f8620000-0000-0000-0000-000000000014>f8620000-0000-0000-0000-000000000015:12.0']::text[]
  from phase6_plan_before)
 and (select not exists((select * from phase6_plan_before) except select * from public.get_final_settlement_plan('f8600000-0000-0000-0000-000000000001')))
 and (select not exists((select * from public.get_final_settlement_plan('f8600000-0000-0000-0000-000000000001') except select * from phase6_plan_before)))
 and (select bool_and(source_financial_version=(select financial_version from public.activities where id='f8600000-0000-0000-0000-000000000001')) from phase6_plan_before),
 'large root/sub debts use deterministic participant ordering and preserve disconnected components');

-- A stale amount is rejected after a financial change, and the failed call
-- does not create a fact or increment financial_version.
select financial_version into temporary table phase6_stale_version from public.activities where id='f8600000-0000-0000-0000-000000000001';
select pg_temp.assert_true((select base_amount=41 and version=2 from public.update_expense((select object_id from phase6_ids where label='child_debt'),'f8610000-0000-0000-0000-000000000002','child debt increased',41,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000001","amount":"41"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000012","amount":"41"}]','{}','2026-08-31 10:00+08',null,null)),'child update succeeds with expense version 2');
select pg_temp.assert_true((select financial_version=(select financial_version+1 from phase6_stale_version) from public.activities where id='f8600000-0000-0000-0000-000000000001'),'child update changes the current plan version');
select pg_temp.assert_true((select base_amount=41 and version=2 from public.update_expense((select object_id from phase6_ids where label='root_debt'),'f8610000-0000-0000-0000-000000000001','root debt increased',41,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000012","amount":"41"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000011","amount":"41"}]','{}','2026-08-31 09:00+08',null,null)),'root update preserves the two-hop shape');
do $stale$ begin begin
  perform * from public.execute_final_settlement('f8600000-0000-0000-0000-000000000001','f8620000-0000-0000-0000-000000000011','f8620000-0000-0000-0000-000000000001',40,now(),null);
  raise exception 'stale final plan unexpectedly succeeded';
exception when check_violation then null; end; end $stale$;
select pg_temp.assert_true((select financial_version=(select financial_version+2 from phase6_stale_version) from public.activities where id='f8600000-0000-0000-0000-000000000001') and (select count(*)=0 from public.transfers where activity_id='f8600000-0000-0000-0000-000000000001' and type='final_settlement'),'stale plan rejection has no financial side effect');

-- Execute the current A -> C item.  A two-edge path explains one real 40.0
-- payment with 80.0 of path rows, as required by the path semantics.
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000001');
with x as (select * from public.create_final_settlement('f8600000-0000-0000-0000-000000000001','f8620000-0000-0000-0000-000000000011','f8620000-0000-0000-0000-000000000001',41,'2026-08-31 13:00+08',null)) insert into phase6_ids select 'final_ac',transfer_id from x;
select pg_temp.assert_true(
 (select type='final_settlement' and amount=41 and currency='CNY' from public.transfers where id=(select object_id from phase6_ids where label='final_ac'))
 and (select count(*)=2 and sum(amount)=82 and sum(amount)>(select amount from public.transfers where id=(select object_id from phase6_ids where label='final_ac')) and bool_and(component_type='settlement') from public.final_settlement_paths where transfer_id=(select object_id from phase6_ids where label='final_ac'))
 and (select count(*)=2 and bool_and(source_expense_id in (select object_id from phase6_ids where label in ('root_debt','child_debt'))) from public.final_settlement_paths where transfer_id=(select object_id from phase6_ids where label='final_ac'))
 and (select not exists(select 1 from public.bilateral_debts where activity_id='f8600000-0000-0000-0000-000000000001' and (debtor_participant_id in ('f8620000-0000-0000-0000-000000000011','f8620000-0000-0000-0000-000000000012') or creditor_participant_id in ('f8620000-0000-0000-0000-000000000001')))),
 'final execution records immutable path rows and consumes the cross-unit ordinary edges');

-- Historical update/delete retain the Transfer and path facts, while the
-- current balance changes.  Full rebuild is equivalent and version-neutral.
select financial_version into temporary table phase6_history_version from public.activities where id='f8600000-0000-0000-0000-000000000001';
select pg_temp.assert_true((select base_amount=20 and version=3 from public.update_expense((select object_id from phase6_ids where label='root_debt'),'f8610000-0000-0000-0000-000000000001','root reduced',20,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000012","amount":"20"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000011","amount":"20"}]','{}','2026-08-31 09:00+08',null,null)),'history update succeeds with expense version 3');
select pg_temp.assert_true((select financial_version=(select financial_version+1 from phase6_history_version) from public.activities where id='f8600000-0000-0000-0000-000000000001'),'history update increments Activity version once');
select pg_temp.assert_true((select count(*)=2 from public.final_settlement_paths where transfer_id=(select object_id from phase6_ids where label='final_ac')) and (select exists(select 1 from public.bilateral_debts where debtor_participant_id='f8620000-0000-0000-0000-000000000012' and creditor_participant_id='f8620000-0000-0000-0000-000000000011' and amount=21)),'history update retains paths and exposes the changed residual');
select pg_temp.assert_true((select deleted and version=4 from public.delete_expense((select object_id from phase6_ids where label='root_debt'))),'history delete succeeds with expense version 4');
select pg_temp.assert_true((select financial_version=(select financial_version+2 from phase6_history_version) from public.activities where id='f8600000-0000-0000-0000-000000000001'),'history delete increments Activity version once');
select pg_temp.assert_true((select count(*)=2 from public.final_settlement_paths where transfer_id=(select object_id from phase6_ids where label='final_ac')) and (select exists(select 1 from public.bilateral_debts where debtor_participant_id='f8620000-0000-0000-0000-000000000012' and creditor_participant_id='f8620000-0000-0000-0000-000000000011' and amount=41)),'history delete retains paths and recalculates balance');
reset role; set local role service_role;
create temporary table phase6_before_rebuild on commit drop as select activity_id,debtor_participant_id,creditor_participant_id,amount from public.bilateral_debts where activity_id='f8600000-0000-0000-0000-000000000001';
select financial_version into temporary table phase6_rebuild_version from public.activities where id='f8600000-0000-0000-0000-000000000001';
select private.rebuild_activity_debt_projection('f8600000-0000-0000-0000-000000000001');
select pg_temp.assert_true((select financial_version=(select financial_version from phase6_rebuild_version) from public.activities where id='f8600000-0000-0000-0000-000000000001') and not exists((select * from phase6_before_rebuild except select activity_id,debtor_participant_id,creditor_participant_id,amount from public.bilateral_debts where activity_id='f8600000-0000-0000-0000-000000000001')) and not exists((select activity_id,debtor_participant_id,creditor_participant_id,amount from public.bilateral_debts where activity_id='f8600000-0000-0000-0000-000000000001' except select * from phase6_before_rebuild)),'full rebuild preserves history projection and financial_version');

-- Voiding final settlement keeps path history but makes those paths inactive.
set local role authenticated; select pg_temp.authenticate('f8600000-0000-0000-0000-000000000001');
select pg_temp.assert_true((select voided from public.void_prepayment_transfer((select object_id from phase6_ids where label='final_ac'),'undo final')),'void final settlement succeeds');
select pg_temp.assert_true((select count(*)=2 from public.final_settlement_paths where transfer_id=(select object_id from phase6_ids where label='final_ac')) and (select exists(select 1 from public.bilateral_debts where debtor_participant_id='f8620000-0000-0000-0000-000000000012' and creditor_participant_id='f8620000-0000-0000-0000-000000000001' and amount=41)),'void leaves paths visible but removes their financial effect');

-- A normal Activity cannot expose final settlement.
do $normal$ begin begin perform * from public.preview_final_settlement('f8600000-0000-0000-0000-000000000002'); raise exception 'normal preview succeeded'; exception when check_violation then null; end; end $normal$;
do $normal_execute$ begin begin
  perform * from public.create_final_settlement(
    'f8600000-0000-0000-0000-000000000002',
    'f8620000-0000-0000-0000-000000000021',
    'f8620000-0000-0000-0000-000000000022',
    1, now(), null);
  raise exception 'normal execute succeeded';
exception when check_violation then null; end; end $normal_execute$;

-- Capacity branch: A -> B 100, B -> D 1, E -> D 99.  The deterministic
-- matcher must split A's 100 into A -> B 99 and A -> D 1; the latter has a
-- two-hop explanation whose every hop is bounded by its source debt.
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000001');
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000009','capacity A to B',100,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000062","amount":"100"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000061","amount":"100"}]','{}',now(),null,null)) insert into phase6_ids select 'capacity_ab',expense_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000010','capacity B to D',1,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000063","amount":"1"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000062","amount":"1"}]','{}',now(),null,null)) insert into phase6_ids select 'capacity_bd',expense_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000010','capacity E to D',99,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000063","amount":"99"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000064","amount":"99"}]','{}',now(),null,null)) insert into phase6_ids select 'capacity_ed',expense_id from x;
select pg_temp.assert_true(
 (select count(*)=3 and bool_and((from_participant_id='f8620000-0000-0000-0000-000000000061' and to_participant_id='f8620000-0000-0000-0000-000000000062' and amount=99) or (from_participant_id='f8620000-0000-0000-0000-000000000061' and to_participant_id='f8620000-0000-0000-0000-000000000063' and amount=1) or (from_participant_id='f8620000-0000-0000-0000-000000000064' and to_participant_id='f8620000-0000-0000-0000-000000000063' and amount=99)) from public.preview_final_settlement('f8600000-0000-0000-0000-000000000006'))
 and (select count(*)=0 from public.final_settlement_paths where activity_id='f8600000-0000-0000-0000-000000000006'),
 'capacity branch emits bounded deterministic items before execution');
select financial_version into temporary table phase6_capacity_version from public.activities where id='f8600000-0000-0000-0000-000000000006';
with x as (select * from public.create_final_settlement('f8600000-0000-0000-0000-000000000006','f8620000-0000-0000-0000-000000000061','f8620000-0000-0000-0000-000000000063',1,now(),'f8620000-0000-0000-0000-000000000063')) insert into phase6_ids select 'capacity_final',transfer_id from x;
select pg_temp.assert_true(
 (select count(*)=2 and bool_and(amount=1 and ((from_participant_id='f8620000-0000-0000-0000-000000000061' and to_participant_id='f8620000-0000-0000-0000-000000000062') or (from_participant_id='f8620000-0000-0000-0000-000000000062' and to_participant_id='f8620000-0000-0000-0000-000000000063'))) from public.final_settlement_paths where transfer_id=(select object_id from phase6_ids where label='capacity_final'))
 and not exists(select 1 from public.final_settlement_paths p join public.expense_debts d on d.expense_id=p.source_expense_id where p.transfer_id=(select object_id from phase6_ids where label='capacity_final') and p.amount>d.amount)
 and not exists(select 1 from public.bilateral_debts where activity_id='f8600000-0000-0000-0000-000000000006' and debtor_participant_id in ('f8620000-0000-0000-0000-000000000063','f8620000-0000-0000-0000-000000000061') and creditor_participant_id in ('f8620000-0000-0000-0000-000000000061','f8620000-0000-0000-0000-000000000063'))
 and (select financial_version=(select financial_version+1 from phase6_capacity_version) from public.activities where id='f8600000-0000-0000-0000-000000000006'),
 'capacity final path never exceeds an underlying edge or invents a reverse debt');

-- Weakly connected but not directed: A -> B, C -> B, and C -> D leave D
-- unreachable from A even though all four participants share one component.
-- The matcher must choose an explainable reachable endpoint and never fabricate
-- a direct source-less A -> D edge.
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000013','weak A to B',100,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000082","amount":"100"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000083","amount":"100"}]','{}',now(),null,null)) insert into phase6_ids select 'weak_ab',expense_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000014','weak C to B',40,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000082","amount":"40"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000084","amount":"40"}]','{}',now(),null,null)) insert into phase6_ids select 'weak_cb',expense_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000014','weak C to D',60,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000081","amount":"60"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000084","amount":"60"}]','{}',now(),null,null)) insert into phase6_ids select 'weak_cd',expense_id from x;
select pg_temp.assert_true(
 (select count(*)=3 and bool_and((from_participant_id='f8620000-0000-0000-0000-000000000083' and to_participant_id='f8620000-0000-0000-0000-000000000082' and amount=100) or (from_participant_id='f8620000-0000-0000-0000-000000000084' and to_participant_id='f8620000-0000-0000-0000-000000000081' and amount=60) or (from_participant_id='f8620000-0000-0000-0000-000000000084' and to_participant_id='f8620000-0000-0000-0000-000000000082' and amount=40)) from public.preview_final_settlement('f8600000-0000-0000-0000-000000000008')),
 'weakly connected graph uses deterministic endpoint matching');
with x as (select * from public.create_final_settlement('f8600000-0000-0000-0000-000000000008','f8620000-0000-0000-0000-000000000083','f8620000-0000-0000-0000-000000000082',100,'2026-08-31 17:00+08','f8620000-0000-0000-0000-000000000082')) insert into phase6_ids select 'weak_final',transfer_id from x;
select pg_temp.assert_true((select count(*)=1 and bool_and(from_participant_id='f8620000-0000-0000-0000-000000000083' and to_participant_id='f8620000-0000-0000-0000-000000000082' and amount=100 and source_expense_id=(select object_id from phase6_ids where label='weak_ab')) from public.final_settlement_paths where transfer_id=(select object_id from phase6_ids where label='weak_final')),'weak graph final explanation must use an actual directed source edge and never fabricate a direct path');

-- Opposite-direction case: an owner -> custodian account returns custodian ->
-- owner, while ordinary netting suggests owner -> custodian through a middle
-- path.  These must remain two separate final items and real transfers.
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000001');
with x as (select * from public.create_prepayment('f8600000-0000-0000-0000-000000000007','f8620000-0000-0000-0000-000000000071','f8620000-0000-0000-0000-000000000072',10,'2026-08-31 18:00+08',null)) insert into phase6_ids select 'reverse_return_deposit',transfer_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000012','return owner to middle',10,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000073","amount":"10"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000071","amount":"10"}]','{}',now(),null,null)) insert into phase6_ids select 'reverse_om',expense_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000012','return middle to custodian',10,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000072","amount":"10"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000073","amount":"10"}]','{}',now(),null,null)) insert into phase6_ids select 'reverse_mc',expense_id from x;
select pg_temp.assert_true((select count(*)=2 and count(*) filter (where from_participant_id='f8620000-0000-0000-0000-000000000071' and to_participant_id='f8620000-0000-0000-0000-000000000072' and ordinary_amount=10 and prepayment_return_amount=0)=1 and count(*) filter (where from_participant_id='f8620000-0000-0000-0000-000000000072' and to_participant_id='f8620000-0000-0000-0000-000000000071' and ordinary_amount=0 and prepayment_return_amount=10 and is_prepayment_return)=1 from public.preview_final_settlement('f8600000-0000-0000-0000-000000000007')),'opposite ordinary final and prepayment return remain separate directions');
with x as (select * from public.create_final_settlement('f8600000-0000-0000-0000-000000000007','f8620000-0000-0000-0000-000000000071','f8620000-0000-0000-0000-000000000072',10,'2026-08-31 19:00+08',null)) insert into phase6_ids select 'reverse_ordinary_final',transfer_id from x;
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000002');
with x as (select * from public.create_final_settlement('f8600000-0000-0000-0000-000000000007','f8620000-0000-0000-0000-000000000072','f8620000-0000-0000-0000-000000000071',10,'2026-08-31 20:00+08',null)) insert into phase6_ids select 'reverse_return_final',transfer_id from x;
select pg_temp.assert_true((select count(*)=2 from public.transfers where activity_id='f8600000-0000-0000-0000-000000000007' and type='final_settlement' and not is_voided and ((from_participant_id='f8620000-0000-0000-0000-000000000071' and to_participant_id='f8620000-0000-0000-0000-000000000072') or (from_participant_id='f8620000-0000-0000-0000-000000000072' and to_participant_id='f8620000-0000-0000-0000-000000000071'))) and (select coalesce(sum(balance),0)=0 from public.prepayment_accounts where activity_id='f8600000-0000-0000-0000-000000000007'),'opposite final directions execute independently without cancellation or merge');

-- A multi-hop final endpoint may share a prepayment account pair.  Its
-- endpoint component must not be mistaken for a direct settlement against
-- that account; only the recorded path hops settle ordinary debt.
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000001');
with x as (select * from public.create_prepayment('f8600000-0000-0000-0000-000000000007','f8620000-0000-0000-0000-000000000071','f8620000-0000-0000-0000-000000000073',100,'2026-08-31 21:00+08',null)) insert into phase6_ids select 'multihop_account',transfer_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000011','multihop direct account debt',50,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000073","amount":"50"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000071","amount":"50"}]','{}',now(),null,null)) insert into phase6_ids select 'multihop_direct_debt',expense_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000011','multihop A to middle',100,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000072","amount":"100"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000071","amount":"100"}]','{}',now(),null,null)) insert into phase6_ids select 'multihop_ab',expense_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000012','multihop middle to endpoint',100,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000073","amount":"100"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000072","amount":"100"}]','{}',now(),null,null)) insert into phase6_ids select 'multihop_bc',expense_id from x;
-- The earlier return-owner -> middle fact contributes another 10.0 to this
-- pair, so the account consumes 60.0 and retains 40.0 before final payment.
select pg_temp.assert_true((select count(*) filter (where from_participant_id='f8620000-0000-0000-0000-000000000071' and to_participant_id='f8620000-0000-0000-0000-000000000073' and amount=90)=1 from public.preview_final_settlement('f8600000-0000-0000-0000-000000000007')),'multi-hop preview preserves the directed endpoint amount');
select pg_temp.assert_true((select sum(balance)=40 from public.prepayment_accounts where activity_id='f8600000-0000-0000-0000-000000000007' and owner_participant_id='f8620000-0000-0000-0000-000000000071' and custodian_participant_id='f8620000-0000-0000-0000-000000000073'),'multi-hop endpoint shares an account without changing its residual before payment');
with x as (select * from public.create_final_settlement('f8600000-0000-0000-0000-000000000007','f8620000-0000-0000-0000-000000000071','f8620000-0000-0000-0000-000000000073',90,'2026-08-31 22:00+08',null)) insert into phase6_ids select 'multihop_final',transfer_id from x;
select pg_temp.assert_true((select count(*)=2 and sum(amount)=180 and bool_and(amount=90) from public.final_settlement_paths where transfer_id=(select object_id from phase6_ids where label='multihop_final')) and (select sum(balance)=40 from public.prepayment_accounts where activity_id='f8600000-0000-0000-0000-000000000007' and owner_participant_id='f8620000-0000-0000-0000-000000000071' and custodian_participant_id='f8620000-0000-0000-0000-000000000073') and (select sum(amount)=60 from public.prepayment_usages where activity_id='f8600000-0000-0000-0000-000000000007'),'multi-hop final endpoint does not consume the prepayment account as a direct settlement');

-- Prepayment return merges only with an ordinary item of the same direction.
-- Owner -> Custodian has 10.0 available, while Custodian -> Owner owes 20.0.
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000002');
with x as (select * from public.create_prepayment('f8600000-0000-0000-0000-000000000003','f8620000-0000-0000-0000-000000000031','f8620000-0000-0000-0000-000000000032',10,'2026-08-31 14:00+08',null)) insert into phase6_ids select 'merge_prepay',transfer_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000006','custodian owes owner',20,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000031","amount":"20"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000032","amount":"20"}]','{}','2026-08-31 15:00+08',null,null)) insert into phase6_ids select 'merge_debt',expense_id from x;
select pg_temp.assert_true((select count(*)=1 and bool_and(from_participant_id='f8620000-0000-0000-0000-000000000032' and to_participant_id='f8620000-0000-0000-0000-000000000031' and amount=30 and ordinary_amount=20 and prepayment_return_amount=10 and not is_prepayment_return) from public.preview_final_settlement('f8600000-0000-0000-0000-000000000003')),'same-direction final ordinary and prepayment return merge into one item');
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000003');
with x as (select * from public.execute_final_settlement('f8600000-0000-0000-0000-000000000003','f8620000-0000-0000-0000-000000000032','f8620000-0000-0000-0000-000000000031',30,'2026-08-31 16:00+08',null)) insert into phase6_ids select 'merge_final',transfer_id from x;
select pg_temp.assert_true((select count(*)=2 and bool_and((component_type='settlement' and amount=20) or (component_type='prepayment_return' and amount=10)) from public.transfer_components where transfer_id=(select object_id from phase6_ids where label='merge_final')) and (select coalesce(sum(balance),0)=0 from public.prepayment_accounts where activity_id='f8600000-0000-0000-0000-000000000003'),'merged execution persists separate components and returns the account');
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000001');
select pg_temp.assert_true((select not has_unsettled and total_debt=0 and total_prepayment=0 and warning is null from public.archive_activity('f8600000-0000-0000-0000-000000000003')),'completed archive returns empty warning summary');
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000002');
do $archive_actor$ begin begin perform * from public.unarchive_activity('f8600000-0000-0000-0000-000000000003'); raise exception 'member unarchive succeeded'; exception when insufficient_privilege then null; end; end $archive_actor$;
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000001');
select pg_temp.assert_true((select changed and not archived from public.unarchive_activity('f8600000-0000-0000-0000-000000000003')),'completed archive has no warning and remains idempotently reversible');

-- Three-party cycle is net zero per participant but remains active because
-- daily bilateral debts are not path-optimized.
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000001');
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000008','cycle A pays B',10,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000052","amount":"10"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000051","amount":"10"}]','{}',now(),null,null)) insert into phase6_ids select 'cycle_ab',expense_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000008','cycle B pays C',10,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000053","amount":"10"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000052","amount":"10"}]','{}',now(),null,null)) insert into phase6_ids select 'cycle_bc',expense_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000008','cycle C pays A',10,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000051","amount":"10"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000053","amount":"10"}]','{}',now(),null,null)) insert into phase6_ids select 'cycle_ca',expense_id from x;
select pg_temp.assert_true((select count(*)=3 from public.bilateral_debts where activity_id='f8600000-0000-0000-0000-000000000005') and (select completed=false and financial_status='active' from public.activity_financial_status where activity_id='f8600000-0000-0000-0000-000000000005') and (select count(*)=3 and bool_and(net_balance=0 and receivable>0 and payable>0 and financial_status='active' and not completed) from public.participant_financial_status where activity_id='f8600000-0000-0000-0000-000000000005'),'cycle remains active despite zero net balance when bilateral debts remain');

-- Archive/unarchive is creator-only, idempotent, returns warning summaries,
-- and archive makes every business write path read-only.
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000001');
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000007','archive debt',5,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000042","amount":"5"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000041","amount":"5"}]','{}',now(),null,null)) insert into phase6_ids select 'archive_expense',expense_id from x;
with x as (select * from public.create_expense('f8610000-0000-0000-0000-000000000007','archive settled portion',5,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000042","amount":"5"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000041","amount":"5"}]','{}',now(),null,null)) insert into phase6_ids select 'archive_settled_expense',expense_id from x;
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000002');
with x as (select * from public.create_settlement_transfer('f8600000-0000-0000-0000-000000000004','f8620000-0000-0000-0000-000000000041','f8620000-0000-0000-0000-000000000042',5,now(),null)) insert into phase6_ids select 'archive_settlement',transfer_id from x;
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000001');
select financial_version into temporary table phase6_archive_version from public.activities where id='f8600000-0000-0000-0000-000000000004';
select pg_temp.assert_true((select has_unsettled and total_debt=5 and changed and warning is not null from public.archive_activity('f8600000-0000-0000-0000-000000000004')),'unsettled archive returns warning summary');
select pg_temp.assert_true((select not changed and archived and total_debt=5 from public.archive_activity('f8600000-0000-0000-0000-000000000004')),'archive is idempotent');
select pg_temp.assert_true((select changed and not archived from public.unarchive_activity('f8600000-0000-0000-0000-000000000004')),'creator can unarchive');
select pg_temp.assert_true((select not changed and not archived from public.unarchive_activity('f8600000-0000-0000-0000-000000000004')),'unarchive is idempotent');
select pg_temp.assert_true((select changed and archived from public.archive_activity('f8600000-0000-0000-0000-000000000004')),'creator can archive again');

do $archived$ begin
  begin perform * from public.create_expense('f8610000-0000-0000-0000-000000000007','blocked',1,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000042","amount":"1"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000041","amount":"1"}]','{}',now(),null,null); raise exception 'archived create expense succeeded'; exception when object_not_in_prerequisite_state then null; end;
  begin perform * from public.update_expense((select object_id from phase6_ids where label='archive_expense'),'f8610000-0000-0000-0000-000000000007','blocked update',4,'CNY',1,'manual','[{"participant_id":"f8620000-0000-0000-0000-000000000042","amount":"4"}]','[{"participant_id":"f8620000-0000-0000-0000-000000000041","amount":"4"}]','{}',now(),null,null); raise exception 'archived update expense succeeded'; exception when object_not_in_prerequisite_state then null; end;
  begin perform * from public.delete_expense((select object_id from phase6_ids where label='archive_expense')); raise exception 'archived delete expense succeeded'; exception when object_not_in_prerequisite_state then null; end;
  begin perform * from public.create_settlement_transfer('f8600000-0000-0000-0000-000000000004','f8620000-0000-0000-0000-000000000042','f8620000-0000-0000-0000-000000000041',1,now(),null); raise exception 'archived settlement succeeded'; exception when object_not_in_prerequisite_state then null; end;
  begin perform * from public.create_prepayment('f8600000-0000-0000-0000-000000000004','f8620000-0000-0000-0000-000000000041','f8620000-0000-0000-0000-000000000042',1,now(),null); raise exception 'archived prepayment succeeded'; exception when object_not_in_prerequisite_state then null; end;
  begin perform * from public.create_prepayment_return('f8600000-0000-0000-0000-000000000004','f8620000-0000-0000-0000-000000000041','f8620000-0000-0000-0000-000000000042',1,now(),null); raise exception 'archived return succeeded'; exception when object_not_in_prerequisite_state then null; end;
  begin perform * from public.create_final_settlement('f8600000-0000-0000-0000-000000000004','f8620000-0000-0000-0000-000000000042','f8620000-0000-0000-0000-000000000041',1,now(),null); raise exception 'archived final succeeded'; exception when object_not_in_prerequisite_state then null; end;
  begin perform * from public.void_prepayment_transfer((select object_id from phase6_ids where label='archive_settlement'),'archived void'); raise exception 'archived void succeeded'; exception when object_not_in_prerequisite_state then null; end;
  begin perform * from public.create_sub_activity('f8600000-0000-0000-0000-000000000004','blocked sub'); raise exception 'archived sub activity succeeded'; exception when object_not_in_prerequisite_state then null; end;
end $archived$;
select pg_temp.assert_true((select financial_version=(select financial_version from phase6_archive_version) from public.activities where id='f8600000-0000-0000-0000-000000000004'),'archive/unarchive and archived failures do not increment financial_version');

-- Direct Data API writes are also denied after archive, including an attempted
-- cross-Activity unit move.  UPDATE/DELETE may be denied by RLS as zero rows;
-- any changed row is explicitly treated as a failure.
do $archived_dml$ declare n integer;
begin
  update public.activities set name='must stay archived' where id='f8600000-0000-0000-0000-000000000004';
  get diagnostics n = row_count; if n <> 0 then raise exception 'archived Activity UPDATE succeeded'; end if;
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  insert into public.participants(activity_id,name,participant_order) values ('f8600000-0000-0000-0000-000000000004','must fail',99);
  raise exception 'archived Participant INSERT succeeded';
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  update public.participants set name='must stay archived' where id='f8620000-0000-0000-0000-000000000041';
  get diagnostics n = row_count; if n <> 0 then raise exception 'archived Participant UPDATE succeeded'; end if;
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  delete from public.participants where id='f8620000-0000-0000-0000-000000000043';
  get diagnostics n = row_count; if n <> 0 then raise exception 'archived Participant DELETE succeeded'; end if;
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  insert into public.ledger_units(activity_id,name,type) values ('f8600000-0000-0000-0000-000000000004','must fail','sub_activity');
  raise exception 'archived LedgerUnit INSERT succeeded';
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  update public.ledger_units set name='must stay archived' where id='f8610000-0000-0000-0000-000000000007';
  get diagnostics n = row_count; if n <> 0 then raise exception 'archived LedgerUnit UPDATE succeeded'; end if;
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  update public.ledger_units set activity_id='f8600000-0000-0000-0000-000000000005' where id='f8610000-0000-0000-0000-000000000007';
  get diagnostics n = row_count; if n <> 0 then raise exception 'cross-Activity LedgerUnit move succeeded'; end if;
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  insert into public.participant_claims(activity_id,participant_id,user_id) values ('f8600000-0000-0000-0000-000000000004','f8620000-0000-0000-0000-000000000043','f8600000-0000-0000-0000-000000000003');
  raise exception 'archived ParticipantClaim INSERT succeeded';
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  delete from public.participant_claims where activity_id='f8600000-0000-0000-0000-000000000004' and participant_id='f8620000-0000-0000-0000-000000000042';
  get diagnostics n = row_count; if n <> 0 then raise exception 'archived ParticipantClaim DELETE succeeded'; end if;
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  insert into public.activity_members(activity_id,user_id) values ('f8600000-0000-0000-0000-000000000004','f8600000-0000-0000-0000-000000000004');
  raise exception 'archived ActivityMember INSERT succeeded';
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  delete from public.activity_members where activity_id='f8600000-0000-0000-0000-000000000004' and user_id='f8600000-0000-0000-0000-000000000003';
  get diagnostics n = row_count; if n <> 0 then raise exception 'archived ActivityMember DELETE succeeded'; end if;
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  update public.participant_claims set participant_id='f8620000-0000-0000-0000-000000000043'
    where activity_id='f8600000-0000-0000-0000-000000000004' and participant_id='f8620000-0000-0000-0000-000000000042';
  get diagnostics n = row_count; if n <> 0 then raise exception 'archived ParticipantClaim UPDATE succeeded'; end if;
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  delete from public.ledger_units where id='f8610000-0000-0000-0000-000000000007';
  get diagnostics n = row_count; if n <> 0 then raise exception 'archived LedgerUnit DELETE succeeded'; end if;
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  update public.activity_members set user_id='f8600000-0000-0000-0000-000000000004'
    where activity_id='f8600000-0000-0000-0000-000000000004' and user_id='f8600000-0000-0000-0000-000000000003';
  get diagnostics n = row_count; if n <> 0 then raise exception 'archived ActivityMember UPDATE succeeded'; end if;
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
do $archived_dml$ declare n integer;
begin
  update public.participants set activity_id='f8600000-0000-0000-0000-000000000005'
    where id='f8620000-0000-0000-0000-000000000043';
  get diagnostics n = row_count; if n <> 0 then raise exception 'cross-Activity Participant move succeeded'; end if;
exception when insufficient_privilege or object_not_in_prerequisite_state then null;
end $archived_dml$;
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000004');
do $archived_join$ begin
  begin perform * from public.join_activity_by_code('86000004'); raise exception 'archived join succeeded'; exception when object_not_in_prerequisite_state then null; when no_data_found then null; end;
end $archived_join$;
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000001');

-- The member can read paths, but outsider/anon cannot; client roles cannot
-- mutate financial facts or invoke server-only rebuilds.
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000002');
select pg_temp.assert_true((select count(*)=0 from public.final_settlement_paths where activity_id='f8600000-0000-0000-0000-000000000001') is false,'member can read final settlement paths');
select pg_temp.authenticate('f8600000-0000-0000-0000-000000000004');
do $nonmember_final$ begin
  begin
    perform * from public.preview_final_settlement('f8600000-0000-0000-0000-000000000001');
    raise exception 'non-member preview succeeded';
  exception when insufficient_privilege then null; end;
  begin
    perform * from public.create_final_settlement(
      'f8600000-0000-0000-0000-000000000001',
      'f8620000-0000-0000-0000-000000000011',
      'f8620000-0000-0000-0000-000000000001',
      1, now(), null);
    raise exception 'non-member execute succeeded';
  exception when insufficient_privilege then null; end;
end $nonmember_final$;
select pg_temp.assert_true((select count(*)=0 from public.final_settlement_paths),'outsider RLS hides final settlement paths');
reset role;
select pg_temp.assert_true(not has_table_privilege('anon','public.final_settlement_paths','SELECT') and not has_table_privilege('authenticated','public.final_settlement_paths','INSERT,UPDATE,DELETE') and not has_function_privilege('anon','public.preview_final_settlement(uuid)','EXECUTE') and not has_function_privilege('anon','public.create_final_settlement(uuid,uuid,uuid,numeric,timestamptz,uuid)','EXECUTE') and not has_function_privilege('anon','public.archive_activity(uuid)','EXECUTE') and not has_function_privilege('anon','public.unarchive_activity(uuid)','EXECUTE') and not has_function_privilege('anon','private.archive_activity_impl(uuid)','EXECUTE') and has_function_privilege('authenticated','private.archive_activity_impl(uuid)','EXECUTE') and has_function_privilege('authenticated','private.unarchive_activity_impl(uuid)','EXECUTE') and (select not p.prosecdef from pg_proc p where p.oid='public.archive_activity(uuid)'::regprocedure) and (select not p.prosecdef from pg_proc p where p.oid='public.unarchive_activity(uuid)'::regprocedure) and (select p.prosecdef from pg_proc p where p.oid='private.archive_activity_impl(uuid)'::regprocedure) and (select p.prosecdef from pg_proc p where p.oid='private.unarchive_activity_impl(uuid)'::regprocedure) and not has_function_privilege('authenticated','private.rebuild_activity_debt_projection(uuid)','EXECUTE'),'Phase 6 RLS and grants preserve the invoker wrapper and private definer boundary');

select pass('Phase 6 final settlement and archive assertions');
select * from extensions.finish();
rollback;
