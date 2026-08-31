\set ON_ERROR_STOP on

begin;

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

insert into auth.users (
  instance_id,
  id,
  aud,
  role,
  email,
  encrypted_password,
  email_confirmed_at,
  raw_app_meta_data,
  raw_user_meta_data,
  created_at,
  updated_at
)
values
  (
    '00000000-0000-0000-0000-000000000000',
    'e3000000-0000-0000-0000-000000000001',
    'authenticated',
    'authenticated',
    'phase3.member@example.invalid',
    crypt('phase3-password', gen_salt('bf')),
    now(),
    '{}',
    '{"display_name":"Phase 3 Member"}',
    now(),
    now()
  ),
  (
    '00000000-0000-0000-0000-000000000000',
    'e3000000-0000-0000-0000-000000000002',
    'authenticated',
    'authenticated',
    'phase3.outsider@example.invalid',
    crypt('phase3-password', gen_salt('bf')),
    now(),
    '{}',
    '{"display_name":"Phase 3 Outsider"}',
    now(),
    now()
  );

insert into public.activities (
  id,
  join_code,
  name,
  type,
  base_currency,
  multi_currency_enabled,
  created_by
)
values
  ('e0000000-0000-0000-0000-000000000001', '93000001', 'Projection cases', 'normal', 'CNY', false, 'e3000000-0000-0000-0000-000000000001'),
  ('e0000000-0000-0000-0000-000000000002', '93000002', 'Triangle case', 'normal', 'CNY', false, 'e3000000-0000-0000-0000-000000000001'),
  ('e0000000-0000-0000-0000-000000000003', '93000003', 'Refund case', 'normal', 'CNY', false, 'e3000000-0000-0000-0000-000000000001'),
  ('e0000000-0000-0000-0000-000000000004', '93000004', 'Mutation case', 'normal', 'CNY', false, 'e3000000-0000-0000-0000-000000000001');

insert into public.activity_members (activity_id, user_id)
select a.id, 'e3000000-0000-0000-0000-000000000001'::uuid
from public.activities as a
where a.id in (
  'e0000000-0000-0000-0000-000000000001',
  'e0000000-0000-0000-0000-000000000002',
  'e0000000-0000-0000-0000-000000000003',
  'e0000000-0000-0000-0000-000000000004'
);

insert into public.ledger_units (id, activity_id, name, type)
values
  ('e1000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 'Projection ledger', 'default'),
  ('e1000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000002', 'Triangle ledger', 'default'),
  ('e1000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000003', 'Refund ledger', 'default'),
  ('e1000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000004', 'Mutation ledger', 'default');

-- UUID values and input JSON order differ from the authoritative participant order.
insert into public.participants (id, activity_id, name, participant_order)
values
  ('e2000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 'A', 0),
  ('e2000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000001', 'B', 1),
  ('e2000000-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000001', 'C', 2),
  ('e2000000-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000001', 'D', 3),
  ('e2000000-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000001', 'E', 4),
  ('e2000000-0000-0000-0000-000000000101', 'e0000000-0000-0000-0000-000000000002', 'Triangle A', 0),
  ('e2000000-0000-0000-0000-000000000102', 'e0000000-0000-0000-0000-000000000002', 'Triangle B', 1),
  ('e2000000-0000-0000-0000-000000000103', 'e0000000-0000-0000-0000-000000000002', 'Triangle C', 2),
  ('e2000000-0000-0000-0000-000000000201', 'e0000000-0000-0000-0000-000000000003', 'Refund A', 0),
  ('e2000000-0000-0000-0000-000000000202', 'e0000000-0000-0000-0000-000000000003', 'Refund B', 1),
  ('e2000000-0000-0000-0000-000000000301', 'e0000000-0000-0000-0000-000000000004', 'Mutation A', 0),
  ('e2000000-0000-0000-0000-000000000302', 'e0000000-0000-0000-0000-000000000004', 'Mutation B', 1);

set local role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"e3000000-0000-0000-0000-000000000001","role":"authenticated"}',
  true
);

create temporary table phase3_expense_ids (
  label text primary key,
  expense_id uuid not null
) on commit drop;

-- Single payer: B owes A 60.0.
with created as (
  select * from public.create_expense(
    'e1000000-0000-0000-0000-000000000001',
    'Single payer',
    100.0000,
    'CNY',
    1,
    'manual',
    '[{"participant_id":"e2000000-0000-0000-0000-000000000001","amount":"100.0000"}]'::jsonb,
    '[
      {"participant_id":"e2000000-0000-0000-0000-000000000001","amount":"40.0000"},
      {"participant_id":"e2000000-0000-0000-0000-000000000002","amount":"60.0000"}
    ]'::jsonb,
    '{}'::uuid[],
    '2026-08-31 09:00:00+08',
    null,
    null
  )
)
insert into phase3_expense_ids select 'single', expense_id from created;

select pg_temp.assert_true(
  (
    select count(*) = 1
      and bool_and(
        ed.debtor_participant_id = 'e2000000-0000-0000-0000-000000000002'
        and ed.creditor_participant_id = 'e2000000-0000-0000-0000-000000000001'
        and ed.amount = 60.0
      )
    from public.expense_debts as ed
    where ed.expense_id = (select expense_id from phase3_expense_ids where label = 'single')
  ),
  'single payer expense must project B -> A 60.0'
);

-- Two creditors and two debtors, with input JSON deliberately out of order.
with created as (
  select * from public.create_expense(
    'e1000000-0000-0000-0000-000000000001',
    'Multiple sides',
    200.0000,
    'CNY',
    1,
    'manual',
    '[
      {"participant_id":"e2000000-0000-0000-0000-000000000002","amount":"50.0000"},
      {"participant_id":"e2000000-0000-0000-0000-000000000001","amount":"150.0000"}
    ]'::jsonb,
    '[
      {"participant_id":"e2000000-0000-0000-0000-000000000004","amount":"80.0000"},
      {"participant_id":"e2000000-0000-0000-0000-000000000003","amount":"120.0000"}
    ]'::jsonb,
    '{}'::uuid[],
    '2026-08-31 09:05:00+08',
    null,
    null
  )
)
insert into phase3_expense_ids select 'multiple', expense_id from created;

select pg_temp.assert_true(
  (
    select array_agg(
      ed.debtor_participant_id::text || '>' || ed.creditor_participant_id::text || ':' || ed.amount::text
      order by p_debtor.participant_order, ed.debtor_participant_id,
               p_creditor.participant_order, ed.creditor_participant_id
    ) = array[
      'e2000000-0000-0000-0000-000000000003>e2000000-0000-0000-0000-000000000001:120.0',
      'e2000000-0000-0000-0000-000000000004>e2000000-0000-0000-0000-000000000001:30.0',
      'e2000000-0000-0000-0000-000000000004>e2000000-0000-0000-0000-000000000002:50.0'
    ]::text[]
    from public.expense_debts as ed
    join public.participants as p_debtor on p_debtor.id = ed.debtor_participant_id
    join public.participants as p_creditor on p_creditor.id = ed.creditor_participant_id
    where ed.expense_id = (select expense_id from phase3_expense_ids where label = 'multiple')
  ),
  'multiple creditors/debtors must use deterministic greedy matching'
);

-- Participant ordering, followed by UUID as the deterministic secondary key.
with created as (
  select * from public.create_expense(
    'e1000000-0000-0000-0000-000000000001',
    'Order and id tie-break',
    100.0000,
    'CNY',
    1,
    'manual',
    '[
      {"participant_id":"e2000000-0000-0000-0000-000000000003","amount":"50.0000"},
      {"participant_id":"e2000000-0000-0000-0000-000000000002","amount":"50.0000"}
    ]'::jsonb,
    '[
      {"participant_id":"e2000000-0000-0000-0000-000000000005","amount":"25.0000"},
      {"participant_id":"e2000000-0000-0000-0000-000000000004","amount":"75.0000"}
    ]'::jsonb,
    '{}'::uuid[],
    '2026-08-31 09:10:00+08',
    null,
    null
  )
)
insert into phase3_expense_ids select 'tie_break', expense_id from created;

select pg_temp.assert_true(
  (
    select array_agg(
      ed.debtor_participant_id::text || '>' || ed.creditor_participant_id::text || ':' || ed.amount::text
      order by p_debtor.participant_order, ed.debtor_participant_id,
               p_creditor.participant_order, ed.creditor_participant_id
    ) = array[
      'e2000000-0000-0000-0000-000000000004>e2000000-0000-0000-0000-000000000002:50.0',
      'e2000000-0000-0000-0000-000000000004>e2000000-0000-0000-0000-000000000003:25.0',
      'e2000000-0000-0000-0000-000000000005>e2000000-0000-0000-0000-000000000003:25.0'
    ]::text[]
    from public.expense_debts as ed
    join public.participants as p_debtor on p_debtor.id = ed.debtor_participant_id
    join public.participants as p_creditor on p_creditor.id = ed.creditor_participant_id
    where ed.expense_id = (select expense_id from phase3_expense_ids where label = 'tie_break')
  ),
  'participant_order then participant_id must drive deterministic matching'
);

-- A second B -> A expense aggregates with the first one.
with created as (
  select * from public.create_expense(
    'e1000000-0000-0000-0000-000000000001',
    'Same direction aggregation',
    40.0000,
    'CNY',
    1,
    'manual',
    '[{"participant_id":"e2000000-0000-0000-0000-000000000001","amount":"40.0000"}]'::jsonb,
    '[{"participant_id":"e2000000-0000-0000-0000-000000000002","amount":"40.0000"}]'::jsonb,
    '{}'::uuid[],
    '2026-08-31 09:15:00+08',
    null,
    null
  )
)
insert into phase3_expense_ids select 'same_direction', expense_id from created;

select pg_temp.assert_true(
  exists (
    select 1 from public.bilateral_debts as bd
    where bd.activity_id = 'e0000000-0000-0000-0000-000000000001'
      and bd.debtor_participant_id = 'e2000000-0000-0000-0000-000000000002'
      and bd.creditor_participant_id = 'e2000000-0000-0000-0000-000000000001'
      and bd.amount = 100.0
  ),
  'same-direction ExpenseDebts must aggregate across expenses'
);

-- Reverse A -> B 30.0 nets only this unordered pair to B -> A 70.0.
with created as (
  select * from public.create_expense(
    'e1000000-0000-0000-0000-000000000001',
    'Reverse direction offset',
    30.0000,
    'CNY',
    1,
    'manual',
    '[{"participant_id":"e2000000-0000-0000-0000-000000000002","amount":"30.0000"}]'::jsonb,
    '[{"participant_id":"e2000000-0000-0000-0000-000000000001","amount":"30.0000"}]'::jsonb,
    '{}'::uuid[],
    '2026-08-31 09:20:00+08',
    null,
    null
  )
)
insert into phase3_expense_ids select 'reverse', expense_id from created;

select pg_temp.assert_true(
  (
    select count(*) = 1 and bool_and(
      bd.debtor_participant_id = 'e2000000-0000-0000-0000-000000000002'
      and bd.creditor_participant_id = 'e2000000-0000-0000-0000-000000000001'
      and bd.amount = 70.0
    )
    from public.bilateral_debts as bd
    where bd.activity_id = 'e0000000-0000-0000-0000-000000000001'
      and least(bd.debtor_participant_id, bd.creditor_participant_id)
          = 'e2000000-0000-0000-0000-000000000001'
      and greatest(bd.debtor_participant_id, bd.creditor_participant_id)
          = 'e2000000-0000-0000-0000-000000000002'
  ),
  'opposite directions must net to one positive bilateral direction'
);

-- A three-person cycle remains three bilateral rows; there is no path netting.
with created as (
  select * from public.create_expense(
    'e1000000-0000-0000-0000-000000000002', 'Triangle AB', 50.0000, 'CNY', 1, 'manual',
    '[{"participant_id":"e2000000-0000-0000-0000-000000000101","amount":"50.0000"}]'::jsonb,
    '[{"participant_id":"e2000000-0000-0000-0000-000000000102","amount":"50.0000"}]'::jsonb,
    '{}'::uuid[], '2026-08-31 10:00:00+08', null, null
  )
)
insert into phase3_expense_ids select 'triangle_ab', expense_id from created;

with created as (
  select * from public.create_expense(
    'e1000000-0000-0000-0000-000000000002', 'Triangle BC', 50.0000, 'CNY', 1, 'manual',
    '[{"participant_id":"e2000000-0000-0000-0000-000000000102","amount":"50.0000"}]'::jsonb,
    '[{"participant_id":"e2000000-0000-0000-0000-000000000103","amount":"50.0000"}]'::jsonb,
    '{}'::uuid[], '2026-08-31 10:05:00+08', null, null
  )
)
insert into phase3_expense_ids select 'triangle_bc', expense_id from created;

with created as (
  select * from public.create_expense(
    'e1000000-0000-0000-0000-000000000002', 'Triangle CA', 50.0000, 'CNY', 1, 'manual',
    '[{"participant_id":"e2000000-0000-0000-0000-000000000103","amount":"50.0000"}]'::jsonb,
    '[{"participant_id":"e2000000-0000-0000-0000-000000000101","amount":"50.0000"}]'::jsonb,
    '{}'::uuid[], '2026-08-31 10:10:00+08', null, null
  )
)
insert into phase3_expense_ids select 'triangle_ca', expense_id from created;

select pg_temp.assert_true(
  (
    select count(*) = 3 and pg_catalog.sum(amount) = 150.0
    from public.bilateral_debts
    where activity_id = 'e0000000-0000-0000-0000-000000000002'
  ),
  'three-person cycle must not be optimized away'
);

-- Negative Expense uses the identical net/matching algorithm. The refund is
-- the exact reverse of the original, so bilateral debt becomes zero.
with created as (
  select * from public.create_expense(
    'e1000000-0000-0000-0000-000000000003', 'Refund original', 100.0000, 'CNY', 1, 'manual',
    '[{"participant_id":"e2000000-0000-0000-0000-000000000201","amount":"100.0000"}]'::jsonb,
    '[
      {"participant_id":"e2000000-0000-0000-0000-000000000201","amount":"40.0000"},
      {"participant_id":"e2000000-0000-0000-0000-000000000202","amount":"60.0000"}
    ]'::jsonb,
    '{}'::uuid[], '2026-08-31 11:00:00+08', null, null
  )
)
insert into phase3_expense_ids select 'refund_original', expense_id from created;

with created as (
  select * from public.create_expense(
    'e1000000-0000-0000-0000-000000000003', 'Negative refund', -100.0000, 'CNY', 1, 'manual',
    '[{"participant_id":"e2000000-0000-0000-0000-000000000201","amount":"-100.0000"}]'::jsonb,
    '[
      {"participant_id":"e2000000-0000-0000-0000-000000000201","amount":"-40.0000"},
      {"participant_id":"e2000000-0000-0000-0000-000000000202","amount":"-60.0000"}
    ]'::jsonb,
    '{}'::uuid[],
    '2026-08-31 11:05:00+08',
    null,
    (select expense_id from phase3_expense_ids where label = 'refund_original')
  )
)
insert into phase3_expense_ids select 'negative_refund', expense_id from created;

select pg_temp.assert_true(
  exists (
    select 1 from public.expense_debts as ed
    where ed.expense_id = (select expense_id from phase3_expense_ids where label = 'negative_refund')
      and ed.debtor_participant_id = 'e2000000-0000-0000-0000-000000000201'
      and ed.creditor_participant_id = 'e2000000-0000-0000-0000-000000000202'
      and ed.amount = 60.0
  )
  and not exists (
    select 1 from public.bilateral_debts as bd
    where bd.activity_id = 'e0000000-0000-0000-0000-000000000003'
  ),
  'negative refund must reverse direction and cancel the original pair'
);

-- create -> update -> delete all update projections in the same RPC transaction.
with created as (
  select * from public.create_expense(
    'e1000000-0000-0000-0000-000000000004', 'Mutable', 90.0000, 'CNY', 1, 'manual',
    '[{"participant_id":"e2000000-0000-0000-0000-000000000301","amount":"90.0000"}]'::jsonb,
    '[
      {"participant_id":"e2000000-0000-0000-0000-000000000301","amount":"30.0000"},
      {"participant_id":"e2000000-0000-0000-0000-000000000302","amount":"60.0000"}
    ]'::jsonb,
    '{}'::uuid[], '2026-08-31 12:00:00+08', null, null
  )
)
insert into phase3_expense_ids select 'mutable', expense_id from created;

select pg_temp.assert_true(
  exists (
    select 1 from public.bilateral_debts
    where activity_id = 'e0000000-0000-0000-0000-000000000004' and amount = 60.0
  ),
  'create_expense must build projections before returning'
);

select pg_temp.assert_true(base_amount = 50.0 and version = 2, 'update must retain Phase 2C return/version semantics')
from public.update_expense(
  (select expense_id from phase3_expense_ids where label = 'mutable'),
  'e1000000-0000-0000-0000-000000000004',
  'Mutable updated',
  50.0000,
  'CNY',
  1,
  'manual',
  '[{"participant_id":"e2000000-0000-0000-0000-000000000301","amount":"50.0000"}]'::jsonb,
  '[
    {"participant_id":"e2000000-0000-0000-0000-000000000301","amount":"30.0000"},
    {"participant_id":"e2000000-0000-0000-0000-000000000302","amount":"20.0000"}
  ]'::jsonb,
  '{}'::uuid[],
  '2026-08-31 12:05:00+08',
  null,
  null
);

select pg_temp.assert_true(
  (
    select count(*) = 1 and bool_and(amount = 20.0)
    from public.bilateral_debts
    where activity_id = 'e0000000-0000-0000-0000-000000000004'
  ),
  'update_expense must replace stale projection values'
);

select pg_temp.assert_true(deleted and version = 3, 'delete must retain Phase 2B version semantics')
from public.delete_expense((select expense_id from phase3_expense_ids where label = 'mutable'));

select pg_temp.assert_true(
  not exists (
    select 1 from public.expense_debts
    where expense_id = (select expense_id from phase3_expense_ids where label = 'mutable')
  )
  and not exists (
    select 1 from public.bilateral_debts
    where activity_id = 'e0000000-0000-0000-0000-000000000004'
  ),
  'logical delete must remove the Expense and Activity debt projections'
);

-- A member can read projections but cannot mutate them directly.
do $test$
begin
  begin
    insert into public.expense_debts (
      activity_id, expense_id, debtor_participant_id, creditor_participant_id, amount
    ) values (
      'e0000000-0000-0000-0000-000000000001',
      (select expense_id from phase3_expense_ids where label = 'single'),
      'e2000000-0000-0000-0000-000000000002',
      'e2000000-0000-0000-0000-000000000001',
      1.0
    );
    raise exception 'direct ExpenseDebt insert unexpectedly succeeded';
  exception when insufficient_privilege then null;
  end;

  begin
    update public.bilateral_debts set amount = amount + 1;
    raise exception 'direct BilateralDebt update unexpectedly succeeded';
  exception when insufficient_privilege then null;
  end;

  begin
    delete from public.expense_debts;
    raise exception 'direct ExpenseDebt delete unexpectedly succeeded';
  exception when insufficient_privilege then null;
  end;
end;
$test$;

select pg_temp.assert_true(
  (select count(*) > 0 from public.expense_debts)
  and (select count(*) > 0 from public.bilateral_debts),
  'Activity member must be able to read both debt projections'
);

-- Authenticated non-members have SELECT privilege but RLS exposes no rows.
select set_config(
  'request.jwt.claims',
  '{"sub":"e3000000-0000-0000-0000-000000000002","role":"authenticated"}',
  true
);

select pg_temp.assert_true(
  (select count(*) = 0 from public.expense_debts)
  and (select count(*) = 0 from public.bilateral_debts),
  'authenticated non-members must not read debt projections'
);

reset role;

-- Full Activity rebuild must be byte-for-byte equivalent on business columns
-- to all preceding incremental rebuilds.
create temporary table expected_expense_debts on commit drop as
select activity_id, expense_id, debtor_participant_id, creditor_participant_id, amount
from public.expense_debts
where activity_id = 'e0000000-0000-0000-0000-000000000001';

create temporary table expected_bilateral_debts on commit drop as
select activity_id, debtor_participant_id, creditor_participant_id, amount
from public.bilateral_debts
where activity_id = 'e0000000-0000-0000-0000-000000000001';

select private.rebuild_activity_debt_projection('e0000000-0000-0000-0000-000000000001');

select pg_temp.assert_true(
  not exists (
    (select activity_id, expense_id, debtor_participant_id, creditor_participant_id, amount
     from public.expense_debts
     where activity_id = 'e0000000-0000-0000-0000-000000000001')
    except table expected_expense_debts
  )
  and not exists (
    (table expected_expense_debts)
    except
    (select activity_id, expense_id, debtor_participant_id, creditor_participant_id, amount
     from public.expense_debts
     where activity_id = 'e0000000-0000-0000-0000-000000000001')
  ),
  'full rebuild ExpenseDebts must equal incremental results'
);

select pg_temp.assert_true(
  not exists (
    (select activity_id, debtor_participant_id, creditor_participant_id, amount
     from public.bilateral_debts
     where activity_id = 'e0000000-0000-0000-0000-000000000001')
    except table expected_bilateral_debts
  )
  and not exists (
    (table expected_bilateral_debts)
    except
    (select activity_id, debtor_participant_id, creditor_participant_id, amount
     from public.bilateral_debts
     where activity_id = 'e0000000-0000-0000-0000-000000000001')
  ),
  'full rebuild BilateralDebts must equal incremental results'
);

select pg_temp.assert_true(
  not has_table_privilege('anon', 'public.expense_debts', 'SELECT')
  and not has_table_privilege('anon', 'public.bilateral_debts', 'SELECT')
  and not has_table_privilege('authenticated', 'public.expense_debts', 'INSERT,UPDATE,DELETE')
  and not has_table_privilege('authenticated', 'public.bilateral_debts', 'INSERT,UPDATE,DELETE'),
  'anon cannot read and authenticated clients cannot DML debt projections'
);

select pg_temp.assert_true(
  not has_function_privilege(
    'authenticated',
    'private.rebuild_activity_debt_projection(uuid)',
    'EXECUTE'
  )
  and has_function_privilege(
    'service_role',
    'private.rebuild_activity_debt_projection(uuid)',
    'EXECUTE'
  ),
  'full rebuild must remain internal/service-role only'
);

select pg_temp.assert_true(
  not has_function_privilege(
    'authenticated',
    'private.create_expense_impl(uuid,text,numeric,character,numeric,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)',
    'EXECUTE'
  )
  and not has_function_privilege(
    'authenticated',
    'private.update_expense_impl(uuid,uuid,text,numeric,character,numeric,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)',
    'EXECUTE'
  )
  and not has_function_privilege(
    'authenticated',
    'private.delete_expense_impl(uuid)',
    'EXECUTE'
  ),
  'authenticated clients must not bypass projection-aware Expense wrappers'
);

select pg_temp.assert_true(
  (
    select count(*) = 8
      and bool_and(p.prosecdef)
      and bool_and(p.proconfig @> array['search_path=""']::text[])
    from pg_proc as p
    join pg_namespace as n on n.oid = p.pronamespace
    where n.nspname = 'private'
      and p.proname in (
        'lock_debt_projection_activity',
        'rebuild_expense_debts_locked',
        'rebuild_bilateral_debts_locked',
        'rebuild_expense_and_bilateral_debts',
        'rebuild_activity_debt_projection',
        'create_expense_projected_impl',
        'update_expense_projected_impl',
        'delete_expense_projected_impl'
      )
  ),
  'all debt helpers must be SECURITY DEFINER with an empty search_path'
);

select pg_temp.assert_true(
  pg_catalog.strpos(
    pg_catalog.lower(
      pg_catalog.pg_get_functiondef(
        'private.rebuild_expense_debts_locked(uuid,uuid)'::regprocedure
      )
    ),
    'order by participant_order, participant_id'
  ) > 0,
  'greedy matching must retain participant_order and participant_id sorting'
);

select pg_temp.assert_true(
  not exists (
    select ed.expense_id, ed.debtor_participant_id, ed.creditor_participant_id
    from public.expense_debts as ed
    group by ed.expense_id, ed.debtor_participant_id, ed.creditor_participant_id
    having count(*) > 1
  )
  and not exists (
    select
      bd.activity_id,
      least(bd.debtor_participant_id, bd.creditor_participant_id),
      greatest(bd.debtor_participant_id, bd.creditor_participant_id)
    from public.bilateral_debts as bd
    group by
      bd.activity_id,
      least(bd.debtor_participant_id, bd.creditor_participant_id),
      greatest(bd.debtor_participant_id, bd.creditor_participant_id)
    having count(*) > 1
  ),
  'Expense results and canonical bilateral pairs must remain unique'
);

with participant_nets as (
  select
    e.id as expense_id,
    p.id as participant_id,
    coalesce((
      select pg_catalog.sum(pay.base_amount)
      from public.payments as pay
      where pay.expense_id = e.id and pay.participant_id = p.id
    ), 0::numeric) - coalesce((
      select pg_catalog.sum(s.base_amount)
      from public.splits as s
      where s.expense_id = e.id and s.participant_id = p.id
    ), 0::numeric) as net_amount
  from public.expenses as e
  join public.ledger_units as lu on lu.id = e.ledger_unit_id
  join public.participants as p on p.activity_id = lu.activity_id
  where not e.is_deleted
),
creditor_totals as (
  select expense_id, coalesce(pg_catalog.sum(net_amount) filter (where net_amount > 0), 0) as amount
  from participant_nets
  group by expense_id
),
projected_totals as (
  select ed.expense_id, pg_catalog.sum(ed.amount) as amount
  from public.expense_debts as ed
  group by ed.expense_id
)
select pg_temp.assert_true(
  not exists (
    select 1
    from creditor_totals as c
    left join projected_totals as projected using (expense_id)
    where c.amount is distinct from coalesce(projected.amount, 0)
  ),
  'every ExpenseDebt match must strictly conserve the positive participant net total'
);

select pg_temp.assert_true(
  (
    select count(*) = 7
    from pg_constraint as c
    where c.conname in (
      'expense_debts_expense_ledger_unit_fk',
      'expense_debts_ledger_unit_activity_fk',
      'expense_debts_debtor_activity_fk',
      'expense_debts_creditor_activity_fk',
      'bilateral_debts_debtor_activity_fk',
      'bilateral_debts_creditor_activity_fk',
      'expense_debts_unique_result'
    )
  ),
  'projection rows must retain fact, Activity, participant, and uniqueness constraints'
);

select pg_temp.assert_true(
  (
    select pg_catalog.format_type(a.atttypid, a.atttypmod) = 'numeric(20,1)'
      and a.attnotnull
    from pg_attribute as a
    where a.attrelid = 'public.expense_debts'::regclass
      and a.attname = 'amount'
      and not a.attisdropped
  )
  and (
    select pg_catalog.format_type(a.atttypid, a.atttypmod) = 'numeric(20,1)'
      and a.attnotnull
    from pg_attribute as a
    where a.attrelid = 'public.bilateral_debts'::regclass
      and a.attname = 'amount'
      and not a.attisdropped
  ),
  'debt amount columns must be NOT NULL numeric(20,1)'
);

rollback;
