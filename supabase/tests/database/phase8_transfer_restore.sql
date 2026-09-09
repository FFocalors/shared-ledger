\set ON_ERROR_STOP on

begin;

create extension if not exists pgtap with schema extensions;
select extensions.plan(1);

create function pg_temp.assert_true(p_condition boolean, p_message text)
returns void language plpgsql as $function$
begin
  if p_condition is not true then raise exception 'assertion failed: %',p_message; end if;
end;
$function$;

create function pg_temp.authenticate(p_user uuid) returns void language plpgsql as $function$
begin
  perform set_config('request.jwt.claims',json_build_object('sub',p_user,'role','authenticated')::text,true);
end;
$function$;

insert into auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
values
 ('00000000-0000-0000-0000-000000000000','fa100000-0000-0000-0000-000000000001','authenticated','authenticated','restore.creator@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','fa100000-0000-0000-0000-000000000002','authenticated','authenticated','restore.member@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','fa100000-0000-0000-0000-000000000003','authenticated','authenticated','restore.third@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','fa100000-0000-0000-0000-000000000004','authenticated','authenticated','restore.outsider@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());

insert into public.activities(id,join_code,name,type,base_currency,created_by) values
 ('fa000000-0000-0000-0000-000000000001','98000001','Restore settlement','normal','CNY','fa100000-0000-0000-0000-000000000001'),
 ('fa000000-0000-0000-0000-000000000002','98000002','Restore prepayment','normal','CNY','fa100000-0000-0000-0000-000000000001'),
 ('fa000000-0000-0000-0000-000000000003','98000003','Restore final','large','CNY','fa100000-0000-0000-0000-000000000001');

insert into public.activity_members(activity_id,user_id)
select a.id,u.id from public.activities a cross join auth.users u
where a.id in (
  'fa000000-0000-0000-0000-000000000001',
  'fa000000-0000-0000-0000-000000000002',
  'fa000000-0000-0000-0000-000000000003'
) and u.id in (
  'fa100000-0000-0000-0000-000000000001',
  'fa100000-0000-0000-0000-000000000002',
  'fa100000-0000-0000-0000-000000000003'
);

insert into public.ledger_units(id,activity_id,name,type) values
 ('fa200000-0000-0000-0000-000000000001','fa000000-0000-0000-0000-000000000001','Settlement root','default'),
 ('fa200000-0000-0000-0000-000000000002','fa000000-0000-0000-0000-000000000002','Prepayment root','default'),
 ('fa200000-0000-0000-0000-000000000003','fa000000-0000-0000-0000-000000000003','Final root','root');

insert into public.participants(id,activity_id,name,participant_order) values
 ('fa300000-0000-0000-0000-000000000011','fa000000-0000-0000-0000-000000000001','Settlement creditor',0),
 ('fa300000-0000-0000-0000-000000000012','fa000000-0000-0000-0000-000000000001','Settlement debtor',1),
 ('fa300000-0000-0000-0000-000000000013','fa000000-0000-0000-0000-000000000001','Settlement third',2),
 ('fa300000-0000-0000-0000-000000000021','fa000000-0000-0000-0000-000000000002','Prepayment owner',0),
 ('fa300000-0000-0000-0000-000000000022','fa000000-0000-0000-0000-000000000002','Prepayment custodian',1),
 ('fa300000-0000-0000-0000-000000000023','fa000000-0000-0000-0000-000000000002','Prepayment third',2),
 ('fa300000-0000-0000-0000-000000000031','fa000000-0000-0000-0000-000000000003','Final owner',0),
 ('fa300000-0000-0000-0000-000000000032','fa000000-0000-0000-0000-000000000003','Final custodian',1),
 ('fa300000-0000-0000-0000-000000000033','fa000000-0000-0000-0000-000000000003','Final third',2);

insert into public.participant_claims(activity_id,participant_id,user_id) values
 ('fa000000-0000-0000-0000-000000000001','fa300000-0000-0000-0000-000000000011','fa100000-0000-0000-0000-000000000001'),
 ('fa000000-0000-0000-0000-000000000001','fa300000-0000-0000-0000-000000000012','fa100000-0000-0000-0000-000000000002'),
 ('fa000000-0000-0000-0000-000000000001','fa300000-0000-0000-0000-000000000013','fa100000-0000-0000-0000-000000000003'),
 ('fa000000-0000-0000-0000-000000000002','fa300000-0000-0000-0000-000000000022','fa100000-0000-0000-0000-000000000001'),
 ('fa000000-0000-0000-0000-000000000002','fa300000-0000-0000-0000-000000000021','fa100000-0000-0000-0000-000000000002'),
 ('fa000000-0000-0000-0000-000000000002','fa300000-0000-0000-0000-000000000023','fa100000-0000-0000-0000-000000000003'),
 ('fa000000-0000-0000-0000-000000000003','fa300000-0000-0000-0000-000000000032','fa100000-0000-0000-0000-000000000001'),
 ('fa000000-0000-0000-0000-000000000003','fa300000-0000-0000-0000-000000000031','fa100000-0000-0000-0000-000000000002'),
 ('fa000000-0000-0000-0000-000000000003','fa300000-0000-0000-0000-000000000033','fa100000-0000-0000-0000-000000000003');

set local role authenticated;
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000001');
create temporary table restore_ids(label text primary key,object_id uuid not null) on commit drop;

-- Settlement restore preserves the fact/dispute, rebuilds debt, audits prior
-- void context, increments once, and a serial retry is a version-neutral no-op.
with x as (
  select * from public.create_expense(
    'fa200000-0000-0000-0000-000000000001','Debt 100',100,'CNY',1,'manual',
    '[{"participant_id":"fa300000-0000-0000-0000-000000000011","amount":"100"}]',
    '[{"participant_id":"fa300000-0000-0000-0000-000000000012","amount":"100"}]',
    '{}','2026-09-08 09:00+08',null,null
  )
) insert into restore_ids select 'settlement_expense',expense_id from x;
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000002');
with x as (
  select * from public.create_settlement_transfer(
    'fa000000-0000-0000-0000-000000000001',
    'fa300000-0000-0000-0000-000000000012',
    'fa300000-0000-0000-0000-000000000011',40,'2026-09-08 10:00+08',null
  )
) insert into restore_ids select 'settlement',transfer_id from x;
select public.add_transfer_dispute(
  (select object_id from restore_ids where label='settlement'),
  'fa300000-0000-0000-0000-000000000012','keep across restore'
);
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000001');
select pg_temp.assert_true(
  (select voided from public.void_settlement_transfer(
    (select object_id from restore_ids where label='settlement'),'original void reason'
  )),
  'creator may void a member-recorded settlement'
);
create temporary table settlement_before_restore on commit drop as
select financial_version from public.activities where id='fa000000-0000-0000-0000-000000000001';
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000002');
create temporary table settlement_restore_result on commit drop as
select * from public.restore_transfer(
  (select object_id from restore_ids where label='settlement'),'money was actually transferred'
);
select pg_temp.assert_true(
  (select restored and financial_version=(select financial_version+1 from settlement_before_restore)
   from settlement_restore_result)
  and (select not is_voided and voided_at is null and voided_by is null and void_reason is null
       from public.transfers where id=(select object_id from restore_ids where label='settlement'))
  and (select amount=60 from public.bilateral_debts
       where activity_id='fa000000-0000-0000-0000-000000000001'
         and debtor_participant_id='fa300000-0000-0000-0000-000000000012'
         and creditor_participant_id='fa300000-0000-0000-0000-000000000011')
  and (select count(*)=1 from public.transfer_disputes
       where transfer_id=(select object_id from restore_ids where label='settlement')),
  'settlement restore reactivates the same fact and preserves disputes'
);
create temporary table settlement_retry_result on commit drop as
select * from public.restore_transfer(
  (select object_id from restore_ids where label='settlement'),'idempotent retry'
);
select pg_temp.assert_true(
  (select not restored and financial_version=(select financial_version+1 from settlement_before_restore)
   from settlement_retry_result)
  and (select financial_version=(select financial_version+1 from settlement_before_restore)
       from public.activities where id='fa000000-0000-0000-0000-000000000001'),
  'serial restore retry is idempotent and version-neutral'
);
select pg_temp.assert_true(
  (select action='transfer.restore'
      and metadata->>'restore_reason'='money was actually transferred'
      and metadata->>'previous_void_reason'='original void reason'
      and metadata->>'previous_voided_by'='fa100000-0000-0000-0000-000000000001'
   from public.audit_logs
   where entity_id=(select object_id from restore_ids where label='settlement')
     and action='transfer.restore'
   order by created_at desc limit 1),
  'restore audit preserves reason and prior void context'
);

-- A replacement settlement consumes current capacity, so the old fact cannot
-- be restored. The failed restore leaves fact, projection, and version intact.
select public.void_settlement_transfer((select object_id from restore_ids where label='settlement'),'replace payment');
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000001');
with x as (
  select * from public.create_settlement_transfer(
    'fa000000-0000-0000-0000-000000000001',
    'fa300000-0000-0000-0000-000000000012',
    'fa300000-0000-0000-0000-000000000011',70,'2026-09-08 11:00+08',null
  )
) insert into restore_ids select 'replacement',transfer_id from x;
create temporary table settlement_conflict_before on commit drop as
select a.financial_version,b.amount debt
from public.activities a join public.bilateral_debts b on b.activity_id=a.id
where a.id='fa000000-0000-0000-0000-000000000001';
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000002');
do $conflict$ begin
  begin
    perform * from public.restore_transfer((select object_id from restore_ids where label='settlement'),'duplicate payment');
    raise exception 'conflicting settlement restore succeeded';
  exception when check_violation then null; end;
end $conflict$;
select pg_temp.assert_true(
  (select is_voided from public.transfers where id=(select object_id from restore_ids where label='settlement'))
  and (select a.financial_version=s.financial_version from public.activities a cross join settlement_conflict_before s where a.id='fa000000-0000-0000-0000-000000000001')
  and (select b.amount=s.debt from public.bilateral_debts b cross join settlement_conflict_before s where b.activity_id='fa000000-0000-0000-0000-000000000001'),
  'conflicting restore rolls back fact, debt projection, and version'
);

-- Member without ownership and outsider are both rejected before mutation.
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000001');
select public.void_settlement_transfer((select object_id from restore_ids where label='replacement'),'permission checks');
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000003');
do $unauthorized$ begin
  begin
    perform * from public.restore_transfer((select object_id from restore_ids where label='replacement'),'third member attempt');
    raise exception 'unauthorized member restore succeeded';
  exception when insufficient_privilege then null; end;
end $unauthorized$;
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000004');
do $outsider$ begin
  begin
    perform * from public.restore_transfer((select object_id from restore_ids where label='replacement'),'outsider attempt');
    raise exception 'outsider restore succeeded';
  exception when insufficient_privilege then null; end;
end $outsider$;
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000001');
select pg_temp.assert_true(
  (select is_voided from public.transfers where id=(select object_id from restore_ids where label='replacement')),
  'permission failures keep the transfer voided'
);

-- Mixed prepayment restores its immutable settlement/funding split. A later
-- pure prepayment restores funding without inventing a settlement component.
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000001');
with x as (
  select * from public.create_expense(
    'fa200000-0000-0000-0000-000000000002','Prepayment debt',60,'CNY',1,'manual',
    '[{"participant_id":"fa300000-0000-0000-0000-000000000022","amount":"60"}]',
    '[{"participant_id":"fa300000-0000-0000-0000-000000000021","amount":"60"}]',
    '{}','2026-09-08 09:00+08',null,null
  )
) insert into restore_ids select 'prepayment_expense',expense_id from x;
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000002');
with x as (
  select * from public.create_prepayment(
    'fa000000-0000-0000-0000-000000000002',
    'fa300000-0000-0000-0000-000000000021',
    'fa300000-0000-0000-0000-000000000022',100,'2026-09-08 10:00+08',null
  )
) insert into restore_ids select 'mixed_prepayment',transfer_id from x;
select public.void_prepayment_transfer((select object_id from restore_ids where label='mixed_prepayment'),'mixed void');
create temporary table mixed_before_restore on commit drop as
select financial_version from public.activities where id='fa000000-0000-0000-0000-000000000002';
create temporary table mixed_restore_result on commit drop as
select * from public.restore_transfer(
  (select object_id from restore_ids where label='mixed_prepayment'),'mixed restore'
);
select pg_temp.assert_true(
  (select restored and financial_version=(select financial_version+1 from mixed_before_restore)
   from mixed_restore_result)
  and (select count(*)=2 and bool_and((component_type='settlement' and amount=60) or (component_type='prepayment' and amount=40))
       from public.transfer_components where transfer_id=(select object_id from restore_ids where label='mixed_prepayment'))
  and (select balance=40 from public.prepayment_accounts
       where activity_id='fa000000-0000-0000-0000-000000000002'),
  'mixed prepayment restores original components and increments once'
);
with x as (
  select * from public.create_prepayment(
    'fa000000-0000-0000-0000-000000000002',
    'fa300000-0000-0000-0000-000000000021',
    'fa300000-0000-0000-0000-000000000022',30,'2026-09-08 11:00+08',null
  )
) insert into restore_ids select 'pure_prepayment',transfer_id from x;
select public.void_prepayment_transfer((select object_id from restore_ids where label='pure_prepayment'),'pure void');
create temporary table pure_restore_result on commit drop as
select * from public.restore_transfer(
  (select object_id from restore_ids where label='pure_prepayment'),'pure restore'
);
select pg_temp.assert_true(
  (select restored from pure_restore_result)
  and (select count(*)=1 and bool_and(component_type='prepayment' and amount=30)
       from public.transfer_components where transfer_id=(select object_id from restore_ids where label='pure_prepayment'))
  and (select balance=70 from public.prepayment_accounts
       where activity_id='fa000000-0000-0000-0000-000000000002'),
  'pure prepayment restores funding without component resplitting'
);

-- Return restore succeeds against available balance, then fails atomically
-- after a later return consumes that capacity.
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000001');
with x as (
  select * from public.create_prepayment_return(
    'fa000000-0000-0000-0000-000000000002',
    'fa300000-0000-0000-0000-000000000021',
    'fa300000-0000-0000-0000-000000000022',20,'2026-09-08 12:00+08',null
  )
) insert into restore_ids select 'prepayment_return',transfer_id from x;
select public.void_prepayment_transfer((select object_id from restore_ids where label='prepayment_return'),'return void');
create temporary table return_restore_result on commit drop as
select * from public.restore_transfer(
  (select object_id from restore_ids where label='prepayment_return'),'return restore'
);
select pg_temp.assert_true(
  (select restored from return_restore_result)
  and (select balance=50 from public.prepayment_accounts where activity_id='fa000000-0000-0000-0000-000000000002'),
  'prepayment return restores when current balance covers it'
);
select public.void_prepayment_transfer((select object_id from restore_ids where label='prepayment_return'),'return replacement');
with x as (
  select * from public.create_prepayment_return(
    'fa000000-0000-0000-0000-000000000002',
    'fa300000-0000-0000-0000-000000000021',
    'fa300000-0000-0000-0000-000000000022',60,'2026-09-08 13:00+08',null
  )
) insert into restore_ids select 'replacement_return',transfer_id from x;
create temporary table return_conflict_before on commit drop as
select a.financial_version,pa.balance
from public.activities a join public.prepayment_accounts pa on pa.activity_id=a.id
where a.id='fa000000-0000-0000-0000-000000000002';
do $return_conflict$ begin
  begin
    perform * from public.restore_transfer((select object_id from restore_ids where label='prepayment_return'),'insufficient return balance');
    raise exception 'insufficient return restore succeeded';
  exception when check_violation then null; end;
end $return_conflict$;
select pg_temp.assert_true(
  (select is_voided from public.transfers where id=(select object_id from restore_ids where label='prepayment_return'))
  and (select a.financial_version=r.financial_version from public.activities a cross join return_conflict_before r where a.id='fa000000-0000-0000-0000-000000000002')
  and (select pa.balance=r.balance from public.prepayment_accounts pa cross join return_conflict_before r where pa.activity_id='fa000000-0000-0000-0000-000000000002'),
  'insufficient return restore is atomic'
);

-- Final settlement restore must match endpoint total, both immutable
-- components, and the persisted path hop. Consuming part of the return balance
-- makes the old final item stale without mutating it.
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000002');
with x as (
  select * from public.create_prepayment(
    'fa000000-0000-0000-0000-000000000003',
    'fa300000-0000-0000-0000-000000000031',
    'fa300000-0000-0000-0000-000000000032',10,'2026-09-08 09:00+08',null
  )
) insert into restore_ids select 'final_funding',transfer_id from x;
with x as (
  select * from public.create_expense(
    'fa200000-0000-0000-0000-000000000003','Final ordinary debt',20,'CNY',1,'manual',
    '[{"participant_id":"fa300000-0000-0000-0000-000000000031","amount":"20"}]',
    '[{"participant_id":"fa300000-0000-0000-0000-000000000032","amount":"20"}]',
    '{}','2026-09-08 10:00+08',null,null
  )
) insert into restore_ids select 'final_expense',expense_id from x;
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000001');
with x as (
  select * from public.create_final_settlement(
    'fa000000-0000-0000-0000-000000000003',
    'fa300000-0000-0000-0000-000000000032',
    'fa300000-0000-0000-0000-000000000031',30,'2026-09-08 11:00+08',null
  )
) insert into restore_ids select 'final_settlement',transfer_id from x;
select public.void_prepayment_transfer((select object_id from restore_ids where label='final_settlement'),'final void');
create temporary table final_before_restore on commit drop as
select financial_version from public.activities where id='fa000000-0000-0000-0000-000000000003';
create temporary table final_restore_result on commit drop as
select * from public.restore_transfer(
  (select object_id from restore_ids where label='final_settlement'),'final restore'
);
select pg_temp.assert_true(
  (select restored and financial_version=(select financial_version+1 from final_before_restore)
   from final_restore_result)
  and (select count(*)=2 and bool_and((component_type='settlement' and amount=20) or (component_type='prepayment_return' and amount=10))
       from public.transfer_components where transfer_id=(select object_id from restore_ids where label='final_settlement'))
  and (select count(*)=2 and count(*) filter(where component_type='settlement' and amount=20)=1
       and count(*) filter(where component_type='prepayment_return' and amount=10)=1
       from public.final_settlement_paths where transfer_id=(select object_id from restore_ids where label='final_settlement')),
  'matching final settlement restores components and persisted paths once'
);
select public.void_prepayment_transfer((select object_id from restore_ids where label='final_settlement'),'make final stale');
with x as (
  select * from public.create_prepayment_return(
    'fa000000-0000-0000-0000-000000000003',
    'fa300000-0000-0000-0000-000000000031',
    'fa300000-0000-0000-0000-000000000032',5,'2026-09-08 12:00+08',null
  )
) insert into restore_ids select 'final_partial_return',transfer_id from x;
create temporary table final_stale_before on commit drop as
select financial_version from public.activities where id='fa000000-0000-0000-0000-000000000003';
do $final_stale$ begin
  begin
    perform * from public.restore_transfer((select object_id from restore_ids where label='final_settlement'),'stale final retry');
    raise exception 'stale final settlement restore succeeded';
  exception when check_violation then null; end;
end $final_stale$;
select pg_temp.assert_true(
  (select is_voided from public.transfers where id=(select object_id from restore_ids where label='final_settlement'))
  and (select a.financial_version=f.financial_version from public.activities a cross join final_stale_before f where a.id='fa000000-0000-0000-0000-000000000003')
  and (select count(*)=2 from public.final_settlement_paths where transfer_id=(select object_id from restore_ids where label='final_settlement')),
  'stale final restore keeps the immutable fact and paths unchanged'
);

-- Archived Activities are read-only even for the original recorder.
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000001');
select * from public.archive_activity('fa000000-0000-0000-0000-000000000001');
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000002');
do $archived$ begin
  begin
    perform * from public.restore_transfer((select object_id from restore_ids where label='settlement'),'archived retry');
    raise exception 'archived restore succeeded';
  exception when object_not_in_prerequisite_state then null; end;
end $archived$;

reset role;
select pg_temp.assert_true(
  not has_function_privilege('anon','public.restore_transfer(uuid,text)','EXECUTE')
  and has_function_privilege('authenticated','public.restore_transfer(uuid,text)','EXECUTE')
  and (select not p.prosecdef from pg_proc p where p.oid='public.restore_transfer(uuid,text)'::regprocedure)
  and (select p.prosecdef from pg_proc p where p.oid='private.restore_transfer_impl(uuid,text)'::regprocedure)
  and not has_table_privilege('authenticated','public.transfers','UPDATE')
  and not has_table_privilege('authenticated','public.transfer_components','INSERT,UPDATE,DELETE')
  and exists(select 1 from pg_constraint where conrelid='public.audit_logs'::regclass and conname='audit_logs_action_check' and pg_get_constraintdef(oid) like '%transfer.restore%'),
  'restore RPC preserves wrapper/definer permissions and direct-DML boundary'
);

select pass('Transfer restore contract assertions');
select * from extensions.finish();
rollback;
