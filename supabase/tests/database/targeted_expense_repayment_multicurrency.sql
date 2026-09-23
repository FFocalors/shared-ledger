\set ON_ERROR_STOP on

begin;

\ir legacy_rpc_fixture_adapters.sql
create extension if not exists pgtap with schema extensions;
select extensions.plan(4);

create function pg_temp.authenticate(p_user_id uuid)
returns void language plpgsql as $function$
begin
  perform set_config('request.jwt.claims',
    json_build_object('sub',p_user_id,'role','authenticated')::text,true);
end;
$function$;

insert into auth.users(
  instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,
  raw_app_meta_data,raw_user_meta_data,created_at,updated_at
)
values
  ('00000000-0000-0000-0000-000000000000','f8100000-0000-0000-0000-000000000001',
   'authenticated','authenticated','targeted.fx.a@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
  ('00000000-0000-0000-0000-000000000000','f8100000-0000-0000-0000-000000000002',
   'authenticated','authenticated','targeted.fx.b@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());
insert into public.activities(id,join_code,name,type,base_currency,multi_currency_enabled,created_by)
values ('f8000000-0000-0000-0000-000000000001','98000001','Targeted FX','normal','CNY',true,
        'f8100000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id)
values ('f8000000-0000-0000-0000-000000000001','f8100000-0000-0000-0000-000000000001'),
       ('f8000000-0000-0000-0000-000000000001','f8100000-0000-0000-0000-000000000002');
insert into public.ledger_units(id,activity_id,name,type)
values ('f8200000-0000-0000-0000-000000000001','f8000000-0000-0000-0000-000000000001','Main','default');
insert into public.participants(id,activity_id,name,participant_order)
values ('f8300000-0000-0000-0000-000000000001','f8000000-0000-0000-0000-000000000001','A',0),
       ('f8300000-0000-0000-0000-000000000002','f8000000-0000-0000-0000-000000000001','B',1);
insert into public.participant_claims(activity_id,participant_id,user_id)
values ('f8000000-0000-0000-0000-000000000001','f8300000-0000-0000-0000-000000000001','f8100000-0000-0000-0000-000000000001'),
       ('f8000000-0000-0000-0000-000000000001','f8300000-0000-0000-0000-000000000002','f8100000-0000-0000-0000-000000000002');

set local role authenticated;
select pg_temp.authenticate('f8100000-0000-0000-0000-000000000001');
with x as (
  select * from pg_temp.create_expense_fixture(
    'f8200000-0000-0000-0000-000000000001','EUR bill',10,'EUR',8,
    'manual'::public.expense_split_method,
    '[{"participant_id":"f8300000-0000-0000-0000-000000000002","amount":"10"}]'::jsonb,
    '[{"participant_id":"f8300000-0000-0000-0000-000000000001","amount":"10"}]'::jsonb,
    '{}'::uuid[],'2026-09-05 09:00+08',null,null,'money'
  )
)
select expense_id into temporary table targeted_fx_ids from x;
select financial_version into temporary table targeted_fx_version
from public.activities where id='f8000000-0000-0000-0000-000000000001';

select extensions.ok(
  (select count(*)=1 and bool_and(debt_currency='EUR' and remaining_original_amount=10 and payment_currency_amount=10)
   from public.list_transfer_expense_candidates(
     'f8000000-0000-0000-0000-000000000001',
     'f8300000-0000-0000-0000-000000000001',
     'f8300000-0000-0000-0000-000000000002','EUR'))
  and (select count(*)=1 and bool_and(remaining_base_amount=80 and payment_currency_amount=80)
   from public.list_transfer_expense_candidates(
     'f8000000-0000-0000-0000-000000000001',
     'f8300000-0000-0000-0000-000000000001',
     'f8300000-0000-0000-0000-000000000002','CNY')),
  'foreign payment is restricted to own currency while base payment uses the FX snapshot'
);

select extensions.ok(
  (select payment_currency='EUR' and payment_amount=5 and original_currency='EUR'
      and original_amount=5 and base_amount=40 and fx_rate=8
   from public.preview_expense_repayment(
     'f8000000-0000-0000-0000-000000000001',
     'f8300000-0000-0000-0000-000000000001',
     'f8300000-0000-0000-0000-000000000002',5,'EUR','FIFO',null,
     (select financial_version from targeted_fx_version)))
  and (select payment_currency='CNY' and payment_amount=40 and original_currency='EUR'
      and original_amount=5 and base_amount=40 and fx_rate=8
   from public.preview_expense_repayment(
     'f8000000-0000-0000-0000-000000000001',
     'f8300000-0000-0000-0000-000000000001',
     'f8300000-0000-0000-0000-000000000002',40,'CNY','FIFO',null,
     (select financial_version from targeted_fx_version))),
  'same debt snapshots original/base/payment amounts for foreign and base previews'
);

with x as (
  select * from public.create_expense_repayment_v2(
    'f8000000-0000-0000-0000-000000000001',
    'f8300000-0000-0000-0000-000000000001',
    'f8300000-0000-0000-0000-000000000002',5,'EUR','FIFO',null,
    '2026-09-05 10:00+08',null,
    (select financial_version from targeted_fx_version),
    'f8400000-0000-0000-0000-000000000001'
  )
)
select transfer_id into temporary table targeted_fx_transfer from x;
with x as (
  select * from public.create_expense_repayment_v2(
    'f8000000-0000-0000-0000-000000000001',
    'f8300000-0000-0000-0000-000000000001',
    'f8300000-0000-0000-0000-000000000002',40,'CNY','FIFO',null,
    '2026-09-05 11:00+08',null,
    (select financial_version+1 from targeted_fx_version),
    'f8400000-0000-0000-0000-000000000002'
  )
)
select transfer_id into temporary table targeted_fx_transfer_2 from x;

select extensions.ok(
  (select count(*)=2 and sum(original_amount)=10 and sum(base_amount)=80
   from public.transfer_expense_allocations
   where expense_id=(select expense_id from targeted_fx_ids))
  and (select count(*)=1 and bool_and(payment_currency='EUR' and payment_amount=5)
   from public.transfer_expense_allocations
   where transfer_id=(select transfer_id from targeted_fx_transfer))
  and (select count(*)=1 and bool_and(payment_currency='CNY' and payment_amount=40)
   from public.transfer_expense_allocations
   where transfer_id=(select transfer_id from targeted_fx_transfer_2)),
  'committed allocations retain independent payment currency and FX snapshots'
);

select extensions.ok(
  (select remaining_original_amount=0 and settled_original_amount=10 and settled_base_amount=80
   from public.get_expense_repayment_progress(
     'f8000000-0000-0000-0000-000000000001',
     (select expense_id from targeted_fx_ids))),
  'progress closes the foreign debt using both payment currencies'
);
select * from extensions.finish();
rollback;
