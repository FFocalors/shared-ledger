begin;

select plan(9);

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

insert into auth.users(
  instance_id, id, aud, role, email, encrypted_password,
  email_confirmed_at, raw_app_meta_data, raw_user_meta_data, created_at, updated_at
)
values
  ('00000000-0000-0000-0000-000000000000','f3100000-0000-0000-0000-000000000001',
   'authenticated','authenticated','phase12.a@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
  ('00000000-0000-0000-0000-000000000000','f3100000-0000-0000-0000-000000000002',
   'authenticated','authenticated','phase12.b@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());

insert into public.activities(id,join_code,name,type,base_currency,multi_currency_enabled,created_by)
values
  ('f3000000-0000-0000-0000-000000000001','91220001','Allocation invariants','normal','CNY',true,
   'f3100000-0000-0000-0000-000000000001'),
  ('f3000000-0000-0000-0000-000000000002','91220002','Reverse snapshots','normal','CNY',true,
   'f3100000-0000-0000-0000-000000000001'),
  ('f3000000-0000-0000-0000-000000000003','91220003','Tiny external payments','normal','CNY',true,
   'f3100000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id)
select a.id,u.id
from public.activities a cross join auth.users u
where a.id in (
  'f3000000-0000-0000-0000-000000000001',
  'f3000000-0000-0000-0000-000000000002',
  'f3000000-0000-0000-0000-000000000003'
);

insert into public.ledger_units(id,activity_id,name,type)
values
  ('f3200000-0000-0000-0000-000000000001','f3000000-0000-0000-0000-000000000001','Main','default'),
  ('f3200000-0000-0000-0000-000000000002','f3000000-0000-0000-0000-000000000002','Main','default'),
  ('f3200000-0000-0000-0000-000000000003','f3000000-0000-0000-0000-000000000003','Main','default');

insert into public.participants(id,activity_id,name,participant_order)
values
  ('f3300000-0000-0000-0000-000000000001','f3000000-0000-0000-0000-000000000001','A',0),
  ('f3300000-0000-0000-0000-000000000002','f3000000-0000-0000-0000-000000000001','B',1),
  ('f3300000-0000-0000-0000-000000000003','f3000000-0000-0000-0000-000000000001','C',2),
  ('f3300000-0000-0000-0000-000000000004','f3000000-0000-0000-0000-000000000001','D',3),
  ('f3300000-0000-0000-0000-000000000011','f3000000-0000-0000-0000-000000000002','A',0),
  ('f3300000-0000-0000-0000-000000000012','f3000000-0000-0000-0000-000000000002','B',1),
  ('f3300000-0000-0000-0000-000000000021','f3000000-0000-0000-0000-000000000003','A',0),
  ('f3300000-0000-0000-0000-000000000022','f3000000-0000-0000-0000-000000000003','B',1);

insert into public.participant_claims(activity_id,participant_id,user_id)
values
  ('f3000000-0000-0000-0000-000000000002','f3300000-0000-0000-0000-000000000012','f3100000-0000-0000-0000-000000000002'),
  ('f3000000-0000-0000-0000-000000000003','f3300000-0000-0000-0000-000000000022','f3100000-0000-0000-0000-000000000002');

create temporary table phase12_ids(label text primary key, object_id uuid) on commit drop;
select pg_temp.authenticate('f3100000-0000-0000-0000-000000000002');

with created as (
  select * from public.create_expense(
    'f3200000-0000-0000-0000-000000000001', '47.2 EUR AA', 47.2, 'EUR', 7.6755,
    'aa'::public.expense_split_method,
    '[{"participant_id":"f3300000-0000-0000-0000-000000000001","amount":"47"},
      {"participant_id":"f3300000-0000-0000-0000-000000000002","amount":"0.2"}]'::jsonb,
    '[]'::jsonb,
    array['f3300000-0000-0000-0000-000000000001'::uuid,
          'f3300000-0000-0000-0000-000000000002'::uuid],
    '2026-09-20 12:00:00+08', null, null, 'money'
  )
)
insert into phase12_ids select 'eur',expense_id from created;
select ok(
  (select base_amount=362.3 from public.expenses where id=(select object_id from phase12_ids where label='eur'))
  and (select count(*)=1 and sum(original_amount)=23.4 and sum(amount)=179.5
       from public.expense_debts where expense_id=(select object_id from phase12_ids where label='eur')),
  '47.2 EUR keeps 23.4 original debt and 179.5 base debt'
);

with created as (
  select * from public.create_expense(
    'f3200000-0000-0000-0000-000000000001', '4.04 USD four-party AA', 4.04, 'USD', 7,
    'aa'::public.expense_split_method,
    '[{"participant_id":"f3300000-0000-0000-0000-000000000001","amount":"2.02"},
      {"participant_id":"f3300000-0000-0000-0000-000000000002","amount":"2.02"}]'::jsonb,
    '[]'::jsonb,
    array['f3300000-0000-0000-0000-000000000001'::uuid,
          'f3300000-0000-0000-0000-000000000002'::uuid,
          'f3300000-0000-0000-0000-000000000003'::uuid,
          'f3300000-0000-0000-0000-000000000004'::uuid],
    '2026-09-20 12:01:00+08', null, null, 'money'
  )
)
insert into phase12_ids select 'four',expense_id from created;
select ok(
  (select count(*)=2 from public.expense_debts where expense_id=(select object_id from phase12_ids where label='four'))
  and (select count(*)=0 from public.expense_debts where expense_id=(select object_id from phase12_ids where label='four')
       and debtor_participant_id='f3300000-0000-0000-0000-000000000003'
       and creditor_participant_id='f3300000-0000-0000-0000-000000000002'),
  'four-party original topology has two debts and no C-to-B ghost row'
);

with x as (
  select * from public.create_expense(
    'f3200000-0000-0000-0000-000000000002', 'B owes A at 6', 100, 'USD', 6,
    'manual'::public.expense_split_method,
    '[{"participant_id":"f3300000-0000-0000-0000-000000000011","amount":"100"}]'::jsonb,
    '[{"participant_id":"f3300000-0000-0000-0000-000000000012","amount":"100"}]'::jsonb,
    '{}'::uuid[],'2026-09-20 12:02:00+08',null,null,'money'
  )
), y as (
  select * from public.create_expense(
    'f3200000-0000-0000-0000-000000000002', 'B owes A at 8', 100, 'USD', 8,
    'manual'::public.expense_split_method,
    '[{"participant_id":"f3300000-0000-0000-0000-000000000011","amount":"100"}]'::jsonb,
    '[{"participant_id":"f3300000-0000-0000-0000-000000000012","amount":"100"}]'::jsonb,
    '{}'::uuid[],'2026-09-20 12:03:00+08',null,null,'money'
  )
), z as (
  select * from public.create_expense(
    'f3200000-0000-0000-0000-000000000002', 'A owes B at 7', 100, 'USD', 7,
    'manual'::public.expense_split_method,
    '[{"participant_id":"f3300000-0000-0000-0000-000000000012","amount":"100"}]'::jsonb,
    '[{"participant_id":"f3300000-0000-0000-0000-000000000011","amount":"100"}]'::jsonb,
    '{}'::uuid[],'2026-09-20 12:04:00+08',null,null,'money'
  )
)
select 1 from x,y,z;
select ok(
  (select original_amount=100 and base_amount=800
   from public.bilateral_debts
   where activity_id='f3000000-0000-0000-0000-000000000002'
     and debtor_participant_id='f3300000-0000-0000-0000-000000000012'
     and creditor_participant_id='f3300000-0000-0000-0000-000000000011'
     and currency='USD'),
  'reverse USD debts use FIFO snapshot residual base amount'
);

with x as (
  select * from public.create_settlement_transfer(
    'f3000000-0000-0000-0000-000000000002',
    'f3300000-0000-0000-0000-000000000012',
    'f3300000-0000-0000-0000-000000000011',
    700, 'CNY', '2026-09-20 12:05:00+08', null,
    'f3400000-0000-0000-0000-000000000001'
  )
)
insert into phase12_ids select 'reverse_transfer',transfer_id from x;
select ok(
  (select original_amount=12.5 and base_amount=100
   from public.bilateral_debts
   where activity_id='f3000000-0000-0000-0000-000000000002'
     and debtor_participant_id='f3300000-0000-0000-0000-000000000012'
     and creditor_participant_id='f3300000-0000-0000-0000-000000000011'
     and currency='USD'),
  '700 CNY consumes the FIFO residual and leaves 12.5 USD'
);

with x as (
  select * from public.create_settlement_transfer(
    'f3000000-0000-0000-0000-000000000002',
    'f3300000-0000-0000-0000-000000000012',
    'f3300000-0000-0000-0000-000000000011',
    100, 'CNY', '2026-09-20 12:05:30+08', null,
    'f3400000-0000-0000-0000-000000000004'
  )
)
insert into phase12_ids select 'reverse_transfer_tail',transfer_id from x;
select ok(
  not exists(
    select 1 from public.bilateral_debts
    where activity_id='f3000000-0000-0000-0000-000000000002'
      and original_amount > 0
  ),
  'the remaining 100 CNY clears the FIFO residual'
);

with x as (
  select * from public.create_expense(
    'f3200000-0000-0000-0000-000000000003', '2 JPY', 2, 'JPY', 0.05,
    'manual'::public.expense_split_method,
    '[{"participant_id":"f3300000-0000-0000-0000-000000000021","amount":"2"}]'::jsonb,
    '[{"participant_id":"f3300000-0000-0000-0000-000000000022","amount":"2"}]'::jsonb,
    '{}'::uuid[],'2026-09-20 12:06:00+08',null,null,'money'
  )
)
insert into phase12_ids select 'tiny_expense',expense_id from x;
with x as (
  select * from public.create_settlement_transfer(
    'f3000000-0000-0000-0000-000000000003',
    'f3300000-0000-0000-0000-000000000022',
    'f3300000-0000-0000-0000-000000000021',
    0.01, 'JPY', '2026-09-20 12:07:00+08', null,
    'f3400000-0000-0000-0000-000000000002'
  )
)
insert into phase12_ids select 'tiny_first',transfer_id from x;
select ok(
  (select sum(original_amount)=0.01 and sum(base_amount)=0 from public.transfer_allocations
   where transfer_id=(select object_id from phase12_ids where label='tiny_first')),
  'tiny external transfer records original debt with zero base allocation'
);

with x as (
  select * from public.create_settlement_transfer(
    'f3000000-0000-0000-0000-000000000003',
    'f3300000-0000-0000-0000-000000000022',
    'f3300000-0000-0000-0000-000000000021',
    1.99, 'JPY', '2026-09-20 12:08:00+08', null,
    'f3400000-0000-0000-0000-000000000003'
  )
)
insert into phase12_ids select 'tiny_last',transfer_id from x;
select ok(
  (select sum(original_amount)=2 and sum(base_amount)=0.1 from public.transfer_allocations
   where expense_debt_id in (select id from public.expense_debts
                              where expense_id=(select object_id from phase12_ids where label='tiny_expense')))
  and not exists (select 1 from public.bilateral_debts
                  where activity_id='f3000000-0000-0000-0000-000000000003'
                    and original_amount > 0),
  'cumulative tiny transfers settle the original debt and final base tail'
);

do $replay$
begin
  begin
    perform * from public.create_settlement_transfer(
      'f3000000-0000-0000-0000-000000000003',
      'f3300000-0000-0000-0000-000000000022',
      'f3300000-0000-0000-0000-000000000021',
      0.01, 'JPY', '2026-09-20 13:08:00+08',
      'f3300000-0000-0000-0000-000000000021',
      'f3400000-0000-0000-0000-000000000002'
    );
    raise exception 'conflicting replay unexpectedly succeeded';
  exception when unique_violation then null;
  end;
end;
$replay$;
select ok(true, 'request replay rejects changed occurred_at/on_behalf payload');

create temporary table phase12_before on commit drop as
select debtor_participant_id, creditor_participant_id, currency,
       original_amount, base_amount
from public.bilateral_debts
where activity_id='f3000000-0000-0000-0000-000000000002';
select private.rebuild_activity_debt_projection('f3000000-0000-0000-0000-000000000002');
select ok(
  not exists(
    (select debtor_participant_id, creditor_participant_id, currency, original_amount, base_amount
     from phase12_before)
    except
    (select debtor_participant_id, creditor_participant_id, currency, original_amount, base_amount
     from public.bilateral_debts where activity_id='f3000000-0000-0000-0000-000000000002')
  )
  and not exists(
    (select debtor_participant_id, creditor_participant_id, currency, original_amount, base_amount
     from public.bilateral_debts where activity_id='f3000000-0000-0000-0000-000000000002')
    except
    (select debtor_participant_id, creditor_participant_id, currency, original_amount, base_amount
     from phase12_before)
  ),
  'rebuilding the same activity preserves the projection'
);

select * from extensions.finish();
rollback;
