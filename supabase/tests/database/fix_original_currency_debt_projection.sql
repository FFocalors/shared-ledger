\set ON_ERROR_STOP on

create extension if not exists pgtap with schema extensions;

begin;

\ir legacy_rpc_fixture_adapters.sql
select plan(10);

create function pg_temp.assert_true(p_condition boolean, p_message text)
returns void language plpgsql as $function$
begin
  if p_condition is not true then
    raise exception 'assertion failed: %', p_message;
  end if;
end;
$function$;

create function pg_temp.authenticate(p_user_id uuid)
returns void language plpgsql as $function$
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
  ('00000000-0000-0000-0000-000000000000','f2100000-0000-0000-0000-000000000001',
   'authenticated','authenticated','fix.original.a@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
  ('00000000-0000-0000-0000-000000000000','f2100000-0000-0000-0000-000000000002',
   'authenticated','authenticated','fix.original.b@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());

insert into public.activities(
  id, join_code, name, type, base_currency, multi_currency_enabled, created_by
)
values(
  'f2000000-0000-0000-0000-000000000001',
  '91110011', 'Original currency debt projection', 'normal', 'CNY', true,
  'f2100000-0000-0000-0000-000000000001'
);

insert into public.activity_members(activity_id, user_id)
values
  ('f2000000-0000-0000-0000-000000000001','f2100000-0000-0000-0000-000000000001'),
  ('f2000000-0000-0000-0000-000000000001','f2100000-0000-0000-0000-000000000002');

insert into public.ledger_units(id, activity_id, name, type)
values(
  'f2200000-0000-0000-0000-000000000001',
  'f2000000-0000-0000-0000-000000000001', 'Main', 'default'
);

insert into public.participants(id, activity_id, name, participant_order)
values
  ('f2300000-0000-0000-0000-000000000001','f2000000-0000-0000-0000-000000000001','111',0),
  ('f2300000-0000-0000-0000-000000000002','f2000000-0000-0000-0000-000000000001','222',1),
  ('f2300000-0000-0000-0000-000000000003','f2000000-0000-0000-0000-000000000001','333',2),
  ('f2300000-0000-0000-0000-000000000004','f2000000-0000-0000-0000-000000000001','444',3);

select pg_temp.authenticate('f2100000-0000-0000-0000-000000000002');

-- 47.2 EUR, paid 47/0.2 EUR, split equally at 23.6/23.6 EUR.
create temporary table fix_target_expense on commit drop as
select expense_id
from pg_temp.create_expense_fixture(
  'f2200000-0000-0000-0000-000000000001',
  'EUR AA 47.2',
  47.2, 'EUR', 7.6755, 'aa'::public.expense_split_method,
  '[{"participant_id":"f2300000-0000-0000-0000-000000000001","amount":"47"},
    {"participant_id":"f2300000-0000-0000-0000-000000000002","amount":"0.2"}]'::jsonb,
  '[]'::jsonb,
  array[
    'f2300000-0000-0000-0000-000000000001'::uuid,
    'f2300000-0000-0000-0000-000000000002'::uuid
  ],
  '2026-09-20 12:00:00+08', null, null, 'money'
);

select is(
  (select base_amount from public.expenses where id=(select expense_id from fix_target_expense)),
  362.3::numeric,
  '47.2 EUR keeps the rounded base expense amount'
);
select is(
  (select amount from public.expense_debts where expense_id=(select expense_id from fix_target_expense)),
  179.5::numeric,
  'base debt remains 179.5 CNY'
);
select is(
  (select original_amount from public.expense_debts where expense_id=(select expense_id from fix_target_expense)),
  23.4::numeric,
  'original debt uses the 23.4 EUR participant net'
);
select is(
  (select original_amount from public.bilateral_debts
   where activity_id='f2000000-0000-0000-0000-000000000001'
     and debtor_participant_id='f2300000-0000-0000-0000-000000000002'
     and creditor_participant_id='f2300000-0000-0000-0000-000000000001'
     and currency='EUR'),
  23.4::numeric,
  'bilateral EUR debt is 23.4 EUR'
);
select is(
  (select original_amount from public.list_settlement_options('f2000000-0000-0000-0000-000000000001')
   where debtor_participant_id='f2300000-0000-0000-0000-000000000002'
     and creditor_participant_id='f2300000-0000-0000-0000-000000000001'
     and currency='EUR'),
  23.4::numeric,
  'settlement options expose 23.4 EUR'
);

-- Multiple original-currency rows must follow the same stable participant-order
-- match as the base projection: 222->111=50, 333->111=10, 333->444=40.
create temporary table fix_multi_expense on commit drop as
select expense_id
from pg_temp.create_expense_fixture(
  'f2200000-0000-0000-0000-000000000001',
  'Stable multi-row match',
  100, 'CNY', 1, 'manual'::public.expense_split_method,
  '[{"participant_id":"f2300000-0000-0000-0000-000000000001","amount":"60"},
    {"participant_id":"f2300000-0000-0000-0000-000000000004","amount":"40"}]'::jsonb,
  '[{"participant_id":"f2300000-0000-0000-0000-000000000002","amount":"50"},
    {"participant_id":"f2300000-0000-0000-0000-000000000003","amount":"50"}]'::jsonb,
  '{}'::uuid[],
  '2026-09-20 13:00:00+08', null, null, 'money'
);

select is(
  (select count(*) from public.expense_debts where expense_id=(select expense_id from fix_multi_expense)),
  3::bigint,
  'multi-row expense creates three stable debt pairs'
);
select is(
  (select original_amount from public.expense_debts
   where expense_id=(select expense_id from fix_multi_expense)
     and debtor_participant_id='f2300000-0000-0000-0000-000000000002'
     and creditor_participant_id='f2300000-0000-0000-0000-000000000001'),
  50::numeric,
  'first stable pair keeps 50 CNY'
);
select is(
  (select original_amount from public.expense_debts
   where expense_id=(select expense_id from fix_multi_expense)
     and debtor_participant_id='f2300000-0000-0000-0000-000000000003'
     and creditor_participant_id='f2300000-0000-0000-0000-000000000001'),
  10::numeric,
  'middle stable pair keeps 10 CNY'
);
select is(
  (select original_amount from public.expense_debts
   where expense_id=(select expense_id from fix_multi_expense)
     and debtor_participant_id='f2300000-0000-0000-0000-000000000003'
     and creditor_participant_id='f2300000-0000-0000-0000-000000000004'),
  40::numeric,
  'last stable pair keeps 40 CNY'
);
select is(
  (select sum(original_amount) from public.expense_debts where expense_id=(select expense_id from fix_multi_expense)),
  100::numeric,
  'multi-row original debts conserve the participant net total'
);

select * from extensions.finish();
rollback;
