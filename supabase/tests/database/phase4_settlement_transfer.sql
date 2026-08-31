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

create function pg_temp.authenticate(p_user_id uuid)
returns void
language plpgsql
as $function$
begin
  perform set_config(
    'request.jwt.claims',
    pg_catalog.json_build_object('sub', p_user_id, 'role', 'authenticated')::text,
    true
  );
end;
$function$;

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at
)
values
  ('00000000-0000-0000-0000-000000000000', 'f4300000-0000-0000-0000-000000000001', 'authenticated', 'authenticated', 'phase4.creator@example.invalid', crypt('phase4-password', gen_salt('bf')), now(), '{}', '{}', now(), now()),
  ('00000000-0000-0000-0000-000000000000', 'f4300000-0000-0000-0000-000000000002', 'authenticated', 'authenticated', 'phase4.member@example.invalid', crypt('phase4-password', gen_salt('bf')), now(), '{}', '{}', now(), now()),
  ('00000000-0000-0000-0000-000000000000', 'f4300000-0000-0000-0000-000000000003', 'authenticated', 'authenticated', 'phase4.outsider@example.invalid', crypt('phase4-password', gen_salt('bf')), now(), '{}', '{}', now(), now());

insert into public.activities (
  id, join_code, name, type, base_currency, multi_currency_enabled, created_by
)
values
  ('f4000000-0000-0000-0000-000000000001', '94000001', 'Settlement basics', 'normal', 'CNY', false, 'f4300000-0000-0000-0000-000000000001'),
  ('f4000000-0000-0000-0000-000000000002', '94000002', 'Bilateral allocation', 'normal', 'CNY', false, 'f4300000-0000-0000-0000-000000000001'),
  ('f4000000-0000-0000-0000-000000000003', '94000003', 'Archived writes', 'normal', 'CNY', false, 'f4300000-0000-0000-0000-000000000001'),
  ('f4000000-0000-0000-0000-000000000004', '94000004', 'Creator on behalf', 'normal', 'USD', false, 'f4300000-0000-0000-0000-000000000001');

insert into public.activity_members (activity_id, user_id)
select a.id, u.id
from public.activities as a
cross join auth.users as u
where a.id in (
  'f4000000-0000-0000-0000-000000000001',
  'f4000000-0000-0000-0000-000000000002',
  'f4000000-0000-0000-0000-000000000003',
  'f4000000-0000-0000-0000-000000000004'
)
and u.id in (
  'f4300000-0000-0000-0000-000000000001',
  'f4300000-0000-0000-0000-000000000002'
);

insert into public.ledger_units (id, activity_id, name, type)
values
  ('f4100000-0000-0000-0000-000000000001', 'f4000000-0000-0000-0000-000000000001', 'Basics', 'default'),
  ('f4100000-0000-0000-0000-000000000002', 'f4000000-0000-0000-0000-000000000002', 'Allocation', 'default'),
  ('f4100000-0000-0000-0000-000000000003', 'f4000000-0000-0000-0000-000000000003', 'Archived', 'default'),
  ('f4100000-0000-0000-0000-000000000004', 'f4000000-0000-0000-0000-000000000004', 'On behalf', 'default');

insert into public.participants (id, activity_id, name, participant_order)
values
  ('f4200000-0000-0000-0000-000000000011', 'f4000000-0000-0000-0000-000000000001', 'A1', 0),
  ('f4200000-0000-0000-0000-000000000012', 'f4000000-0000-0000-0000-000000000001', 'B1', 1),
  ('f4200000-0000-0000-0000-000000000013', 'f4000000-0000-0000-0000-000000000001', 'C1', 2),
  ('f4200000-0000-0000-0000-000000000021', 'f4000000-0000-0000-0000-000000000002', 'A2', 0),
  ('f4200000-0000-0000-0000-000000000022', 'f4000000-0000-0000-0000-000000000002', 'B2', 1),
  ('f4200000-0000-0000-0000-000000000031', 'f4000000-0000-0000-0000-000000000003', 'A3', 0),
  ('f4200000-0000-0000-0000-000000000032', 'f4000000-0000-0000-0000-000000000003', 'B3', 1),
  ('f4200000-0000-0000-0000-000000000041', 'f4000000-0000-0000-0000-000000000004', 'A4', 0),
  ('f4200000-0000-0000-0000-000000000042', 'f4000000-0000-0000-0000-000000000004', 'B4', 1),
  ('f4200000-0000-0000-0000-000000000043', 'f4000000-0000-0000-0000-000000000004', 'C4 unclaimed', 2),
  ('f4200000-0000-0000-0000-000000000044', 'f4000000-0000-0000-0000-000000000004', 'D4 unclaimed', 3);

insert into public.participant_claims (activity_id, participant_id, user_id)
values
  ('f4000000-0000-0000-0000-000000000001', 'f4200000-0000-0000-0000-000000000011', 'f4300000-0000-0000-0000-000000000001'),
  ('f4000000-0000-0000-0000-000000000001', 'f4200000-0000-0000-0000-000000000012', 'f4300000-0000-0000-0000-000000000002'),
  ('f4000000-0000-0000-0000-000000000002', 'f4200000-0000-0000-0000-000000000021', 'f4300000-0000-0000-0000-000000000001'),
  ('f4000000-0000-0000-0000-000000000002', 'f4200000-0000-0000-0000-000000000022', 'f4300000-0000-0000-0000-000000000002'),
  ('f4000000-0000-0000-0000-000000000003', 'f4200000-0000-0000-0000-000000000031', 'f4300000-0000-0000-0000-000000000001'),
  ('f4000000-0000-0000-0000-000000000003', 'f4200000-0000-0000-0000-000000000032', 'f4300000-0000-0000-0000-000000000002'),
  ('f4000000-0000-0000-0000-000000000004', 'f4200000-0000-0000-0000-000000000041', 'f4300000-0000-0000-0000-000000000001'),
  ('f4000000-0000-0000-0000-000000000004', 'f4200000-0000-0000-0000-000000000042', 'f4300000-0000-0000-0000-000000000002');

set local role authenticated;
select pg_temp.authenticate('f4300000-0000-0000-0000-000000000001');

create temporary table phase4_ids (
  label text primary key,
  object_id uuid not null
) on commit drop;

-- Two B -> A debts establish Expense FIFO capacity and financial_version 2.
with created as (
  select * from public.create_expense(
    'f4100000-0000-0000-0000-000000000001', 'Old B to A', 60, 'CNY', 1, 'manual',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000011","amount":"60"}]',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000012","amount":"60"}]',
    '{}', '2026-08-31 09:00:00+08', null, null
  )
) insert into phase4_ids select 'basic_e1', expense_id from created;

with created as (
  select * from public.create_expense(
    'f4100000-0000-0000-0000-000000000001', 'New B to A', 40, 'CNY', 1, 'manual',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000011","amount":"40"}]',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000012","amount":"40"}]',
    '{}', '2026-08-31 10:00:00+08', null, null
  )
) insert into phase4_ids select 'basic_e2', expense_id from created;

-- Counterexample: old A->B 50, reverse B->A 70, new A->B 100. Expense-only
-- bilateral is A->B 80, whose residual queue is only the newest ExpenseDebt.
with created as (
  select * from public.create_expense(
    'f4100000-0000-0000-0000-000000000002', 'Old A to B', 50, 'CNY', 1, 'manual',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000022","amount":"50"}]',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000021","amount":"50"}]',
    '{}', '2026-08-31 09:00:00+08', null, null
  )
) insert into phase4_ids select 'counter_e1', expense_id from created;

with created as (
  select * from public.create_expense(
    'f4100000-0000-0000-0000-000000000002', 'Reverse B to A', 70, 'CNY', 1, 'manual',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000021","amount":"70"}]',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000022","amount":"70"}]',
    '{}', '2026-08-31 10:00:00+08', null, null
  )
) insert into phase4_ids select 'counter_e2', expense_id from created;

with created as (
  select * from public.create_expense(
    'f4100000-0000-0000-0000-000000000002', 'New A to B', 100, 'CNY', 1, 'manual',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000022","amount":"100"}]',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000021","amount":"100"}]',
    '{}', '2026-08-31 11:00:00+08', null, null
  )
) insert into phase4_ids select 'counter_e3', expense_id from created;

with created as (
  select * from public.create_expense(
    'f4100000-0000-0000-0000-000000000003', 'Archived source', 50, 'CNY', 1, 'manual',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000031","amount":"50"}]',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000032","amount":"50"}]',
    '{}', '2026-08-31 09:00:00+08', null, null
  )
) insert into phase4_ids select 'archived_e1', expense_id from created;

with created as (
  select * from public.create_expense(
    'f4100000-0000-0000-0000-000000000004', 'C owes D', 25, 'USD', 1, 'manual',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000044","amount":"25"}]',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000043","amount":"25"}]',
    '{}', '2026-08-31 09:00:00+08', null, null
  )
) insert into phase4_ids select 'behalf_e1', expense_id from created;

with created as (
  select * from public.create_expense(
    'f4100000-0000-0000-0000-000000000004', 'B owes A', 10, 'USD', 1, 'manual',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000041","amount":"10"}]',
    '[{"participant_id":"f4200000-0000-0000-0000-000000000042","amount":"10"}]',
    '{}', '2026-08-31 10:00:00+08', null, null
  )
) insert into phase4_ids select 'behalf_e2', expense_id from created;

select pg_temp.assert_true(
  (select financial_version = 2 from public.activities where id = 'f4000000-0000-0000-0000-000000000001')
  and (select financial_version = 3 from public.activities where id = 'f4000000-0000-0000-0000-000000000002')
  and (select financial_version = 1 from public.activities where id = 'f4000000-0000-0000-0000-000000000003'),
  'each successful Expense create must increment financial_version exactly once'
);

-- Member B records a partial transfer.
select pg_temp.authenticate('f4300000-0000-0000-0000-000000000002');
with created as (
  select * from public.create_settlement_transfer(
    'f4000000-0000-0000-0000-000000000001',
    'f4200000-0000-0000-0000-000000000012',
    'f4200000-0000-0000-0000-000000000011',
    30, '2026-08-31 11:00:00+08', null
  )
) insert into phase4_ids select 'basic_t1', transfer_id from created;

select pg_temp.assert_true(
  (select amount = 70 from public.bilateral_debts where activity_id = 'f4000000-0000-0000-0000-000000000001')
  and (select pg_catalog.sum(amount) = 30 from public.transfer_allocations where transfer_id = (select object_id from phase4_ids where label = 'basic_t1'))
  and (select financial_version = 3 from public.activities where id = 'f4000000-0000-0000-0000-000000000001'),
  'partial settlement must update allocations, bilateral debt, and version atomically'
);

-- Exceeding the post-lock current debt has no fact/projection/version side effect.
do $test$
declare
  v_before bigint;
  v_count bigint;
begin
  select financial_version into v_before from public.activities where id = 'f4000000-0000-0000-0000-000000000001';
  select count(*) into v_count from public.transfers where activity_id = 'f4000000-0000-0000-0000-000000000001';
  begin
    perform * from public.create_settlement_transfer(
      'f4000000-0000-0000-0000-000000000001',
      'f4200000-0000-0000-0000-000000000012',
      'f4200000-0000-0000-0000-000000000011', 71, now(), null
    );
    raise exception 'over-settlement unexpectedly succeeded';
  exception when check_violation then null;
  end;
  perform pg_temp.assert_true(
    (select financial_version = v_before from public.activities where id = 'f4000000-0000-0000-0000-000000000001')
    and (select count(*) = v_count from public.transfers where activity_id = 'f4000000-0000-0000-0000-000000000001'),
    'failed over-settlement must have no side effect'
  );
end;
$test$;

with created as (
  select * from public.create_settlement_transfer(
    'f4000000-0000-0000-0000-000000000001',
    'f4200000-0000-0000-0000-000000000012',
    'f4200000-0000-0000-0000-000000000011',
    70, '2026-08-31 12:00:00+08', null
  )
) insert into phase4_ids select 'basic_t2', transfer_id from created;

select pg_temp.assert_true(
  not exists (select 1 from public.bilateral_debts where activity_id = 'f4000000-0000-0000-0000-000000000001')
  and (
    select array_agg(
      t.id::text || ':' || e.title || ':' || ta.amount::text
      order by t.occurred_at, t.created_at, t.id, e.occurred_at, e.created_at, e.id
    ) = array[
      (select object_id::text from phase4_ids where label = 'basic_t1') || ':Old B to A:30.0',
      (select object_id::text from phase4_ids where label = 'basic_t2') || ':Old B to A:30.0',
      (select object_id::text from phase4_ids where label = 'basic_t2') || ':New B to A:40.0'
    ]::text[]
    from public.transfer_allocations as ta
    join public.transfers as t on t.id = ta.transfer_id
    join public.expense_debts as ed on ed.id = ta.expense_debt_id
    join public.expenses as e on e.id = ed.expense_id
    where ta.activity_id = 'f4000000-0000-0000-0000-000000000001'
  ),
  'multiple Transfers and Expense allocations must both follow stable FIFO order'
);

select pg_temp.assert_true(voided and financial_version = 5, 'Member may void a self-recorded Transfer')
from public.void_settlement_transfer(
  (select object_id from phase4_ids where label = 'basic_t2'), 'wrong amount'
);

do $test$
declare v_before bigint;
begin
  select financial_version into v_before from public.activities where id = 'f4000000-0000-0000-0000-000000000001';
  begin
    perform * from public.void_settlement_transfer(
      (select object_id from phase4_ids where label = 'basic_t2'), 'again'
    );
    raise exception 'second void unexpectedly succeeded';
  exception when object_not_in_prerequisite_state then null;
  end;
  perform pg_temp.assert_true(
    (select financial_version = v_before from public.activities where id = 'f4000000-0000-0000-0000-000000000001'),
    'already-voided rejection must not increment version'
  );
end;
$test$;

-- Creator participates as claimed A without an on-behalf marker.
select pg_temp.authenticate('f4300000-0000-0000-0000-000000000001');
with created as (
  select * from public.create_settlement_transfer(
    'f4000000-0000-0000-0000-000000000001',
    'f4200000-0000-0000-0000-000000000012',
    'f4200000-0000-0000-0000-000000000011', 20, now(), null
  )
) insert into phase4_ids select 'creator_t1', transfer_id from created;

select pg_temp.authenticate('f4300000-0000-0000-0000-000000000002');
do $test$
begin
  begin
    perform * from public.void_settlement_transfer(
      (select object_id from phase4_ids where label = 'creator_t1'), 'not mine'
    );
    raise exception 'Member voided another recorder transfer';
  exception when insufficient_privilege then null;
  end;
end;
$test$;

select pg_temp.authenticate('f4300000-0000-0000-0000-000000000001');
select pg_temp.assert_true(voided, 'Creator may void any member Transfer')
from public.void_settlement_transfer((select object_id from phase4_ids where label = 'creator_t1'), 'creator correction');
select pg_temp.assert_true(voided, 'Creator may void a Member-recorded Transfer')
from public.void_settlement_transfer((select object_id from phase4_ids where label = 'basic_t1'), 'creator correction');

-- A claimed participant cannot be used as a Creator on-behalf identity.
do $test$
begin
  begin
    perform * from public.create_settlement_transfer(
      'f4000000-0000-0000-0000-000000000001',
      'f4200000-0000-0000-0000-000000000012',
      'f4200000-0000-0000-0000-000000000011', 1, now(),
      'f4200000-0000-0000-0000-000000000012'
    );
    raise exception 'Creator acted for a claimed Participant';
  exception when insufficient_privilege then null;
  end;
end;
$test$;

-- Both parties are unclaimed: Creator must explicitly choose one unclaimed
-- endpoint as the action perspective. Currency comes only from Activity.
do $test$
begin
  begin
    perform * from public.create_settlement_transfer(
      'f4000000-0000-0000-0000-000000000004',
      'f4200000-0000-0000-0000-000000000043',
      'f4200000-0000-0000-0000-000000000044', 25, now(), null
    );
    raise exception 'Creator omitted required on-behalf identity';
  exception when insufficient_privilege then null;
  end;
end;
$test$;

with created as (
  select * from public.create_settlement_transfer(
    'f4000000-0000-0000-0000-000000000004',
    'f4200000-0000-0000-0000-000000000043',
    'f4200000-0000-0000-0000-000000000044', 25,
    '2026-08-31 12:00:00+08', 'f4200000-0000-0000-0000-000000000043'
  )
) insert into phase4_ids select 'behalf_t1', transfer_id from created;

select pg_temp.assert_true(
  (
    select type = 'settlement' and currency = 'USD'
      and recorded_by = 'f4300000-0000-0000-0000-000000000001'
      and on_behalf_of_participant_id = 'f4200000-0000-0000-0000-000000000043'
    from public.transfers where id = (select object_id from phase4_ids where label = 'behalf_t1')
  ),
  'server must persist settlement/base currency and Creator on-behalf audit identity'
);

-- Non-Creator cannot act on behalf, and an outsider cannot invoke a member write.
select pg_temp.authenticate('f4300000-0000-0000-0000-000000000002');
do $test$
begin
  begin
    perform * from public.create_settlement_transfer(
      'f4000000-0000-0000-0000-000000000004',
      'f4200000-0000-0000-0000-000000000043',
      'f4200000-0000-0000-0000-000000000044', 1, now(),
      'f4200000-0000-0000-0000-000000000043'
    );
    raise exception 'Member acted on behalf';
  exception when insufficient_privilege then null;
  end;
end;
$test$;

select pg_temp.authenticate('f4300000-0000-0000-0000-000000000003');
do $test$
begin
  begin
    perform * from public.create_settlement_transfer(
      'f4000000-0000-0000-0000-000000000001',
      'f4200000-0000-0000-0000-000000000012',
      'f4200000-0000-0000-0000-000000000011', 1, now(), null
    );
    raise exception 'outsider created Transfer';
  exception when insufficient_privilege then null;
  end;
end;
$test$;

-- Expense-only bilateral cancellation must happen before Transfer allocation.
select pg_temp.authenticate('f4300000-0000-0000-0000-000000000001');
with created as (
  select * from public.create_settlement_transfer(
    'f4000000-0000-0000-0000-000000000002',
    'f4200000-0000-0000-0000-000000000021',
    'f4200000-0000-0000-0000-000000000022', 80, now(), null
  )
) insert into phase4_ids select 'counter_t1', transfer_id from created;

select pg_temp.assert_true(
  (
    select count(*) = 1 and bool_and(e.id = (select object_id from phase4_ids where label = 'counter_e3') and ta.amount = 80)
    from public.transfer_allocations as ta
    join public.expense_debts as ed on ed.id = ta.expense_debt_id
    join public.expenses as e on e.id = ed.expense_id
    where ta.transfer_id = (select object_id from phase4_ids where label = 'counter_t1')
  )
  and not exists (select 1 from public.bilateral_debts where activity_id = 'f4000000-0000-0000-0000-000000000002'),
  'reverse ExpenseDebt must consume old same-direction debt before Transfer FIFO starts'
);

-- Historical reduction leaves only 10 allocated from the immutable 80 Transfer,
-- while the full Transfer produces the natural reverse bilateral debt 70.
select pg_temp.assert_true(base_amount = 30 and version = 2, 'historical Expense update succeeds')
from public.update_expense(
  (select object_id from phase4_ids where label = 'counter_e3'),
  'f4100000-0000-0000-0000-000000000002', 'New A to B reduced', 30, 'CNY', 1, 'manual',
  '[{"participant_id":"f4200000-0000-0000-0000-000000000022","amount":"30"}]',
  '[{"participant_id":"f4200000-0000-0000-0000-000000000021","amount":"30"}]',
  '{}', '2026-08-31 11:00:00+08', null, null
);

select pg_temp.assert_true(
  (select pg_catalog.sum(amount) = 10 from public.transfer_allocations where transfer_id = (select object_id from phase4_ids where label = 'counter_t1'))
  and exists (
    select 1 from public.bilateral_debts
    where activity_id = 'f4000000-0000-0000-0000-000000000002'
      and debtor_participant_id = 'f4200000-0000-0000-0000-000000000022'
      and creditor_participant_id = 'f4200000-0000-0000-0000-000000000021'
      and amount = 70
  )
  and (select financial_version = 5 from public.activities where id = 'f4000000-0000-0000-0000-000000000002'),
  'history update must rebuild allocation and expose overpayment as reverse bilateral debt'
);

select pg_temp.assert_true(deleted and version = 3, 'historical Expense delete succeeds')
from public.delete_expense((select object_id from phase4_ids where label = 'counter_e3'));

select pg_temp.assert_true(
  not exists (select 1 from public.transfer_allocations where transfer_id = (select object_id from phase4_ids where label = 'counter_t1'))
  and exists (
    select 1 from public.bilateral_debts
    where activity_id = 'f4000000-0000-0000-0000-000000000002'
      and debtor_participant_id = 'f4200000-0000-0000-0000-000000000022'
      and creditor_participant_id = 'f4200000-0000-0000-0000-000000000021'
      and amount = 100
  )
  and (select financial_version = 6 from public.activities where id = 'f4000000-0000-0000-0000-000000000002'),
  'history delete must rebuild allocations and bilateral debt exactly once'
);

-- Full repair equals incremental business columns and does not move version.
reset role;
create temporary table expected_expense_debts on commit drop as
select activity_id, expense_id, debtor_participant_id, creditor_participant_id, amount
from public.expense_debts where activity_id = 'f4000000-0000-0000-0000-000000000002';
create temporary table expected_allocations on commit drop as
select activity_id, transfer_id, expense_debt_id, amount
from public.transfer_allocations where activity_id = 'f4000000-0000-0000-0000-000000000002';
create temporary table expected_bilateral on commit drop as
select activity_id, debtor_participant_id, creditor_participant_id, amount
from public.bilateral_debts where activity_id = 'f4000000-0000-0000-0000-000000000002';
select private.rebuild_activity_debt_projection('f4000000-0000-0000-0000-000000000002');
select pg_temp.assert_true(
  not exists ((select activity_id, expense_id, debtor_participant_id, creditor_participant_id, amount from public.expense_debts where activity_id = 'f4000000-0000-0000-0000-000000000002') except table expected_expense_debts)
  and not exists ((table expected_expense_debts) except (select activity_id, expense_id, debtor_participant_id, creditor_participant_id, amount from public.expense_debts where activity_id = 'f4000000-0000-0000-0000-000000000002'))
  and not exists ((select activity_id, transfer_id, expense_debt_id, amount from public.transfer_allocations where activity_id = 'f4000000-0000-0000-0000-000000000002') except table expected_allocations)
  and not exists ((table expected_allocations) except (select activity_id, transfer_id, expense_debt_id, amount from public.transfer_allocations where activity_id = 'f4000000-0000-0000-0000-000000000002'))
  and not exists ((select activity_id, debtor_participant_id, creditor_participant_id, amount from public.bilateral_debts where activity_id = 'f4000000-0000-0000-0000-000000000002') except table expected_bilateral)
  and not exists ((table expected_bilateral) except (select activity_id, debtor_participant_id, creditor_participant_id, amount from public.bilateral_debts where activity_id = 'f4000000-0000-0000-0000-000000000002'))
  and (select financial_version = 6 from public.activities where id = 'f4000000-0000-0000-0000-000000000002'),
  'full repair must equal incremental business columns without incrementing version'
);

-- Archived Activities reject every Expense mutation and settlement write after
-- the Activity lock, with the complete fact transaction rolled back.
set local role authenticated;
select pg_temp.authenticate('f4300000-0000-0000-0000-000000000001');
update public.activities set archived_at = now() where id = 'f4000000-0000-0000-0000-000000000003';

do $test$
declare v_before bigint;
begin
  select financial_version into v_before from public.activities where id = 'f4000000-0000-0000-0000-000000000003';
  begin
    perform * from public.create_expense(
      'f4100000-0000-0000-0000-000000000003', 'Blocked create', 10, 'CNY', 1, 'manual',
      '[{"participant_id":"f4200000-0000-0000-0000-000000000031","amount":"10"}]',
      '[{"participant_id":"f4200000-0000-0000-0000-000000000032","amount":"10"}]',
      '{}', now(), null, null
    );
    raise exception 'archived create unexpectedly succeeded';
  exception when object_not_in_prerequisite_state then null;
  end;
  begin
    perform * from public.update_expense(
      (select object_id from phase4_ids where label = 'archived_e1'),
      'f4100000-0000-0000-0000-000000000003', 'Blocked update', 40, 'CNY', 1, 'manual',
      '[{"participant_id":"f4200000-0000-0000-0000-000000000031","amount":"40"}]',
      '[{"participant_id":"f4200000-0000-0000-0000-000000000032","amount":"40"}]',
      '{}', now(), null, null
    );
    raise exception 'archived update unexpectedly succeeded';
  exception when object_not_in_prerequisite_state then null;
  end;
  begin
    perform * from public.delete_expense((select object_id from phase4_ids where label = 'archived_e1'));
    raise exception 'archived delete unexpectedly succeeded';
  exception when object_not_in_prerequisite_state then null;
  end;
  begin
    perform * from public.create_settlement_transfer(
      'f4000000-0000-0000-0000-000000000003',
      'f4200000-0000-0000-0000-000000000032',
      'f4200000-0000-0000-0000-000000000031', 10, now(), null
    );
    raise exception 'archived settlement unexpectedly succeeded';
  exception when object_not_in_prerequisite_state then null;
  end;
  perform pg_temp.assert_true(
    (select financial_version = v_before from public.activities where id = 'f4000000-0000-0000-0000-000000000003')
    and (select title = 'Archived source' and not is_deleted and version = 1 from public.expenses where id = (select object_id from phase4_ids where label = 'archived_e1'))
    and not exists (select 1 from public.transfers where activity_id = 'f4000000-0000-0000-0000-000000000003'),
    'archived failures must roll back facts and leave financial_version unchanged'
  );
end;
$test$;

-- Archived also blocks voiding an existing settlement.
update public.activities set archived_at = now() where id = 'f4000000-0000-0000-0000-000000000004';
do $test$
declare v_before bigint;
begin
  select financial_version into v_before from public.activities where id = 'f4000000-0000-0000-0000-000000000004';
  begin
    perform * from public.void_settlement_transfer((select object_id from phase4_ids where label = 'behalf_t1'), 'archived');
    raise exception 'archived void unexpectedly succeeded';
  exception when object_not_in_prerequisite_state then null;
  end;
  perform pg_temp.assert_true(
    (select financial_version = v_before from public.activities where id = 'f4000000-0000-0000-0000-000000000004')
    and (select not is_voided from public.transfers where id = (select object_id from phase4_ids where label = 'behalf_t1')),
    'archived void must have no side effect'
  );
end;
$test$;

-- Creator still cannot directly mutate the protected concurrency token.
do $test$
begin
  begin
    update public.activities
    set financial_version = financial_version + 100
    where id = 'f4000000-0000-0000-0000-000000000003';
    raise exception 'direct financial_version update unexpectedly succeeded';
  exception when insufficient_privilege then null;
  end;
end;
$test$;

-- Members can read their rows but cannot directly mutate facts/projections.
do $test$
begin
  begin
    insert into public.transfers (
      activity_id, from_participant_id, to_participant_id, type, amount,
      currency, recorded_by
    ) values (
      'f4000000-0000-0000-0000-000000000001',
      'f4200000-0000-0000-0000-000000000012',
      'f4200000-0000-0000-0000-000000000011', 'settlement', 1, 'CNY',
      'f4300000-0000-0000-0000-000000000001'
    );
    raise exception 'direct Transfer insert unexpectedly succeeded';
  exception when insufficient_privilege then null;
  end;
  begin
    update public.transfers set amount = amount + 1;
    raise exception 'direct Transfer update unexpectedly succeeded';
  exception when insufficient_privilege then null;
  end;
  begin
    delete from public.transfer_allocations;
    raise exception 'direct TransferAllocation delete unexpectedly succeeded';
  exception when insufficient_privilege then null;
  end;
end;
$test$;

select pg_temp.assert_true(
  not has_table_privilege('anon', 'public.transfers', 'SELECT')
  and not has_table_privilege('anon', 'public.transfer_allocations', 'SELECT')
  and not has_table_privilege('authenticated', 'public.transfers', 'INSERT,UPDATE,DELETE')
  and not has_table_privilege('authenticated', 'public.transfer_allocations', 'INSERT,UPDATE,DELETE')
  and not has_column_privilege('authenticated', 'public.activities', 'financial_version', 'UPDATE')
  and not has_function_privilege('anon', 'public.create_settlement_transfer(uuid,uuid,uuid,numeric,timestamptz,uuid)', 'EXECUTE')
  and not has_function_privilege('anon', 'public.void_settlement_transfer(uuid,text)', 'EXECUTE'),
  'Data API grants must deny anon RPC/read and authenticated direct financial DML'
);

select pg_temp.assert_true(
  (
    select enum_range(null::public.transfer_type)::text[] =
      array['settlement', 'prepayment', 'prepayment_return', 'final_settlement']::text[]
  )
  and (
    select count(*) = 5
    from pg_constraint
    where conname in (
      'transfers_from_activity_fk',
      'transfers_to_activity_fk',
      'transfers_on_behalf_activity_fk',
      'transfer_allocations_transfer_activity_fk',
      'transfer_allocations_expense_debt_activity_fk'
    )
  ),
  'Transfer type vocabulary and composite Activity ownership FKs must be present'
);

select pg_temp.assert_true(
  (
    select count(*) = 9
      and bool_and(p.prosecdef)
      and bool_and(p.proconfig @> array['search_path=""']::text[])
    from pg_proc as p
    join pg_namespace as n on n.oid = p.pronamespace
    where n.nspname = 'private'
      and p.proname in (
        'rebuild_transfer_allocations_locked',
        'rebuild_bilateral_debts_locked',
        'rebuild_expense_and_bilateral_debts',
        'rebuild_activity_debt_projection',
        'create_expense_projected_impl',
        'update_expense_projected_impl',
        'delete_expense_projected_impl',
        'create_settlement_transfer_impl',
        'void_settlement_transfer_impl'
      )
  ),
  'all replaced/new private functions must remain SECURITY DEFINER with empty search_path'
);

-- RLS returns no Transfer data to an authenticated outsider.
select pg_temp.authenticate('f4300000-0000-0000-0000-000000000003');
select pg_temp.assert_true(
  (select count(*) = 0 from public.transfers)
  and (select count(*) = 0 from public.transfer_allocations),
  'authenticated outsider must not read Transfer facts or allocations'
);

rollback;
