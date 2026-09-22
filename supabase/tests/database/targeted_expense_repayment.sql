\set ON_ERROR_STOP on

begin;

create extension if not exists pgtap with schema extensions;
select extensions.plan(8);

create function pg_temp.authenticate(p_user_id uuid)
returns void
language plpgsql
as $function$
begin
  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', p_user_id, 'role', 'authenticated')::text,
    true
  );
end;
$function$;

create function pg_temp.assert_true(p_condition boolean, p_message text)
returns void
language plpgsql
as $function$
begin
  if p_condition is not true then
    raise exception 'assertion failed: %', p_message;
  end if;
end;
$function$;

insert into auth.users(
  instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,
  raw_app_meta_data,raw_user_meta_data,created_at,updated_at
)
values
  ('00000000-0000-0000-0000-000000000000','f7100000-0000-0000-0000-000000000001',
   'authenticated','authenticated','targeted.a@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
  ('00000000-0000-0000-0000-000000000000','f7100000-0000-0000-0000-000000000002',
   'authenticated','authenticated','targeted.b@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());

insert into public.activities(id,join_code,name,type,base_currency,multi_currency_enabled,created_by)
values ('f7000000-0000-0000-0000-000000000001','97000001','Targeted repayment','normal','CNY',true,
        'f7100000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id)
values ('f7000000-0000-0000-0000-000000000001','f7100000-0000-0000-0000-000000000001'),
       ('f7000000-0000-0000-0000-000000000001','f7100000-0000-0000-0000-000000000002');
insert into public.ledger_units(id,activity_id,name,type)
values ('f7200000-0000-0000-0000-000000000001','f7000000-0000-0000-0000-000000000001','Main','default');
insert into public.participants(id,activity_id,name,participant_order)
values ('f7300000-0000-0000-0000-000000000001','f7000000-0000-0000-0000-000000000001','A',0),
       ('f7300000-0000-0000-0000-000000000002','f7000000-0000-0000-0000-000000000001','B',1);
insert into public.participant_claims(activity_id,participant_id,user_id)
values ('f7000000-0000-0000-0000-000000000001','f7300000-0000-0000-0000-000000000001','f7100000-0000-0000-0000-000000000001'),
       ('f7000000-0000-0000-0000-000000000001','f7300000-0000-0000-0000-000000000002','f7100000-0000-0000-0000-000000000002');

set local role authenticated;
select pg_temp.authenticate('f7100000-0000-0000-0000-000000000001');

-- Prepayment is created before the bills so it is consumed dynamically by the
-- first bill.  The second bill is then the selected partial-payment target.
select * from public.create_prepayment(
  'f7000000-0000-0000-0000-000000000001',
  'f7300000-0000-0000-0000-000000000001',
  'f7300000-0000-0000-0000-000000000002',40,'2026-09-01 08:00+08',null
);

create temporary table targeted_ids(label text primary key, object_id uuid) on commit drop;
with x as (
  select * from public.create_expense(
    'f7200000-0000-0000-0000-000000000001','first bill',100,'CNY',1,
    'manual'::public.expense_split_method,
    '[{"participant_id":"f7300000-0000-0000-0000-000000000002","amount":"100"}]'::jsonb,
    '[{"participant_id":"f7300000-0000-0000-0000-000000000001","amount":"100"}]'::jsonb,
    '{}'::uuid[],'2026-09-01 09:00+08',null,null,'money'
  )
)
insert into targeted_ids select 'first',expense_id from x;
with x as (
  select * from public.create_expense(
    'f7200000-0000-0000-0000-000000000001','second bill',80,'CNY',1,
    'manual'::public.expense_split_method,
    '[{"participant_id":"f7300000-0000-0000-0000-000000000002","amount":"80"}]'::jsonb,
    '[{"participant_id":"f7300000-0000-0000-0000-000000000001","amount":"80"}]'::jsonb,
    '{}'::uuid[],'2026-09-02 09:00+08',null,null,'money'
  )
)
insert into targeted_ids select 'second',expense_id from x;
with x as (
  select * from public.create_expense(
    'f7200000-0000-0000-0000-000000000001','reverse bill',30,'CNY',1,
    'manual'::public.expense_split_method,
    '[{"participant_id":"f7300000-0000-0000-0000-000000000001","amount":"30"}]'::jsonb,
    '[{"participant_id":"f7300000-0000-0000-0000-000000000002","amount":"30"}]'::jsonb,
    '{}'::uuid[],'2026-09-03 09:00+08',null,null,'money'
  )
)
insert into targeted_ids select 'reverse',expense_id from x;

select pg_temp.assert_true(
  (select remaining_original_amount=30 and offset_original_amount=30 and prepayment_original_amount=40
   from public.list_transfer_expense_candidates(
     'f7000000-0000-0000-0000-000000000001',
     'f7300000-0000-0000-0000-000000000001',
     'f7300000-0000-0000-0000-000000000002','CNY'
   ) where expense_id=(select object_id from targeted_ids where label='first'))
  and (select remaining_original_amount=80 and offset_original_amount=0
   from public.list_transfer_expense_candidates(
     'f7000000-0000-0000-0000-000000000001',
     'f7300000-0000-0000-0000-000000000001',
     'f7300000-0000-0000-0000-000000000002','CNY'
   ) where expense_id=(select object_id from targeted_ids where label='second')),
  'two forward bills share one reverse offset globally and preserve prepayment'
);

select financial_version into temporary table targeted_version
from public.activities where id='f7000000-0000-0000-0000-000000000001';

select pg_temp.assert_true(
  (select count(*)=2 and sum(payment_amount)=50 and
          sum(original_amount) filter (where expense_id=(select object_id from targeted_ids where label='first'))=30 and
          sum(original_amount) filter (where expense_id=(select object_id from targeted_ids where label='second'))=20
   from public.preview_expense_repayment(
     'f7000000-0000-0000-0000-000000000001',
     'f7300000-0000-0000-0000-000000000001',
     'f7300000-0000-0000-0000-000000000002',50,'CNY','TARGETED',
     array[(select object_id from targeted_ids where label='first'),
           (select object_id from targeted_ids where label='second')],
     (select financial_version from targeted_version)
   )),
  'targeted preview allocates selected residuals across two bills'
);

with x as (
  select * from public.create_expense_repayment_v2(
    'f7000000-0000-0000-0000-000000000001',
    'f7300000-0000-0000-0000-000000000001',
    'f7300000-0000-0000-0000-000000000002',50,'CNY','TARGETED',
    array[(select object_id from targeted_ids where label='first'),
          (select object_id from targeted_ids where label='second')],
    '2026-09-04 09:00+08',null,
    (select financial_version from targeted_version),
    'f7400000-0000-0000-0000-000000000001'
  )
)
insert into targeted_ids select 'payment',transfer_id from x;
grant select on targeted_ids to service_role;

select pg_temp.assert_true(
  (select count(*)=2 and sum(payment_amount)=50 and sum(base_amount)=50
   from public.transfer_expense_allocations
   where transfer_id=(select object_id from targeted_ids where label='payment')
     and allocation_mode='TARGETED')
  and (select count(*)=2 and sum(coalesce(ta.original_amount,ta.amount))=50
       from public.transfer_allocations ta
       where ta.transfer_id=(select object_id from targeted_ids where label='payment')),
  'targeted payment persists immutable actuals and rebuildable projection'
);

reset role;
set local role service_role;
select private.rebuild_activity_debt_projection('f7000000-0000-0000-0000-000000000001');
set local role authenticated;
select pg_temp.authenticate('f7100000-0000-0000-0000-000000000001');

select pg_temp.assert_true(
  (select count(*)=2 and sum(payment_amount)=50
   from public.transfer_expense_allocations
   where transfer_id=(select object_id from targeted_ids where label='payment'))
  and (select settled_original_amount=30 and prepayment_original_amount=40 and
              offset_original_amount=30 and remaining_original_amount=0
       from public.get_expense_repayment_progress(
         'f7000000-0000-0000-0000-000000000001',
         (select object_id from targeted_ids where label='first'))),
  'rebuild keeps fixed allocation facts and progress totals'
);

select pg_temp.assert_true(
  (select count(*)=1 from public.create_expense_repayment_v2(
    'f7000000-0000-0000-0000-000000000001',
    'f7300000-0000-0000-0000-000000000001',
    'f7300000-0000-0000-0000-000000000002',50,'CNY','TARGETED',
    array[(select object_id from targeted_ids where label='first'),
          (select object_id from targeted_ids where label='second')],
    '2026-09-04 09:00+08',null,
    (select financial_version from targeted_version),
    'f7400000-0000-0000-0000-000000000001'
  )),
  'same request id retries before stale-version rejection'
);

do $stale$
begin
  begin
    perform * from public.create_expense_repayment_v2(
      'f7000000-0000-0000-0000-000000000001',
      'f7300000-0000-0000-0000-000000000001',
      'f7300000-0000-0000-0000-000000000002',1,'CNY','FIFO',null,
      '2026-09-04 10:00+08',null,
      (select financial_version from targeted_version),
      'f7400000-0000-0000-0000-000000000002'
    );
    raise exception 'stale version unexpectedly succeeded';
  exception when sqlstate '40001' then null;
  end;
end;
$stale$;
select pg_temp.assert_true(
  (select count(*)=1 from public.transfers where id=(select object_id from targeted_ids where label='payment'))
  and (select financial_version>(select financial_version from targeted_version)
       from public.activities where id='f7000000-0000-0000-0000-000000000001'),
  'stale version rejects a new request without adding a transfer'
);

select * from public.void_prepayment_transfer(
  (select object_id from targeted_ids where label='payment'),'targeted test void'
);
select pg_temp.assert_true(
  (select not exists(select 1 from public.transfer_allocations where transfer_id=(select object_id from targeted_ids where label='payment')))
  and (select count(*)=2 from public.transfer_expense_allocations where transfer_id=(select object_id from targeted_ids where label='payment'))
  and (select financial_locked from public.expenses where id=(select object_id from targeted_ids where label='first'))
  and (select financial_locked from public.expenses where id=(select object_id from targeted_ids where label='second')),
  'void removes active contribution but preserves immutable allocation and financial lock'
);

reset role;
set local role service_role;
select private.rebuild_activity_debt_projection('f7000000-0000-0000-0000-000000000001');
select pg_temp.assert_true(
  (select count(*)=0 from public.transfer_allocations where transfer_id=(select object_id from targeted_ids where label='payment'))
  and (select count(*)=2 from public.expense_debts where expense_id in(
    (select object_id from targeted_ids where label='first'),
    (select object_id from targeted_ids where label='second'))),
  'rebuild after void does not delete locked expense debt rows'
);

select extensions.ok(true,'candidate offset and prepayment residuals');
select extensions.ok(true,'targeted preview across two bills');
select extensions.ok(true,'immutable actual allocations');
select extensions.ok(true,'fixed allocation survives rebuild');
select extensions.ok(true,'progress aggregation');
select extensions.ok(true,'idempotent retry');
select extensions.ok(true,'stale version rejection');
select extensions.ok(true,'void and locked rebuild');
select * from extensions.finish();
rollback;
