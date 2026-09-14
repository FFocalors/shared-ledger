\set ON_ERROR_STOP on

begin;

create extension if not exists pgtap with schema extensions;
select extensions.plan(1);

create function pg_temp.assert_true(p_condition boolean, p_message text)
returns void language plpgsql as $function$
begin
  if p_condition is not true then
    raise exception 'assertion failed: %', p_message;
  end if;
end;
$function$;

create function pg_temp.authenticate(p_user uuid) returns void
language plpgsql as $function$
begin
  perform set_config('request.jwt.claims',
    json_build_object('sub',p_user,'role','authenticated')::text,true);
end;
$function$;

insert into auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,
  raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
values
 ('00000000-0000-0000-0000-000000000000','fa100000-0000-0000-0000-000000000101','authenticated','authenticated','subdel.creator@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','fa100000-0000-0000-0000-000000000102','authenticated','authenticated','subdel.member@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','fa100000-0000-0000-0000-000000000103','authenticated','authenticated','subdel.outsider@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());

insert into public.activities(id,join_code,name,type,base_currency,created_by)
values
 ('fa000000-0000-0000-0000-000000000101','98100101','Sub delete large','large','CNY','fa100000-0000-0000-0000-000000000101'),
 ('fa000000-0000-0000-0000-000000000102','98100102','Sub delete normal','normal','CNY','fa100000-0000-0000-0000-000000000101'),
 ('fa000000-0000-0000-0000-000000000103','98100103','Sub delete archived','large','CNY','fa100000-0000-0000-0000-000000000101'),
 ('fa000000-0000-0000-0000-000000000104','98100104','Sub delete removed','large','CNY','fa100000-0000-0000-0000-000000000101');

insert into public.activity_members(activity_id,user_id)
select a.id,u.id from public.activities a cross join auth.users u
where a.id in ('fa000000-0000-0000-0000-000000000101','fa000000-0000-0000-0000-000000000102','fa000000-0000-0000-0000-000000000103','fa000000-0000-0000-0000-000000000104')
  and u.id in ('fa100000-0000-0000-0000-000000000101','fa100000-0000-0000-0000-000000000102');

insert into public.ledger_units(id,activity_id,name,type) values
 ('fa200000-0000-0000-0000-000000000101','fa000000-0000-0000-0000-000000000101','Large root','root'),
 ('fa200000-0000-0000-0000-000000000102','fa000000-0000-0000-0000-000000000101','Sub unit','sub_activity'),
 ('fa200000-0000-0000-0000-000000000103','fa000000-0000-0000-0000-000000000101','Deleted sub unit','sub_activity'),
 ('fa200000-0000-0000-0000-000000000104','fa000000-0000-0000-0000-000000000102','Normal default','default'),
 ('fa200000-0000-0000-0000-000000000105','fa000000-0000-0000-0000-000000000103','Archived root','root'),
 ('fa200000-0000-0000-0000-000000000106','fa000000-0000-0000-0000-000000000103','Archived sub','sub_activity'),
 ('fa200000-0000-0000-0000-000000000107','fa000000-0000-0000-0000-000000000104','Removed root','root'),
 ('fa200000-0000-0000-0000-000000000108','fa000000-0000-0000-0000-000000000104','Removed sub','sub_activity');

update public.activities set archived_at=now() where id='fa000000-0000-0000-0000-000000000103';
update public.activities set is_deleted=true,deleted_at=now(),deleted_by='fa100000-0000-0000-0000-000000000101' where id='fa000000-0000-0000-0000-000000000104';

insert into public.participants(id,activity_id,name,participant_order) values
 ('fa300000-0000-0000-0000-000000000101','fa000000-0000-0000-0000-000000000101','Alice',0),
 ('fa300000-0000-0000-0000-000000000102','fa000000-0000-0000-0000-000000000101','Bob',1);
insert into public.participant_claims(activity_id,participant_id,user_id) values
 ('fa000000-0000-0000-0000-000000000101','fa300000-0000-0000-0000-000000000101','fa100000-0000-0000-0000-000000000101'),
 ('fa000000-0000-0000-0000-000000000101','fa300000-0000-0000-0000-000000000102','fa100000-0000-0000-0000-000000000102');

set local role authenticated;
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000102');

-- A prepayment is created before the sub-activity Expense, so its usage is
-- attached to that sub-activity after the Expense is created.
select * from public.create_prepayment(
  'fa000000-0000-0000-0000-000000000101',
  'fa300000-0000-0000-0000-000000000102',
  'fa300000-0000-0000-0000-000000000101',50,'2026-09-13 09:00+08',null);

select pg_temp.authenticate('fa100000-0000-0000-0000-000000000101');
create temporary table subdel_ids(label text primary key, object_id uuid not null) on commit drop;
with x as (
  select * from public.create_expense(
    'fa200000-0000-0000-0000-000000000102','Sub expense',100,'CNY',1,'manual',
    '[{"participant_id":"fa300000-0000-0000-0000-000000000102","amount":"100"}]',
    '[{"participant_id":"fa300000-0000-0000-0000-000000000101","amount":"100"}]',
    '{}','2026-09-13 10:00+08',null,null)
) insert into subdel_ids select 'expense',expense_id from x;

-- A settlement creates a TransferAllocation against the sub-activity debt.
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000102');
with x as (
  select * from public.create_settlement_transfer(
    'fa000000-0000-0000-0000-000000000101',
    'fa300000-0000-0000-0000-000000000102',
    'fa300000-0000-0000-0000-000000000101',30,'2026-09-13 11:00+08',null)
) insert into subdel_ids select 'transfer',transfer_id from x;

reset role;
insert into public.attachments(
  id,activity_id,ledger_unit_id,expense_id,original_filename,mime_type,
  storage_path,status,uploaded_by)
values(
  'fa400000-0000-0000-0000-000000000101',
  'fa000000-0000-0000-0000-000000000101',
  'fa200000-0000-0000-0000-000000000102',
  (select object_id from subdel_ids where label='expense'),
  'receipt.jpg','image/jpeg','subdel/receipt.jpg','pending',
  'fa100000-0000-0000-0000-000000000101');

set local role authenticated;
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000102');
create temporary table delete_result on commit drop as
select * from public.delete_sub_activity('fa200000-0000-0000-0000-000000000102');
select pg_temp.assert_true(
  (select changed and is_deleted and financial_version=4 from delete_result)
  and (select is_deleted and deleted_by='fa100000-0000-0000-0000-000000000102' from public.ledger_units where id='fa200000-0000-0000-0000-000000000102')
  and (select count(*)=0 from public.expense_debts where expense_id=(select object_id from subdel_ids where label='expense'))
  and (select count(*)=0 from public.transfer_allocations where transfer_id=(select object_id from subdel_ids where label='transfer'))
  and (select count(*)=0 from public.prepayment_usages where activity_id='fa000000-0000-0000-0000-000000000101')
  and (select count(*)=0 from public.bilateral_debts where activity_id='fa000000-0000-0000-0000-000000000101')
  and (select count(*)=0 from public.preview_final_settlement('fa000000-0000-0000-0000-000000000101'))
  and (select count(*)=1 from public.attachments where id='fa400000-0000-0000-0000-000000000101')
  and (select count(*)=1 from public.expenses where id=(select object_id from subdel_ids where label='expense'))
  and (select count(*)=1 from public.transfer_components where transfer_id=(select object_id from subdel_ids where label='transfer')),
  'member delete soft-deletes unit, rebuilds all financial projections, and preserves facts/attachment');

create temporary table delete_retry on commit drop as
select * from public.delete_sub_activity('fa200000-0000-0000-0000-000000000102');
select pg_temp.assert_true(
  (select not changed and is_deleted and financial_version=4 from delete_retry)
  and (select financial_version=4 from public.activities where id='fa000000-0000-0000-0000-000000000101'),
  'delete is idempotent and version-neutral');

-- A non-creator member can restore. The projection chain and final settlement
-- preview become consistent with the restored unit again.
select pg_temp.authenticate('fa100000-0000-0000-0000-000000000101');
create temporary table restore_result on commit drop as
select * from public.restore_sub_activity('fa200000-0000-0000-0000-000000000102');
select pg_temp.assert_true(
  (select changed and not is_deleted and financial_version=5 from restore_result)
  and (select count(*)=1 from public.expense_debts where expense_id=(select object_id from subdel_ids where label='expense'))
  and (select count(*)=1 and sum(amount)=30 from public.transfer_allocations where transfer_id=(select object_id from subdel_ids where label='transfer'))
  and (select count(*)=1 and sum(amount)=50 from public.prepayment_usages where activity_id='fa000000-0000-0000-0000-000000000101')
  and (select count(*)=1 from public.preview_final_settlement('fa000000-0000-0000-0000-000000000101')),
  'restore rebuilds Expense debt, Transfer allocation, prepayment usage, bilateral debt, and final preview');

create temporary table restore_retry on commit drop as
select * from public.restore_sub_activity('fa200000-0000-0000-0000-000000000102');
select pg_temp.assert_true(
  (select not changed and not is_deleted and financial_version=5 from restore_retry)
  and (select count(*)=1 from public.audit_logs where entity_id='fa200000-0000-0000-0000-000000000102' and action='ledger_unit.delete')
  and (select count(*)=1 from public.audit_logs where entity_id='fa200000-0000-0000-0000-000000000102' and action='ledger_unit.restore'),
  'restore is idempotent and adds exactly one lifecycle audit event per transition');

select pg_temp.authenticate('fa100000-0000-0000-0000-000000000103');
do $outsider$ begin
  begin perform * from public.delete_sub_activity('fa200000-0000-0000-0000-000000000102'); raise exception 'outsider delete succeeded';
  exception when insufficient_privilege then null; end;
end $outsider$;

select pg_temp.authenticate('fa100000-0000-0000-0000-000000000101');
do $invalid_units$ begin
  begin perform * from public.delete_sub_activity('fa200000-0000-0000-0000-000000000101'); raise exception 'root delete succeeded';
  exception when invalid_parameter_value then null; when raise_exception then
    if sqlerrm <> 'only a large activity sub-activity may be changed' then raise; end if;
  end;
  begin perform * from public.delete_sub_activity('fa200000-0000-0000-0000-000000000104'); raise exception 'normal default delete succeeded';
  exception when invalid_parameter_value then null; when raise_exception then
    if sqlerrm <> 'only a large activity sub-activity may be changed' then raise; end if;
  end;
end $invalid_units$;

do $lifecycle$ begin
  begin perform * from public.delete_sub_activity('fa200000-0000-0000-0000-000000000106'); raise exception 'archived delete succeeded';
  exception when object_not_in_prerequisite_state then null; end;
  begin perform * from public.restore_sub_activity('fa200000-0000-0000-0000-000000000108'); raise exception 'deleted activity restore succeeded';
  exception when no_data_found then null; when raise_exception then
    if sqlerrm <> 'activity was not found' then raise; end if;
  end;
end $lifecycle$;

reset role;
select pg_temp.assert_true(
  has_function_privilege('authenticated','public.delete_sub_activity(uuid)','EXECUTE')
  and has_function_privilege('authenticated','public.restore_sub_activity(uuid)','EXECUTE')
  and not has_function_privilege('anon','public.delete_sub_activity(uuid)','EXECUTE')
  and not has_table_privilege('authenticated','public.ledger_units','UPDATE')
  and exists(select 1 from pg_constraint where conrelid='public.audit_logs'::regclass
    and conname='audit_logs_action_check' and pg_get_constraintdef(oid) like '%ledger_unit.delete%'),
  'RPC-only permissions and ledger-unit audit actions are installed');

select pass('Sub-activity delete/restore contract assertions');
select * from extensions.finish();
rollback;
