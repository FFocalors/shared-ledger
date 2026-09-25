\set ON_ERROR_STOP on

begin;

\ir legacy_rpc_fixture_adapters.sql

create extension if not exists pgtap with schema extensions;
select extensions.plan(8);

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password,
  email_confirmed_at, raw_app_meta_data, raw_user_meta_data, created_at, updated_at
)
values (
  '00000000-0000-0000-0000-000000000000',
  'b5000000-0000-0000-0000-000000000001',
  'authenticated', 'authenticated', 'mass500-aa@example.invalid',
  crypt('fixture', gen_salt('bf')), now(), '{}', '{}', now(), now()
);

insert into public.activities (
  id, join_code, name, type, base_currency, multi_currency_enabled, created_by
)
values (
  'b5000000-0000-0000-0000-000000000010',
  '95000010', 'MASS500 micro AA', 'normal', 'CNY', false,
  'b5000000-0000-0000-0000-000000000001'
);

insert into public.activity_members(activity_id, user_id)
values (
  'b5000000-0000-0000-0000-000000000010',
  'b5000000-0000-0000-0000-000000000001'
);

insert into public.ledger_units(id, activity_id, name, type)
values (
  'b5000000-0000-0000-0000-000000000020',
  'b5000000-0000-0000-0000-000000000010', 'Main', 'default'
);

insert into public.participants(id, activity_id, name, participant_order)
select
  ('b5000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  'b5000000-0000-0000-0000-000000000010'::uuid,
  chr(64 + n), n - 1
from generate_series(1, 5) as n;

set local role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"b5000000-0000-0000-0000-000000000001","role":"authenticated"}',
  true
);

create temporary table mass500_expenses (
  label text primary key,
  expense_id uuid not null
) on commit drop;

-- MASS500-001: four positive 0.0600 original debts must fit a 0.2 base net.
with created as (
  select * from pg_temp.create_expense_fixture(
    'b5000000-0000-0000-0000-000000000020',
    'MASS500 0.3 / 5', 0.3, 'CNY', 1, 'aa',
    '[{"participant_id":"b5000000-0000-0000-0000-000000000001","amount":"0.3"}]',
    '[]',
    array(
      select id from public.participants
      where activity_id = 'b5000000-0000-0000-0000-000000000010'
      order by participant_order
    ),
    '2026-09-25 09:00+08', null, null, 'money'
  )
)
insert into mass500_expenses select 'micro', expense_id from created;

select extensions.ok(
  exists(select 1 from mass500_expenses where label = 'micro'),
  '0.3 CNY / five-person AA is a valid persisted Expense'
);

select extensions.is(
  (select array_agg(d.original_amount order by p.participant_order)
   from public.expense_debts d
   join public.participants p on p.id = d.debtor_participant_id
   where d.expense_id = (select expense_id from mass500_expenses where label = 'micro')),
  array[0.0600, 0.0600, 0.0600, 0.0600]::numeric[],
  'four original debts remain exactly 0.0600 CNY each'
);

select extensions.is(
  (select array_agg(d.amount order by p.participant_order)
   from public.expense_debts d
   join public.participants p on p.id = d.debtor_participant_id
   where d.expense_id = (select expense_id from mass500_expenses where label = 'micro')),
  array[0.1, 0.1, 0.0, 0.0]::numeric[],
  'base debt uses deterministic debtor order for the two available 0.1 units'
);

select extensions.ok(
  (select count(*) = 4 and min(d.amount) >= 0 and sum(d.amount) = 0.2
   from public.expense_debts d
   where d.expense_id = (select expense_id from mass500_expenses where label = 'micro')),
  'all four base debts are nonnegative and conserve the 0.2 base net'
);

select extensions.is(
  (select count(*) from public.expense_debts d
   where d.expense_id = (select expense_id from mass500_expenses where label = 'micro')
     and d.original_amount > 0 and d.amount = 0),
  2::bigint,
  'positive original debts remain present when their base share is zero'
);

create temporary table mass500_before_rebuild on commit drop as
select debtor_participant_id, creditor_participant_id, original_amount,
       original_currency, fx_rate, amount
from public.expense_debts
where expense_id = (select expense_id from mass500_expenses where label = 'micro');

reset role;
select private.rebuild_expense_debts_locked(
  (select expense_id from mass500_expenses where label = 'micro'),
  'b5000000-0000-0000-0000-000000000010'
);
set local role authenticated;

select extensions.ok(
  not exists (
    (select * from mass500_before_rebuild
     except all
     select debtor_participant_id, creditor_participant_id, original_amount,
            original_currency, fx_rate, amount
     from public.expense_debts
     where expense_id = (select expense_id from mass500_expenses where label = 'micro'))
    union all
    (select debtor_participant_id, creditor_participant_id, original_amount,
            original_currency, fx_rate, amount
     from public.expense_debts
     where expense_id = (select expense_id from mass500_expenses where label = 'micro')
     except all select * from mass500_before_rebuild)
  ),
  'repeat rebuild reproduces the same pairs and amounts without relying on row IDs'
);

-- MASS500-002's existing valid allocation must remain unchanged by the fix.
with created as (
  select * from pg_temp.create_expense_fixture(
    'b5000000-0000-0000-0000-000000000020',
    'MASS500 1.2 / 5', 1.2, 'CNY', 1, 'aa',
    '[{"participant_id":"b5000000-0000-0000-0000-000000000001","amount":"1.2"}]',
    '[]',
    array(
      select id from public.participants
      where activity_id = 'b5000000-0000-0000-0000-000000000010'
      order by participant_order
    ),
    '2026-09-25 09:01+08', null, null, 'money'
  )
)
insert into mass500_expenses select 'valid', expense_id from created;

select extensions.is(
  (select array_agg(d.amount order by p.participant_order)
   from public.expense_debts d
   join public.participants p on p.id = d.debtor_participant_id
   where d.expense_id = (select expense_id from mass500_expenses where label = 'valid')),
  array[0.2, 0.2, 0.2, 0.3]::numeric[],
  'existing valid 1.2 / five-person base allocation is preserved'
);

select extensions.is(
  (select array_agg(d.original_amount order by p.participant_order)
   from public.expense_debts d
   join public.participants p on p.id = d.debtor_participant_id
   where d.expense_id = (select expense_id from mass500_expenses where label = 'valid')),
  array[0.2400, 0.2400, 0.2400, 0.2400]::numeric[],
  'existing valid 1.2 / five-person original debts remain exact'
);

select * from extensions.finish();
rollback;
