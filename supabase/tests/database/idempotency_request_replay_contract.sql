\set ON_ERROR_STOP on

begin;
create extension if not exists pgtap with schema extensions;
select extensions.plan(11);

create function pg_temp.authenticate(p_user uuid) returns void language plpgsql as $function$
begin
  perform set_config('request.jwt.claims',json_build_object('sub',p_user,'role','authenticated')::text,true);
end;
$function$;

insert into auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
values
 ('00000000-0000-0000-0000-000000000000','e6100000-0000-0000-0000-000000000001','authenticated','authenticated','replay.a@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','e6100000-0000-0000-0000-000000000002','authenticated','authenticated','replay.b@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());
insert into public.activities(id,join_code,name,type,base_currency,created_by)
values ('e6000000-0000-0000-0000-000000000001','96000101','Request replay','normal','CNY','e6100000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id) values
 ('e6000000-0000-0000-0000-000000000001','e6100000-0000-0000-0000-000000000001'),
 ('e6000000-0000-0000-0000-000000000001','e6100000-0000-0000-0000-000000000002');
insert into public.ledger_units(id,activity_id,name,type)
values ('e6200000-0000-0000-0000-000000000001','e6000000-0000-0000-0000-000000000001','default','default');
insert into public.participants(id,activity_id,name,participant_order) values
 ('e6300000-0000-0000-0000-000000000001','e6000000-0000-0000-0000-000000000001','A',0),
 ('e6300000-0000-0000-0000-000000000002','e6000000-0000-0000-0000-000000000001','B',1);
insert into public.participant_claims(activity_id,participant_id,user_id) values
 ('e6000000-0000-0000-0000-000000000001','e6300000-0000-0000-0000-000000000001','e6100000-0000-0000-0000-000000000001'),
 ('e6000000-0000-0000-0000-000000000001','e6300000-0000-0000-0000-000000000002','e6100000-0000-0000-0000-000000000002');

create temporary table replay_results(
  label text primary key, transfer_id uuid not null, amount numeric not null,
  currency character(3) not null, new_balance numeric not null, financial_version bigint not null
) on commit drop;
grant select,insert,update,delete on replay_results to authenticated,service_role;
create temporary table replay_context(request_version bigint) on commit drop;
insert into replay_context select financial_version from public.activities where id='e6000000-0000-0000-0000-000000000001';
grant select on replay_context to authenticated,service_role;

set local role authenticated;
select pg_temp.authenticate('e6100000-0000-0000-0000-000000000001');
with result as (
  select * from public.create_prepayment_v2(
    'e6000000-0000-0000-0000-000000000001','e6300000-0000-0000-0000-000000000001',
    'e6300000-0000-0000-0000-000000000002',10,'CNY','2026-09-23 09:00:00+00',null,(select request_version from replay_context),
    'e6400000-0000-0000-0000-000000000001'
  )
)
insert into replay_results
select 'original',transfer_id,prepayment_amount,currency,new_balance,financial_version from result;
select extensions.ok((select amount=10 and currency='CNY' and new_balance=10
  and financial_version=(select request_version+1 from replay_context) from replay_results where label='original'),
  'the original successful request records its exact result');

with result as (
  select * from public.create_prepayment_v2(
    'e6000000-0000-0000-0000-000000000001','e6300000-0000-0000-0000-000000000001',
    'e6300000-0000-0000-0000-000000000002',10,'CNY','2026-09-23 09:00:00+00',null,(select request_version from replay_context),
    'e6400000-0000-0000-0000-000000000001'
  )
)
insert into replay_results
select 'same_actor_retry',transfer_id,prepayment_amount,currency,new_balance,financial_version from result;
select extensions.ok((select o.transfer_id=r.transfer_id and o.amount=r.amount and o.currency=r.currency
  and o.new_balance=r.new_balance and o.financial_version=r.financial_version
  from replay_results o cross join replay_results r where o.label='original' and r.label='same_actor_retry'),
  'an exact retry with the original version returns the stored result');

select extensions.throws_ok($$select * from public.create_prepayment_v2(
  'e6000000-0000-0000-0000-000000000001','e6300000-0000-0000-0000-000000000001',
  'e6300000-0000-0000-0000-000000000002',11,'CNY','2026-09-23 09:00:00+00',null,(select request_version from replay_context),
  'e6400000-0000-0000-0000-000000000001')$$,
  '23505',null,'a reused request_id with changed payload is rejected');

select pg_temp.authenticate('e6100000-0000-0000-0000-000000000002');
select extensions.throws_ok($$select * from public.create_prepayment_v2(
  'e6000000-0000-0000-0000-000000000001','e6300000-0000-0000-0000-000000000001',
  'e6300000-0000-0000-0000-000000000002',10,'CNY','2026-09-23 09:00:00+00',null,(select request_version from replay_context),
  'e6400000-0000-0000-0000-000000000001')$$,
  '23505',null,'the same request_id cannot be replayed by another activity member');

select pg_temp.authenticate('e6100000-0000-0000-0000-000000000001');
select extensions.throws_ok($$select * from public.create_prepayment_return_v2(
  'e6000000-0000-0000-0000-000000000001','e6300000-0000-0000-0000-000000000001',
  'e6300000-0000-0000-0000-000000000002',1,'CNY','2026-09-23 09:00:00+00',null,(select request_version from replay_context),
  'e6400000-0000-0000-0000-000000000001')$$,
  '23505',null,'the same request_id cannot be reused for another operation');

select extensions.ok((select archived and changed from public.archive_activity('e6000000-0000-0000-0000-000000000001')),
  'the successful request Activity can be archived');
with result as (
  select * from public.create_prepayment_v2(
    'e6000000-0000-0000-0000-000000000001','e6300000-0000-0000-0000-000000000001',
    'e6300000-0000-0000-0000-000000000002',10,'CNY','2026-09-23 09:00:00+00',null,(select request_version from replay_context),
    'e6400000-0000-0000-0000-000000000001'
  )
)
insert into replay_results
select 'archived_retry',transfer_id,prepayment_amount,currency,new_balance,financial_version from result;
select extensions.ok((select o.transfer_id=r.transfer_id and o.amount=r.amount and o.currency=r.currency
  and o.new_balance=r.new_balance and o.financial_version=r.financial_version
  from replay_results o cross join replay_results r where o.label='original' and r.label='archived_retry'),
  'an archived Activity retry returns the original successful result');
select extensions.ok((select count(*)=1 from public.transfers
  where activity_id='e6000000-0000-0000-0000-000000000001' and request_id='e6400000-0000-0000-0000-000000000001'),
  'same-key replays create no duplicate transfer');

select extensions.ok((select not archived and changed from public.unarchive_activity('e6000000-0000-0000-0000-000000000001')),
  'the Activity can be unarchived for the deleted-lifecycle retry check');
select extensions.ok(public.delete_activity('e6000000-0000-0000-0000-000000000001'),
  'the creator can logically delete the Activity after the request succeeds');
with result as (
  select * from public.create_prepayment_v2(
    'e6000000-0000-0000-0000-000000000001','e6300000-0000-0000-0000-000000000001',
    'e6300000-0000-0000-0000-000000000002',10,'CNY','2026-09-23 09:00:00+00',null,(select request_version from replay_context),
    'e6400000-0000-0000-0000-000000000001'
  )
)
insert into replay_results
select 'deleted_retry',transfer_id,prepayment_amount,currency,new_balance,financial_version from result;
select extensions.ok((select o.transfer_id=r.transfer_id and o.amount=r.amount and o.currency=r.currency
  and o.new_balance=r.new_balance and o.financial_version=r.financial_version
  from replay_results o cross join replay_results r where o.label='original' and r.label='deleted_retry'),
  'a logically deleted Activity retry still returns the original successful result');

select * from extensions.finish();
rollback;
