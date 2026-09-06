\set ON_ERROR_STOP on

begin;
create extension if not exists pgtap with schema extensions;
select extensions.plan(16);

create function pg_temp.authenticate(p_user uuid) returns void
language plpgsql as $function$
begin
  perform set_config(
    'request.jwt.claims',
    json_build_object('sub', p_user, 'role', 'authenticated')::text,
    true
  );
end;
$function$;

set local role postgres;
insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password,
  email_confirmed_at, raw_app_meta_data, raw_user_meta_data, created_at, updated_at
)
values
  (
    '00000000-0000-0000-0000-000000000000',
    'f3000000-0000-0000-0000-000000000001',
    'authenticated', 'authenticated', 'phase3.member@example.invalid',
    crypt('phase3-password', gen_salt('bf')), now(), '{}', '{}', now(), now()
  ),
  (
    '00000000-0000-0000-0000-000000000000',
    'f3000000-0000-0000-0000-000000000002',
    'authenticated', 'authenticated', 'phase3.outsider@example.invalid',
    crypt('phase3-password', gen_salt('bf')), now(), '{}', '{}', now(), now()
  );

insert into public.activities (id, join_code, name, type, base_currency, created_by)
values (
  'f3000000-0000-0000-0000-000000000101',
  '93000001', 'Phase 3 deleted read', 'normal', 'CNY',
  'f3000000-0000-0000-0000-000000000001'
);

insert into public.activity_members (activity_id, user_id)
values (
  'f3000000-0000-0000-0000-000000000101',
  'f3000000-0000-0000-0000-000000000001'
);

insert into public.ledger_units (id, activity_id, name, type)
values (
  'f3000000-0000-0000-0000-000000000201',
  'f3000000-0000-0000-0000-000000000101',
  'Phase 3 ledger', 'default'
);

insert into public.participants (id, activity_id, name, participant_order)
values
  (
    'f3000000-0000-0000-0000-000000000301',
    'f3000000-0000-0000-0000-000000000101', 'Member', 0
  ),
  (
    'f3000000-0000-0000-0000-000000000302',
    'f3000000-0000-0000-0000-000000000101', 'Other', 1
  );

insert into public.expenses (
  id, ledger_unit_id, title, original_amount, original_currency, fx_rate,
  base_amount, split_method, occurred_at, created_by, updated_by,
  version, is_deleted, deleted_at, deleted_by
)
values
  (
    'f3000000-0000-0000-0000-000000000401',
    'f3000000-0000-0000-0000-000000000201',
    'Active expense', 10, 'CNY', 1, 10, 'manual', now(),
    'f3000000-0000-0000-0000-000000000001',
    'f3000000-0000-0000-0000-000000000001', 1, false, null, null
  ),
  (
    'f3000000-0000-0000-0000-000000000402',
    'f3000000-0000-0000-0000-000000000201',
    'Deleted expense', 20, 'CNY', 1, 20, 'manual', now(),
    'f3000000-0000-0000-0000-000000000001',
    'f3000000-0000-0000-0000-000000000001', 2, true, now(),
    'f3000000-0000-0000-0000-000000000001'
  );

insert into public.payments (id, expense_id, participant_id, amount, base_amount)
values
  (
    'f3000000-0000-0000-0000-000000000501',
    'f3000000-0000-0000-0000-000000000401',
    'f3000000-0000-0000-0000-000000000301', 10, 10
  ),
  (
    'f3000000-0000-0000-0000-000000000502',
    'f3000000-0000-0000-0000-000000000402',
    'f3000000-0000-0000-0000-000000000301', 20, 20
  );

insert into public.splits (id, expense_id, participant_id, amount, base_amount)
values
  (
    'f3000000-0000-0000-0000-000000000601',
    'f3000000-0000-0000-0000-000000000401',
    'f3000000-0000-0000-0000-000000000302', 10, 10
  ),
  (
    'f3000000-0000-0000-0000-000000000602',
    'f3000000-0000-0000-0000-000000000402',
    'f3000000-0000-0000-0000-000000000302', 20, 20
  );

set local role authenticated;
select pg_temp.authenticate('f3000000-0000-0000-0000-000000000001');

select ok(
  (select count(*) = 1 from public.expenses where id = 'f3000000-0000-0000-0000-000000000401'),
  'Activity member can read an active Expense'
);
select ok(
  (select count(*) = 1 and bool_and(is_deleted) from public.expenses where id = 'f3000000-0000-0000-0000-000000000402'),
  'Activity member can read a deleted Expense'
);
select ok(
  (select count(*) = 1 from public.payments where expense_id = 'f3000000-0000-0000-0000-000000000401'),
  'Activity member can read payments for an active Expense'
);
select ok(
  (select count(*) = 1 from public.payments where expense_id = 'f3000000-0000-0000-0000-000000000402'),
  'Activity member can read payments for a deleted Expense'
);
select ok(
  (select count(*) = 1 from public.splits where expense_id = 'f3000000-0000-0000-0000-000000000401'),
  'Activity member can read splits for an active Expense'
);
select ok(
  (select count(*) = 1 from public.splits where expense_id = 'f3000000-0000-0000-0000-000000000402'),
  'Activity member can read splits for a deleted Expense'
);

select pg_temp.authenticate('f3000000-0000-0000-0000-000000000002');
select ok(
  (select count(*) = 0 from public.expenses where id in (
    'f3000000-0000-0000-0000-000000000401',
    'f3000000-0000-0000-0000-000000000402'
  )),
  'Non-member cannot read active or deleted Expenses'
);
select ok(
  (select count(*) = 0 from public.payments where expense_id in (
    'f3000000-0000-0000-0000-000000000401',
    'f3000000-0000-0000-0000-000000000402'
  )),
  'Non-member cannot read Expense payments'
);
select ok(
  (select count(*) = 0 from public.splits where expense_id in (
    'f3000000-0000-0000-0000-000000000401',
    'f3000000-0000-0000-0000-000000000402'
  )),
  'Non-member cannot read Expense splits'
);

select ok(
  has_function_privilege('authenticated', 'private.can_read_expense(uuid)', 'EXECUTE')
    and not has_function_privilege('anon', 'private.can_read_expense(uuid)', 'EXECUTE'),
  'can_read_expense remains private to authenticated RLS evaluation'
);
select ok(
  (select p.prosecdef and p.proconfig @> array['search_path=""']::text[]
   from pg_proc as p
   join pg_namespace as n on n.oid = p.pronamespace
   where n.nspname = 'private' and p.proname = 'can_read_expense'
     and pg_catalog.pg_get_function_identity_arguments(p.oid) = 'p_expense_id uuid'),
  'can_read_expense remains SECURITY DEFINER with an empty search_path'
);
select ok(
  (select pg_catalog.strpos(pg_catalog.lower(pg_catalog.pg_get_functiondef(p.oid)), 'not lu.is_deleted') > 0
      and pg_catalog.strpos(pg_catalog.lower(pg_catalog.pg_get_functiondef(p.oid)), 'not a.is_deleted') > 0
   from pg_proc as p
   join pg_namespace as n on n.oid = p.pronamespace
   where n.nspname = 'private' and p.proname = 'can_read_expense'
     and pg_catalog.pg_get_function_identity_arguments(p.oid) = 'p_expense_id uuid'),
  'can_read_expense retains non-deleted Activity and LedgerUnit boundaries'
);
select ok(
  (select pg_catalog.strpos(pg_catalog.lower(pg_catalog.pg_get_functiondef(p.oid)), 'auth.uid') > 0
      and pg_catalog.strpos(pg_catalog.lower(pg_catalog.pg_get_functiondef(p.oid)), 'activity_members') > 0
   from pg_proc as p
   join pg_namespace as n on n.oid = p.pronamespace
   where n.nspname = 'private' and p.proname = 'can_read_expense'
     and pg_catalog.pg_get_function_identity_arguments(p.oid) = 'p_expense_id uuid'),
  'can_read_expense retains authenticated identity and membership checks'
);

select pg_temp.authenticate('f3000000-0000-0000-0000-000000000001');
select ok(
  (select restored from public.restore_expense('f3000000-0000-0000-0000-000000000402')),
  'Deleted Expense remains restorable through the public restore RPC'
);
select ok(
  has_function_privilege('authenticated', 'public.restore_expense(uuid)', 'EXECUTE')
    and not has_function_privilege('anon', 'public.restore_expense(uuid)', 'EXECUTE'),
  'restore_expense remains exposed only to authenticated callers'
);
select ok(
  (select not p.prosecdef and p.proconfig @> array['search_path=""']::text[]
   from pg_proc as p
   join pg_namespace as n on n.oid = p.pronamespace
   where n.nspname = 'public' and p.proname = 'restore_expense'
     and pg_catalog.pg_get_function_identity_arguments(p.oid) = 'expense_id uuid'),
  'restore_expense remains a SECURITY INVOKER wrapper with an empty search_path'
);

select * from extensions.finish();
rollback;
