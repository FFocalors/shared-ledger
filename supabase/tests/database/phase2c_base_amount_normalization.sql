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
    'f3000000-0000-0000-0000-000000000001',
    'authenticated',
    'authenticated',
    'phase2c.member@example.invalid',
    crypt('phase2c-password', gen_salt('bf')),
    now(),
    '{}',
    '{"display_name":"Phase 2C Member"}',
    now(),
    now()
  ),
  (
    '00000000-0000-0000-0000-000000000000',
    'f3000000-0000-0000-0000-000000000002',
    'authenticated',
    'authenticated',
    'phase2c.outsider@example.invalid',
    crypt('phase2c-password', gen_salt('bf')),
    now(),
    '{}',
    '{"display_name":"Phase 2C Outsider"}',
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
values (
  'f0000000-0000-0000-0000-000000000001',
  '92000001',
  'Phase 2C fixture',
  'normal',
  'CNY',
  true,
  'f3000000-0000-0000-0000-000000000001'
);

insert into public.activity_members (activity_id, user_id)
values (
  'f0000000-0000-0000-0000-000000000001',
  'f3000000-0000-0000-0000-000000000001'
);

insert into public.ledger_units (id, activity_id, name, type)
values (
  'f1000000-0000-0000-0000-000000000001',
  'f0000000-0000-0000-0000-000000000001',
  'Phase 2C ledger',
  'default'
);

insert into public.participants (id, activity_id, name, participant_order)
values
  (
    'f2000000-0000-0000-0000-000000000001',
    'f0000000-0000-0000-0000-000000000001',
    'First',
    0
  ),
  (
    'f2000000-0000-0000-0000-000000000002',
    'f0000000-0000-0000-0000-000000000001',
    'Second',
    1
  ),
  (
    'f2000000-0000-0000-0000-000000000003',
    'f0000000-0000-0000-0000-000000000001',
    'Third',
    2
  );

set local role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"f3000000-0000-0000-0000-000000000001","role":"authenticated"}',
  true
);

create temporary table phase2c_expense_ids (
  label text primary key,
  expense_id uuid not null
) on commit drop;

-- Base-currency AA: original-currency allocation remains at four decimals,
-- while the base allocation uses 0.1 units and puts the tail on the last row.
with created as (
  select *
  from public.create_expense(
    'f1000000-0000-0000-0000-000000000001',
    'Base AA 100 / 3',
    100.0000,
    'CNY',
    1,
    'aa',
    '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"100.0000"}]'::jsonb,
    '[]'::jsonb,
    array[
      'f2000000-0000-0000-0000-000000000003'::uuid,
      'f2000000-0000-0000-0000-000000000001'::uuid,
      'f2000000-0000-0000-0000-000000000002'::uuid
    ],
    '2026-08-30 10:00:00+08',
    null,
    null
  )
)
insert into phase2c_expense_ids (label, expense_id)
select 'base_aa', expense_id from created;

-- Foreign-currency payments and manual splits deliberately create rounding
-- tails. Input JSON order differs from participant_order.
with created as (
  select *
  from public.create_expense(
    'f1000000-0000-0000-0000-000000000001',
    'Foreign manual tails',
    10.0000,
    'USD',
    7.25,
    'manual',
    '[
      {"participant_id":"f2000000-0000-0000-0000-000000000003","amount":"3.3334"},
      {"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"3.3333"},
      {"participant_id":"f2000000-0000-0000-0000-000000000002","amount":"3.3333"}
    ]'::jsonb,
    '[
      {"participant_id":"f2000000-0000-0000-0000-000000000003","amount":"8.0000"},
      {"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"1.0000"},
      {"participant_id":"f2000000-0000-0000-0000-000000000002","amount":"1.0000"}
    ]'::jsonb,
    '{}'::uuid[],
    '2026-08-30 10:05:00+08',
    null,
    null
  )
)
insert into phase2c_expense_ids (label, expense_id)
select 'foreign_manual', expense_id from created;

-- A positive expense is the protected original for a negative refund.
with created as (
  select *
  from public.create_expense(
    'f1000000-0000-0000-0000-000000000001',
    'Refund original',
    10.0000,
    'USD',
    7.25,
    'aa',
    '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"10.0000"}]'::jsonb,
    '[]'::jsonb,
    array[
      'f2000000-0000-0000-0000-000000000001'::uuid,
      'f2000000-0000-0000-0000-000000000002'::uuid,
      'f2000000-0000-0000-0000-000000000003'::uuid
    ],
    '2026-08-30 10:10:00+08',
    null,
    null
  )
)
insert into phase2c_expense_ids (label, expense_id)
select 'refund_original', expense_id from created;

with created as (
  select *
  from public.create_expense(
    'f1000000-0000-0000-0000-000000000001',
    'Negative refund',
    -10.0000,
    'USD',
    7.25,
    'aa',
    '[
      {"participant_id":"f2000000-0000-0000-0000-000000000003","amount":"-3.3334"},
      {"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"-3.3333"},
      {"participant_id":"f2000000-0000-0000-0000-000000000002","amount":"-3.3333"}
    ]'::jsonb,
    '[]'::jsonb,
    array[
      'f2000000-0000-0000-0000-000000000003'::uuid,
      'f2000000-0000-0000-0000-000000000001'::uuid,
      'f2000000-0000-0000-0000-000000000002'::uuid
    ],
    '2026-08-30 10:15:00+08',
    null,
    (select expense_id from phase2c_expense_ids where label = 'refund_original')
  )
)
insert into phase2c_expense_ids (label, expense_id)
select 'negative_refund', expense_id from created;

-- Base-normalized child values may legitimately round to zero even though the
-- original-currency amount remains non-zero.
with created as (
  select *
  from public.create_expense(
    'f1000000-0000-0000-0000-000000000001',
    'Zero normalized children',
    0.0100,
    'USD',
    0.10,
    'manual',
    '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"0.0100"}]'::jsonb,
    '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"0.0100"}]'::jsonb,
    '{}'::uuid[],
    '2026-08-30 10:17:00+08',
    null,
    null
  )
)
insert into phase2c_expense_ids (label, expense_id)
select 'zero_base', expense_id from created;

select pg_temp.assert_true(
  (
    select e.base_amount = 100.0
    from public.expenses as e
    join phase2c_expense_ids as t on t.expense_id = e.id
    where t.label = 'base_aa'
  ),
  'base-currency expense base amount must equal original amount'
);

select pg_temp.assert_true(
  (
    select array_agg(s.amount order by p.participant_order, p.id)
           = array[33.3334, 33.3333, 33.3333]::numeric[]
    from public.splits as s
    join public.participants as p on p.id = s.participant_id
    join phase2c_expense_ids as t on t.expense_id = s.expense_id
    where t.label = 'base_aa'
  ),
  'AA original amounts must preserve the four-decimal allocation algorithm'
);

select pg_temp.assert_true(
  (
    select array_agg(s.base_amount order by p.participant_order, p.id)
           = array[33.3, 33.3, 33.4]::numeric[]
    from public.splits as s
    join public.participants as p on p.id = s.participant_id
    join phase2c_expense_ids as t on t.expense_id = s.expense_id
    where t.label = 'base_aa'
  ),
  'AA base amounts must allocate 100 / 3 as 33.3, 33.3, 33.4'
);

select pg_temp.assert_true(
  (
    select array_agg(pay.base_amount order by p.participant_order, p.id)
           = array[24.2, 24.2, 24.1]::numeric[]
    from public.payments as pay
    join public.participants as p on p.id = pay.participant_id
    join phase2c_expense_ids as t on t.expense_id = pay.expense_id
    where t.label = 'foreign_manual'
  ),
  'payment rounding tail must be assigned to the last deterministic participant'
);

select pg_temp.assert_true(
  (
    select array_agg(s.base_amount order by p.participant_order, p.id)
           = array[7.3, 7.3, 57.9]::numeric[]
    from public.splits as s
    join public.participants as p on p.id = s.participant_id
    join phase2c_expense_ids as t on t.expense_id = s.expense_id
    where t.label = 'foreign_manual'
  ),
  'manual split rounding tail must be assigned to the last deterministic participant'
);

select pg_temp.assert_true(
  (
    select array_agg(s.base_amount order by p.participant_order, p.id)
           = array[-24.1, -24.1, -24.3]::numeric[]
    from public.splits as s
    join public.participants as p on p.id = s.participant_id
    join phase2c_expense_ids as t on t.expense_id = s.expense_id
    where t.label = 'negative_refund'
  ),
  'negative AA base amounts must conserve sign and put the tail last'
);

select pg_temp.assert_true(
  (
    select array_agg(pay.base_amount order by p.participant_order, p.id)
           = array[-24.2, -24.2, -24.1]::numeric[]
    from public.payments as pay
    join public.participants as p on p.id = pay.participant_id
    join phase2c_expense_ids as t on t.expense_id = pay.expense_id
    where t.label = 'negative_refund'
  ),
  'negative payment rounding must conserve the expense base amount'
);

select pg_temp.assert_true(
  (
    select e.base_amount = 0.0
           and pay.base_amount = 0.0
           and s.base_amount = 0.0
    from public.expenses as e
    join public.payments as pay on pay.expense_id = e.id
    join public.splits as s on s.expense_id = e.id
    join phase2c_expense_ids as t on t.expense_id = e.id
    where t.label = 'zero_base'
  ),
  'non-zero original values must permit normalized child base amounts of zero'
);

select pg_temp.assert_true(
  not exists (
    select 1
    from public.expenses as e
    where (
      select sum(pay.base_amount)
      from public.payments as pay
      where pay.expense_id = e.id
    ) is distinct from e.base_amount
       or (
         select sum(s.base_amount)
         from public.splits as s
         where s.expense_id = e.id
       ) is distinct from e.base_amount
  ),
  'every payment and split base total must strictly equal its expense base amount'
);

-- Update replaces children, recalculates both kinds of base amount, and bumps
-- the server-owned LWW version.
with updated as (
  select *
  from public.update_expense(
    (select expense_id from phase2c_expense_ids where label = 'foreign_manual'),
    'f1000000-0000-0000-0000-000000000001',
    'Foreign manual tails updated',
    12.0000,
    'USD',
    7.27,
    'manual',
    '[
      {"participant_id":"f2000000-0000-0000-0000-000000000003","amount":"4.0000"},
      {"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"4.0000"},
      {"participant_id":"f2000000-0000-0000-0000-000000000002","amount":"4.0000"}
    ]'::jsonb,
    '[
      {"participant_id":"f2000000-0000-0000-0000-000000000003","amount":"8.0000"},
      {"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"2.0000"},
      {"participant_id":"f2000000-0000-0000-0000-000000000002","amount":"2.0000"}
    ]'::jsonb,
    '{}'::uuid[],
    '2026-08-30 10:20:00+08',
    'updated',
    null
  )
)
select pg_temp.assert_true(
  base_amount = 87.2 and version = 2,
  'update must return recalculated base amount and incremented version'
)
from updated;

select pg_temp.assert_true(
  (
    select array_agg(pay.base_amount order by p.participant_order, p.id)
           = array[29.1, 29.1, 29.0]::numeric[]
    from public.payments as pay
    join public.participants as p on p.id = pay.participant_id
    join phase2c_expense_ids as t on t.expense_id = pay.expense_id
    where t.label = 'foreign_manual'
  ),
  'updated payment base amounts must be recomputed with the final tail last'
);

select pg_temp.assert_true(
  (
    select array_agg(s.base_amount order by p.participant_order, p.id)
           = array[14.5, 14.5, 58.2]::numeric[]
    from public.splits as s
    join public.participants as p on p.id = s.participant_id
    join phase2c_expense_ids as t on t.expense_id = s.expense_id
    where t.label = 'foreign_manual'
  ),
  'updated manual split base amounts must be recomputed and conserved'
);

-- Phase 2B payload validation remains authoritative, and Phase 2C does not
-- allow clients to smuggle a precomputed normalized amount into child JSON.
do $test$
begin
  begin
    perform public.create_expense(
      'f1000000-0000-0000-0000-000000000001',
      'Client supplied base amount',
      1.0000,
      'CNY',
      1,
      'manual',
      '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"1.0000","base_amount":"999.0"}]'::jsonb,
      '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"1.0000"}]'::jsonb,
      '{}'::uuid[],
      now(),
      null,
      null
    );
    raise exception 'client-supplied child base amount unexpectedly succeeded';
  exception
    when sqlstate '22023' then null;
  end;

  begin
    perform public.create_expense(
      'f1000000-0000-0000-0000-000000000001',
      'Payment total mismatch',
      2.0000,
      'CNY',
      1,
      'manual',
      '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"1.0000"}]'::jsonb,
      '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"2.0000"}]'::jsonb,
      '{}'::uuid[],
      now(),
      null,
      null
    );
    raise exception 'mismatched payment total unexpectedly succeeded';
  exception
    when sqlstate '22023' then null;
  end;

  begin
    perform public.create_expense(
      'f1000000-0000-0000-0000-000000000001',
      'Invalid base currency FX',
      1.0000,
      'CNY',
      2,
      'manual',
      '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"1.0000"}]'::jsonb,
      '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"1.0000"}]'::jsonb,
      '{}'::uuid[],
      now(),
      null,
      null
    );
    raise exception 'base-currency expense with FX rate other than 1 unexpectedly succeeded';
  exception
    when sqlstate '22023' then null;
  end;
end;
$test$;

-- Phase 2B regression: direct writes remain unavailable to API roles.
do $test$
begin
  begin
    insert into public.payments (expense_id, participant_id, amount, base_amount)
    values (
      (select expense_id from phase2c_expense_ids where label = 'base_aa'),
      'f2000000-0000-0000-0000-000000000002',
      1,
      1
    );
    raise exception 'direct payment insert unexpectedly succeeded';
  exception
    when insufficient_privilege then null;
  end;
end;
$test$;

-- Phase 2B regression: an authenticated non-member cannot see or create data.
select set_config(
  'request.jwt.claims',
  '{"sub":"f3000000-0000-0000-0000-000000000002","role":"authenticated"}',
  true
);

select pg_temp.assert_true(
  (select count(*) = 0 from public.expenses),
  'expense RLS must hide rows from authenticated non-members'
);

do $test$
begin
  begin
    perform public.create_expense(
      'f1000000-0000-0000-0000-000000000001',
      'Outsider write',
      1.0000,
      'CNY',
      1,
      'manual',
      '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"1.0000"}]'::jsonb,
      '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"1.0000"}]'::jsonb,
      '{}'::uuid[],
      now(),
      null,
      null
    );
    raise exception 'non-member expense creation unexpectedly succeeded';
  exception
    when sqlstate '42501' then null;
  end;
end;
$test$;

-- The private definer boundary performs its own auth check even for a role
-- that has EXECUTE, rather than trusting the database role alone.
select set_config('request.jwt.claims', '{"role":"authenticated"}', true);

do $test$
begin
  begin
    perform public.create_expense(
      'f1000000-0000-0000-0000-000000000001',
      'Missing auth uid',
      1.0000,
      'CNY',
      1,
      'manual',
      '[]'::jsonb,
      '[]'::jsonb,
      '{}'::uuid[],
      now(),
      null,
      null
    );
    raise exception 'missing auth uid unexpectedly succeeded';
  exception
    when sqlstate '28000' then null;
  end;
end;
$test$;

select set_config(
  'request.jwt.claims',
  '{"sub":"f3000000-0000-0000-0000-000000000001","role":"authenticated"}',
  true
);

-- Refund deletion protection, row-lock-backed delete flow, idempotence, and
-- server-owned version behavior remain intact.
do $test$
begin
  begin
    perform public.delete_expense(
      (select expense_id from phase2c_expense_ids where label = 'refund_original')
    );
    raise exception 'referenced original expense deletion unexpectedly succeeded';
  exception
    when sqlstate '23514' then null;
  end;
end;
$test$;

select pg_temp.assert_true(deleted and version = 2, 'refund delete must bump version')
from public.delete_expense(
  (select expense_id from phase2c_expense_ids where label = 'negative_refund')
);

select pg_temp.assert_true(deleted and version = 2, 'original delete must succeed after refund deletion')
from public.delete_expense(
  (select expense_id from phase2c_expense_ids where label = 'refund_original')
);

select pg_temp.assert_true(not deleted and version = 2, 'repeat delete must be idempotent')
from public.delete_expense(
  (select expense_id from phase2c_expense_ids where label = 'refund_original')
);

do $test$
begin
  begin
    perform public.update_expense(
      (select expense_id from phase2c_expense_ids where label = 'refund_original'),
      'f1000000-0000-0000-0000-000000000001',
      'Deleted update',
      10.0000,
      'USD',
      7.25,
      'aa',
      '[{"participant_id":"f2000000-0000-0000-0000-000000000001","amount":"10.0000"}]'::jsonb,
      '[]'::jsonb,
      array['f2000000-0000-0000-0000-000000000001'::uuid],
      now(),
      null,
      null
    );
    raise exception 'deleted expense update unexpectedly succeeded';
  exception
    when sqlstate '22023' then null;
  end;
end;
$test$;

reset role;

select pg_temp.assert_true(
  not has_table_privilege('authenticated', 'public.payments', 'INSERT')
  and not has_table_privilege('authenticated', 'public.splits', 'INSERT')
  and not has_table_privilege('authenticated', 'public.expenses', 'UPDATE'),
  'direct expense child writes and expense updates must remain revoked'
);

select pg_temp.assert_true(
  (
    select pg_catalog.format_type(a.atttypid, a.atttypmod) = 'numeric(20,1)'
           and a.attnotnull
    from pg_attribute as a
    where a.attrelid = 'public.payments'::regclass
      and a.attname = 'base_amount'
      and not a.attisdropped
  )
  and (
    select pg_catalog.format_type(a.atttypid, a.atttypmod) = 'numeric(20,1)'
           and a.attnotnull
    from pg_attribute as a
    where a.attrelid = 'public.splits'::regclass
      and a.attname = 'base_amount'
      and not a.attisdropped
  ),
  'payment and split base_amount columns must be numeric(20,1) and NOT NULL'
);

select pg_temp.assert_true(
  not has_function_privilege(
    'anon',
    'public.create_expense(uuid,text,numeric,character,numeric,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)',
    'EXECUTE'
  ),
  'anon must not gain create_expense execute permission'
);

select pg_temp.assert_true(
  (
    select not public_rpc.prosecdef
           and private_impl.prosecdef
           and public_rpc.proconfig @> array['search_path=""']::text[]
           and private_impl.proconfig @> array['search_path=""']::text[]
    from pg_proc as public_rpc
    join pg_namespace as public_ns on public_ns.oid = public_rpc.pronamespace
    cross join pg_proc as private_impl
    join pg_namespace as private_ns on private_ns.oid = private_impl.pronamespace
    where public_ns.nspname = 'public'
      and public_rpc.proname = 'create_expense'
      and private_ns.nspname = 'private'
      and private_impl.proname = 'replace_expense_children'
  ),
  'public invoker and private definer boundaries must retain empty search_path'
);

rollback;
