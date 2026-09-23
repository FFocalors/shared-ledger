\set ON_ERROR_STOP on

begin;

\ir legacy_rpc_fixture_adapters.sql

create extension if not exists pgtap with schema extensions;
select extensions.plan(1);

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

create function pg_temp.authenticate(p_user uuid)
returns void
language plpgsql
as $function$
begin
  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', p_user, 'role', 'authenticated')::text,
    true
  );
end;
$function$;

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at
)
values (
  '00000000-0000-0000-0000-000000000000',
  'fa900000-0000-0000-0000-000000000001',
  'authenticated', 'authenticated', 'fair-aa@example.invalid',
  crypt('fair-aa-password', gen_salt('bf')), now(), '{}', '{}', now(), now()
);

insert into public.activities (
  id, join_code, name, type, base_currency, multi_currency_enabled, created_by
)
values (
  'fa900000-0000-0000-0000-000000000010',
  '99000010',
  'Fair AA settlement fixture',
  'large',
  'CNY',
  false,
  'fa900000-0000-0000-0000-000000000001'
);

insert into public.activity_members (activity_id, user_id)
values (
  'fa900000-0000-0000-0000-000000000010',
  'fa900000-0000-0000-0000-000000000001'
);

insert into public.ledger_units (id, activity_id, name, type)
values (
  'fa900000-0000-0000-0000-000000000020',
  'fa900000-0000-0000-0000-000000000010',
  'root',
  'root'
);

-- The order is deliberately whr, zhy, hzl. Input arrays below use a
-- different order to prove that request order never decides the remainder.
insert into public.participants (id, activity_id, name, participant_order)
values
  ('fa900000-0000-0000-0000-000000000101', 'fa900000-0000-0000-0000-000000000010', 'whr', 0),
  ('fa900000-0000-0000-0000-000000000102', 'fa900000-0000-0000-0000-000000000010', 'zhy', 1),
  ('fa900000-0000-0000-0000-000000000103', 'fa900000-0000-0000-0000-000000000010', 'hzl', 2);

set local role authenticated;
select pg_temp.authenticate('fa900000-0000-0000-0000-000000000001');

create temporary table phase9_expenses (
  label text primary key,
  expense_id uuid not null
) on commit drop;

-- Dinner: whr pays 156.2 and all three share equally.
with created as (
  select * from pg_temp.create_expense_fixture(
    'fa900000-0000-0000-0000-000000000020', '晚餐', 156.2, 'CNY', 1, 'aa',
    '[{"participant_id":"fa900000-0000-0000-0000-000000000101","amount":"156.2"}]',
    '[]',
    array[
      'fa900000-0000-0000-0000-000000000103'::uuid,
      'fa900000-0000-0000-0000-000000000102'::uuid,
      'fa900000-0000-0000-0000-000000000101'::uuid
    ],
    '2026-09-09 21:10+08', null, null
  )
)
insert into phase9_expenses select 'dinner', expense_id from created;

-- Mixue: zhy pays 13; zhy owes 6, hzl owes 7, whr owes 0 (omitted).
with created as (
  select * from pg_temp.create_expense_fixture(
    'fa900000-0000-0000-0000-000000000020', '蜜雪', 13, 'CNY', 1, 'manual',
    '[{"participant_id":"fa900000-0000-0000-0000-000000000102","amount":"13"}]',
    '[{"participant_id":"fa900000-0000-0000-0000-000000000102","amount":"6"},{"participant_id":"fa900000-0000-0000-0000-000000000103","amount":"7"}]',
    '{}', '2026-09-09 22:17+08', null, null
  )
)
insert into phase9_expenses select 'mixue', expense_id from created;

-- Highway: zhy pays 100 and whr owes the whole amount.
with created as (
  select * from pg_temp.create_expense_fixture(
    'fa900000-0000-0000-0000-000000000020', '高速费', 100, 'CNY', 1, 'manual',
    '[{"participant_id":"fa900000-0000-0000-0000-000000000102","amount":"100"}]',
    '[{"participant_id":"fa900000-0000-0000-0000-000000000101","amount":"100"}]',
    '{}', '2026-09-10 19:45+08', null, null
  )
)
insert into phase9_expenses select 'highway', expense_id from created;

-- Test bill: zhy pays 300 and all three share exactly 100 each.
with created as (
  select * from pg_temp.create_expense_fixture(
    'fa900000-0000-0000-0000-000000000020', '测试账单', 300, 'CNY', 1, 'aa',
    '[{"participant_id":"fa900000-0000-0000-0000-000000000102","amount":"300"}]',
    '[]',
    array[
      'fa900000-0000-0000-0000-000000000103'::uuid,
      'fa900000-0000-0000-0000-000000000101'::uuid,
      'fa900000-0000-0000-0000-000000000102'::uuid
    ],
    '2026-09-10 20:50+08', null, null
  )
)
insert into phase9_expenses select 'test', expense_id from created;

select pg_temp.assert_true(
  (
    select array_agg(p.name || ':' || s.base_amount::text order by p.participant_order) =
      array['whr:52.1', 'zhy:52.1', 'hzl:52.0']::text[]
      and sum(s.base_amount) = 156.2
    from public.splits as s
    join public.participants as p on p.id = s.participant_id
    where s.expense_id = (select expense_id from phase9_expenses where label = 'dinner')
  ),
  '156.2 AA must allocate 52.1, 52.1, 52.0 by participant order and conserve the total'
);

select pg_temp.assert_true(
  (
    select array_agg(
      debtor.name || '>' || creditor.name || ':' || bd.amount::text
      order by debtor.participant_order, creditor.participant_order
    ) = array['whr>zhy:147.9', 'hzl>whr:52.0', 'hzl>zhy:107.0']::text[]
    from public.bilateral_debts as bd
    join public.participants as debtor on debtor.id = bd.debtor_participant_id
    join public.participants as creditor on creditor.id = bd.creditor_participant_id
    where bd.activity_id = 'fa900000-0000-0000-0000-000000000010'
  ),
  'the four bills must produce the expected ordinary bilateral debts'
);

select pg_temp.assert_true(
  (
    select array_agg(
      from_p.name || '>' || to_p.name || ':' || plan.amount::text
      order by from_p.participant_order
    ) = array['whr>zhy:95.9', 'hzl>zhy:159.0']::text[]
    from public.preview_activity_settlement('fa900000-0000-0000-0000-000000000010') as plan
    join public.participants as from_p on from_p.id = plan.from_participant_id
    join public.participants as to_p on to_p.id = plan.to_participant_id
  ),
  'netted final settlement must be whr to zhy 95.9 and hzl to zhy 159.0'
);

select pg_temp.assert_true(
  (
    select count(*) = 3
      and sum(net_balance) = 0
      and sum(receivable) = sum(payable)
    from public.participant_financial_status
    where activity_id = 'fa900000-0000-0000-0000-000000000010'
  ),
  'participant net balances must conserve zero'
);

-- A positive AA fact and its negative refund cancel each other, while the
-- negative split independently proves truncation-toward-zero plus signed
-- remainder distribution: -15.5 / 3 -> -5.2, -5.2, -5.1.
with created as (
  select * from pg_temp.create_expense_fixture(
    'fa900000-0000-0000-0000-000000000020', '退款原账单', 15.5, 'CNY', 1, 'aa',
    '[{"participant_id":"fa900000-0000-0000-0000-000000000101","amount":"15.5"}]',
    '[]',
    array[
      'fa900000-0000-0000-0000-000000000103'::uuid,
      'fa900000-0000-0000-0000-000000000101'::uuid,
      'fa900000-0000-0000-0000-000000000102'::uuid
    ],
    '2026-09-10 21:00+08', null, null
  )
)
insert into phase9_expenses select 'refund_original', expense_id from created;

with created as (
  select * from pg_temp.create_expense_fixture(
    'fa900000-0000-0000-0000-000000000020', '负数退款', -15.5, 'CNY', 1, 'aa',
    '[{"participant_id":"fa900000-0000-0000-0000-000000000101","amount":"-15.5"}]',
    '[]',
    array[
      'fa900000-0000-0000-0000-000000000102'::uuid,
      'fa900000-0000-0000-0000-000000000103'::uuid,
      'fa900000-0000-0000-0000-000000000101'::uuid
    ],
    '2026-09-10 21:01+08', null,
    (select expense_id from phase9_expenses where label = 'refund_original')
  )
)
insert into phase9_expenses select 'negative_refund', expense_id from created;

select pg_temp.assert_true(
  (
    select array_agg(p.name || ':' || s.base_amount::text order by p.participant_order) =
      array['whr:-5.2', 'zhy:-5.2', 'hzl:-5.1']::text[]
      and sum(s.base_amount) = -15.5
    from public.splits as s
    join public.participants as p on p.id = s.participant_id
    where s.expense_id = (select expense_id from phase9_expenses where label = 'negative_refund')
  )
  and (
    select array_agg(
      from_p.name || '>' || to_p.name || ':' || plan.amount::text
      order by from_p.participant_order
    ) = array['whr>zhy:95.9', 'hzl>zhy:159.0']::text[]
    from public.preview_activity_settlement('fa900000-0000-0000-0000-000000000010') as plan
    join public.participants as from_p on from_p.id = plan.from_participant_id
    join public.participants as to_p on to_p.id = plan.to_participant_id
  ),
  'negative AA refund must conserve -15.5 and leave the netted four-bill plan unchanged'
);

-- Updating the AA bill through the public path must preserve the same stable
-- allocation even when the request array order changes again.
select * from pg_temp.update_expense_fixture(
  (select expense_id from phase9_expenses where label = 'dinner'),
  'fa900000-0000-0000-0000-000000000020', '晚餐（更新）', 156.2, 'CNY', 1, 'aa',
  '[{"participant_id":"fa900000-0000-0000-0000-000000000101","amount":"156.2"}]',
  '[]',
  array[
    'fa900000-0000-0000-0000-000000000102'::uuid,
    'fa900000-0000-0000-0000-000000000103'::uuid,
    'fa900000-0000-0000-0000-000000000101'::uuid
  ],
  '2026-09-09 21:10+08', null, null
);

select pg_temp.assert_true(
  (
    select array_agg(p.name || ':' || s.base_amount::text order by p.participant_order) =
      array['whr:52.1', 'zhy:52.1', 'hzl:52.0']::text[]
    from public.splits as s
    join public.participants as p on p.id = s.participant_id
    where s.expense_id = (select expense_id from phase9_expenses where label = 'dinner')
  ),
  'AA update must use the same deterministic remainder distribution'
);

-- The service-only repair path must produce the same split facts and plan.
reset role;
set local role service_role;
select private.rebuild_activity_debt_projection('fa900000-0000-0000-0000-000000000010');
reset role;
set local role authenticated;
select pg_temp.authenticate('fa900000-0000-0000-0000-000000000001');

select pg_temp.assert_true(
  (
    select array_agg(p.name || ':' || s.base_amount::text order by p.participant_order) =
      array['whr:52.1', 'zhy:52.1', 'hzl:52.0']::text[]
    from public.splits as s
    join public.participants as p on p.id = s.participant_id
    where s.expense_id = (select expense_id from phase9_expenses where label = 'dinner')
  )
  and (
    select array_agg(
      from_p.name || '>' || to_p.name || ':' || plan.amount::text
      order by from_p.participant_order
    ) = array['whr>zhy:95.9', 'hzl>zhy:159.0']::text[]
    from public.preview_activity_settlement('fa900000-0000-0000-0000-000000000010') as plan
    join public.participants as from_p on from_p.id = plan.from_participant_id
    join public.participants as to_p on to_p.id = plan.to_participant_id
  ),
  'full rebuild must preserve the fair AA facts and final settlement plan'
);

-- Soft deletion removes the bill from projections. Expense restoration is a
-- retired lifecycle action, so the historical fact stays deleted.
select pg_temp.assert_true(deleted, 'AA expense delete must succeed')
from public.delete_expense(
  (select expense_id from phase9_expenses where label = 'dinner')
);

select pg_temp.assert_true(
  not exists (
    select 1
    from public.expense_debts as ed
    where ed.expense_id = (select expense_id from phase9_expenses where label = 'dinner')
  ),
  'deleted AA expense must be removed from debt projections'
);

select pg_temp.assert_true(
  (select is_deleted from public.expenses where id = (select expense_id from phase9_expenses where label = 'dinner'))
  and not has_function_privilege('authenticated', 'public.restore_expense(uuid)', 'EXECUTE')
  and not has_function_privilege('service_role', 'public.restore_expense(uuid)', 'EXECUTE'),
  'deleted AA Expense remains a historical fact and restore is retired'
);

reset role;
select pg_temp.assert_true(
  not has_function_privilege(
    'authenticated',
    'private.redistribute_aa_split_base_amounts(uuid)',
    'EXECUTE'
  ),
  'AA allocation helper must remain private'
);

select pass('fair AA allocation and four-bill final settlement regression');
select * from extensions.finish();
rollback;
