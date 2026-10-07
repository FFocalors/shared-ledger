\set ON_ERROR_STOP on

begin;
\ir legacy_rpc_fixture_adapters.sql
create extension if not exists pgtap with schema extensions;
select extensions.plan(13);

create function pg_temp.authenticate(p_user uuid) returns void language plpgsql as $function$
begin
  perform set_config('request.jwt.claims', json_build_object('sub',p_user,'role','authenticated')::text, true);
end;
$function$;

create function pg_temp.legacy_create_prepayment_fixture(
  p_activity_id uuid, p_owner uuid, p_custodian uuid, p_amount numeric(20,1)
)
returns table(transfer_id uuid, settlement_amount numeric, prepayment_amount numeric, currency character(3), financial_version bigint)
language sql security definer set search_path=''
as $function$
  select * from public.create_prepayment(p_activity_id,p_owner,p_custodian,p_amount,pg_catalog.now(),null)
$function$;

insert into auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
values
 ('00000000-0000-0000-0000-000000000000','a1000000-0000-0000-0000-000000000001','authenticated','authenticated','normal-prepay-owner@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','a1000000-0000-0000-0000-000000000002','authenticated','authenticated','normal-prepay-member@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());

insert into public.activities(id,join_code,name,type,base_currency,created_by) values
 ('a1100000-0000-0000-0000-000000000001','99100001','ordinary prepayment guard','normal','CNY','a1000000-0000-0000-0000-000000000001'),
 ('a1100000-0000-0000-0000-000000000002','99100002','large downgrade guard','large','CNY','a1000000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id)
select a.id,u.id from public.activities a cross join auth.users u
where a.id in ('a1100000-0000-0000-0000-000000000001','a1100000-0000-0000-0000-000000000002')
  and u.id in ('a1000000-0000-0000-0000-000000000001','a1000000-0000-0000-0000-000000000002');
insert into public.ledger_units(id,activity_id,name,type) values
 ('a1200000-0000-0000-0000-000000000001','a1100000-0000-0000-0000-000000000001','ordinary ledger','default'),
 ('a1200000-0000-0000-0000-000000000002','a1100000-0000-0000-0000-000000000002','large root','root');
insert into public.participants(id,activity_id,name,participant_order) values
 ('a1300000-0000-0000-0000-000000000001','a1100000-0000-0000-0000-000000000001','Custodian',0),
 ('a1300000-0000-0000-0000-000000000002','a1100000-0000-0000-0000-000000000001','Owner',1),
 ('a1300000-0000-0000-0000-000000000003','a1100000-0000-0000-0000-000000000002','Large owner',0),
 ('a1300000-0000-0000-0000-000000000004','a1100000-0000-0000-0000-000000000002','Large custodian',1);
insert into public.participant_claims(activity_id,participant_id,user_id) values
 ('a1100000-0000-0000-0000-000000000001','a1300000-0000-0000-0000-000000000001','a1000000-0000-0000-0000-000000000001'),
 ('a1100000-0000-0000-0000-000000000001','a1300000-0000-0000-0000-000000000002','a1000000-0000-0000-0000-000000000002');

set local role authenticated;
select pg_temp.authenticate('a1000000-0000-0000-0000-000000000001');
create temporary table normal_prepayment_ids(label text primary key, object_id uuid not null) on commit drop;
with x as (
  select * from pg_temp.create_expense_fixture(
    'a1200000-0000-0000-0000-000000000001','ordinary debt',10,'CNY',1,'manual'::public.expense_split_method,
    '[{"participant_id":"a1300000-0000-0000-0000-000000000001","amount":"10"}]',
    '[{"participant_id":"a1300000-0000-0000-0000-000000000002","amount":"10"}]',
    '{}'::uuid[],now(),null,null,'money'
  )
)
insert into normal_prepayment_ids select 'expense',expense_id from x;

select extensions.throws_ok($$select * from public.preview_prepayment(
  'a1100000-0000-0000-0000-000000000001','a1300000-0000-0000-0000-000000000002',
  'a1300000-0000-0000-0000-000000000001',5,'CNY')$$,
  '23514','普通活动不支持预存','ordinary prepayment preview returns the contract error');
select extensions.throws_ok($$select * from public.create_prepayment_v2(
  'a1100000-0000-0000-0000-000000000001','a1300000-0000-0000-0000-000000000002',
  'a1300000-0000-0000-0000-000000000001',5,'CNY',now(),null,1,'a1400000-0000-0000-0000-000000000001')$$,
  '23514','普通活动不支持预存','ordinary prepayment rejects even when the entire amount would settle debt');
select extensions.throws_ok($$select * from public.create_prepayment_v2(
  'a1100000-0000-0000-0000-000000000001','a1300000-0000-0000-0000-000000000002',
  'a1300000-0000-0000-0000-000000000001',15,'CNY',now(),null,1,'a1400000-0000-0000-0000-000000000002')$$,
  '23514','普通活动不支持预存','ordinary mixed settlement and prepayment request is rejected atomically');
select extensions.throws_ok($$select * from public.create_prepayment_return_v2(
  'a1100000-0000-0000-0000-000000000001','a1300000-0000-0000-0000-000000000002',
  'a1300000-0000-0000-0000-000000000001',1,'CNY',now(),null,1,'a1400000-0000-0000-0000-000000000003')$$,
  '23514','普通活动不支持预存','ordinary v2 return returns the contract error before checking an absent account');
select extensions.throws_ok($$select * from pg_temp.legacy_create_prepayment_fixture(
  'a1100000-0000-0000-0000-000000000001','a1300000-0000-0000-0000-000000000002',
  'a1300000-0000-0000-0000-000000000001',5)$$,
  '23514','普通活动不支持预存','legacy prepayment RPC is covered');
select extensions.throws_ok($$select * from pg_temp.create_prepayment_return_fixture(
  'a1100000-0000-0000-0000-000000000001','a1300000-0000-0000-0000-000000000002',
  'a1300000-0000-0000-0000-000000000001',1,now(),null)$$,
  '23514','普通活动不支持预存','legacy return RPC is covered');

select extensions.ok(
  (select financial_version=1 from public.activities where id='a1100000-0000-0000-0000-000000000001')
  and not exists (select 1 from public.transfers where activity_id='a1100000-0000-0000-0000-000000000001' and type in ('prepayment','prepayment_return'))
  and not exists (select 1 from public.transfer_components where activity_id='a1100000-0000-0000-0000-000000000001' and component_type in ('prepayment','prepayment_return'))
  and not exists (select 1 from public.prepayment_accounts where activity_id='a1100000-0000-0000-0000-000000000001')
  and not exists (select 1 from public.prepayment_usages where activity_id='a1100000-0000-0000-0000-000000000001'),
  'ordinary rejections preserve facts, projections and financial version');
select extensions.ok(exists (
  select 1 from public.preview_final_settlement_v2('a1100000-0000-0000-0000-000000000001','base_unified') p
  where p.ordinary_amount=10 and p.prepayment_return_amount=0 and not p.is_prepayment_return
), 'ordinary final settlement still previews bilateral debt without a prepayment return');

select extensions.ok((select settlement_amount=0 and prepayment_amount=1 and new_balance=1 and financial_version=0
  from public.preview_prepayment('a1100000-0000-0000-0000-000000000002',
    'a1300000-0000-0000-0000-000000000003','a1300000-0000-0000-0000-000000000004',1,'CNY')),
  'large-activity preview remains valid and side-effect free');
select extensions.ok((select count(*)=1 from public.create_prepayment_v2(
  'a1100000-0000-0000-0000-000000000002','a1300000-0000-0000-0000-000000000003',
  'a1300000-0000-0000-0000-000000000004',1,'CNY',now(),null,0,'a1400000-0000-0000-0000-000000000004')),
  'large activity funding remains valid');
select extensions.throws_ok($$update public.activities set type='normal' where id='a1100000-0000-0000-0000-000000000002'$$,
  '42501','permission denied for table activities','authenticated clients cannot directly change activity type');
set local role service_role;
select extensions.throws_ok($$update public.activities set type='normal' where id='a1100000-0000-0000-0000-000000000002'$$,
  '23514','普通活动不支持预存','creator cannot downgrade an activity with prepayment facts');
set local role authenticated;
select extensions.ok(
  (select type='large' and financial_version=1 from public.activities where id='a1100000-0000-0000-0000-000000000002')
  and (select count(*)=1 from public.transfers where activity_id='a1100000-0000-0000-0000-000000000002' and type='prepayment')
  and (select count(*)=1 from public.prepayment_accounts where activity_id='a1100000-0000-0000-0000-000000000002'),
  'failed type downgrade preserves the large activity and its account');

select * from extensions.finish();
rollback;
