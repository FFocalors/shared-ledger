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

create function pg_temp.authenticate(p_user_id uuid)
returns void
language plpgsql
as $function$
begin
  perform set_config(
    'request.jwt.claims',
    jsonb_build_object('sub', p_user_id, 'role', 'authenticated')::text,
    true
  );
end;
$function$;

create function pg_temp.add_ordering_expense(
  p_ledger_unit_id uuid,
  p_title text,
  p_payer_participant_id uuid,
  p_debtor_participant_id uuid,
  p_amount numeric,
  p_original_expense_id uuid default null,
  p_occurred_at timestamptz default now()
)
returns uuid
language plpgsql
as $function$
declare
  v_expense_id uuid;
begin
  select created.expense_id into v_expense_id
  from pg_temp.create_expense_fixture(
    p_ledger_unit_id,
    p_title,
    p_amount,
    'CNY',
    1,
    'manual',
    jsonb_build_array(jsonb_build_object('participant_id', p_payer_participant_id, 'amount', p_amount::text)),
    jsonb_build_array(jsonb_build_object('participant_id', p_debtor_participant_id, 'amount', p_amount::text)),
    '{}'::uuid[],
    p_occurred_at,
    null,
    p_original_expense_id
  ) as created;
  return v_expense_id;
end;
$function$;

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at
)
values
  ('00000000-0000-0000-0000-000000000000','c2100000-0000-0000-0000-000000000001','authenticated','authenticated','ordering.a@example.invalid',crypt('test',gen_salt('bf')),now(),'{}','{}',now(),now()),
  ('00000000-0000-0000-0000-000000000000','c2100000-0000-0000-0000-000000000002','authenticated','authenticated','ordering.b@example.invalid',crypt('test',gen_salt('bf')),now(),'{}','{}',now(),now());

create temporary table ordering_activities (
  activity_id uuid primary key,
  join_code text not null,
  ledger_unit_id uuid not null,
  debtor_id uuid not null,
  creditor_id uuid not null
) on commit drop;

insert into ordering_activities values
  ('c2000000-0000-0000-0000-000000000101','96100101','c2300000-0000-0000-0000-000000000101','c2200000-0000-0000-0000-000000000101','c2200000-0000-0000-0000-000000000102'),
  ('c2000000-0000-0000-0000-000000000102','96100102','c2300000-0000-0000-0000-000000000102','c2200000-0000-0000-0000-000000000201','c2200000-0000-0000-0000-000000000202'),
  ('c2000000-0000-0000-0000-000000000103','96100103','c2300000-0000-0000-0000-000000000103','c2200000-0000-0000-0000-000000000301','c2200000-0000-0000-0000-000000000302'),
  ('c2000000-0000-0000-0000-000000000104','96100104','c2300000-0000-0000-0000-000000000104','c2200000-0000-0000-0000-000000000401','c2200000-0000-0000-0000-000000000402'),
  ('c2000000-0000-0000-0000-000000000105','96100105','c2300000-0000-0000-0000-000000000105','c2200000-0000-0000-0000-000000000501','c2200000-0000-0000-0000-000000000502'),
  ('c2000000-0000-0000-0000-000000000106','96100106','c2300000-0000-0000-0000-000000000106','c2200000-0000-0000-0000-000000000601','c2200000-0000-0000-0000-000000000602'),
  ('c2000000-0000-0000-0000-000000000107','96100107','c2300000-0000-0000-0000-000000000107','c2200000-0000-0000-0000-000000000701','c2200000-0000-0000-0000-000000000702'),
  ('c2000000-0000-0000-0000-000000000108','96100108','c2300000-0000-0000-0000-000000000108','c2200000-0000-0000-0000-000000000801','c2200000-0000-0000-0000-000000000802');

insert into public.activities(id,join_code,name,type,base_currency,multi_currency_enabled,created_by)
select activity_id,join_code,'Financial ordering regression','normal','CNY',true,'c2100000-0000-0000-0000-000000000001'
from ordering_activities;

insert into public.activity_members(activity_id,user_id)
select f.activity_id,u.user_id
from ordering_activities as f
cross join (values
  ('c2100000-0000-0000-0000-000000000001'::uuid),
  ('c2100000-0000-0000-0000-000000000002'::uuid)
) as u(user_id);

insert into public.ledger_units(id,activity_id,name,type)
select ledger_unit_id,activity_id,'default','default' from ordering_activities;

insert into public.participants(id,activity_id,name,participant_order)
select debtor_id,activity_id,'Debtor',0 from ordering_activities
union all
select creditor_id,activity_id,'Creditor',1 from ordering_activities;

insert into public.participant_claims(activity_id,participant_id,user_id)
select activity_id,debtor_id,'c2100000-0000-0000-0000-000000000001'::uuid from ordering_activities
union all
select activity_id,creditor_id,'c2100000-0000-0000-0000-000000000002'::uuid from ordering_activities;

-- v2 prepayment balances can use supported foreign currencies when the
-- Activity enables them. Seed the same supported-code snapshot as the FX tests.
set local role service_role;
select * from public.replace_exchange_rate_cache(
  '2026-09-12',
  '{"EUR":"1","USD":"1.25","CNY":"7.10","JPY":"170.00","GBP":"0.86"}'::jsonb
);
reset role;

create temporary table ordering_ids(label text primary key, object_id uuid not null) on commit drop;
grant select, insert on ordering_activities, ordering_ids to authenticated;

set local role authenticated;
select pg_temp.authenticate('c2100000-0000-0000-0000-000000000001');

-- C02: a completed real settlement is not erased by a later linked refund.
insert into ordering_ids
select 'full_original', pg_temp.add_ordering_expense(ledger_unit_id,'full then refund',creditor_id,debtor_id,100)
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000101';

do $full_settlement$
declare v_version bigint; v_activity uuid := 'c2000000-0000-0000-0000-000000000101'; v_debtor uuid; v_creditor uuid; v_expense uuid;
begin
  select financial_version into v_version from public.activities where id=v_activity;
  select debtor_id,creditor_id into v_debtor,v_creditor from ordering_activities where activity_id=v_activity;
  select object_id into v_expense from ordering_ids where label='full_original';
  perform * from public.create_expense_repayment_v2(v_activity,v_debtor,v_creditor,100,'CNY','TARGETED',array[v_expense],now(),null,v_version,'c2400000-0000-0000-0000-000000000101');
end;
$full_settlement$;

insert into ordering_ids
select 'full_refund', pg_temp.add_ordering_expense(ledger_unit_id,'full refund',creditor_id,debtor_id,-100,(select object_id from ordering_ids where label='full_original'))
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000101';

select pg_temp.assert_true(
  (select count(*)=1 and sum(amount)=100
   from public.bilateral_debts
   where activity_id='c2000000-0000-0000-0000-000000000101'
     and debtor_participant_id='c2200000-0000-0000-0000-000000000102'
     and creditor_participant_id='c2200000-0000-0000-0000-000000000101'),
  'full settlement followed by a linked refund creates the reverse debt'
);

-- C02: multiple real settlements remain in the refund projection, and
-- multiple linked refunds may reach but not exceed the original amount.
insert into ordering_ids
select 'partial_original', pg_temp.add_ordering_expense(ledger_unit_id,'partial then refunds',creditor_id,debtor_id,100)
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000102';

do $partial_settlements$
declare v_version bigint; v_activity uuid := 'c2000000-0000-0000-0000-000000000102'; v_debtor uuid; v_creditor uuid; v_expense uuid;
begin
  select financial_version into v_version from public.activities where id=v_activity;
  select debtor_id,creditor_id into v_debtor,v_creditor from ordering_activities where activity_id=v_activity;
  select object_id into v_expense from ordering_ids where label='partial_original';
  perform * from public.create_expense_repayment_v2(v_activity,v_debtor,v_creditor,40,'CNY','TARGETED',array[v_expense],now(),null,v_version,'c2400000-0000-0000-0000-000000000102');
  select financial_version into v_version from public.activities where id=v_activity;
  perform * from public.create_expense_repayment_v2(v_activity,v_debtor,v_creditor,20,'CNY','TARGETED',array[v_expense],now(),null,v_version,'c2400000-0000-0000-0000-000000000103');
end;
$partial_settlements$;

insert into ordering_ids
select 'partial_refund_60', pg_temp.add_ordering_expense(ledger_unit_id,'refund 60',creditor_id,debtor_id,-60,(select object_id from ordering_ids where label='partial_original'),now()+interval '1 second')
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000102';
insert into ordering_ids
select 'partial_refund_40', pg_temp.add_ordering_expense(ledger_unit_id,'refund 40',creditor_id,debtor_id,-40,(select object_id from ordering_ids where label='partial_original'),now()+interval '2 seconds')
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000102';

do $refund_cap$
declare v_ledger uuid; v_payer uuid; v_split uuid; v_original uuid;
begin
  select ledger_unit_id,creditor_id,debtor_id into v_ledger,v_payer,v_split
  from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000102';
  select object_id into v_original from ordering_ids where label='partial_original';
  begin
    perform pg_temp.add_ordering_expense(v_ledger,'over-refund',v_payer,v_split,-0.1,v_original);
    raise exception 'cumulative refund exceeded the original amount';
  exception when check_violation then null;
  end;
end;
$refund_cap$;

select pg_temp.assert_true(
  (select count(*)=1 and sum(amount)=60
   from public.bilateral_debts
   where activity_id='c2000000-0000-0000-0000-000000000102'
     and debtor_participant_id='c2200000-0000-0000-0000-000000000202'
     and creditor_participant_id='c2200000-0000-0000-0000-000000000201'),
  'multiple settlements followed by full cumulative refunds preserve the reverse balance'
);

select pg_temp.authenticate('c2100000-0000-0000-0000-000000000002');
do $reverse_repayment$
declare v_version bigint; v_activity uuid := 'c2000000-0000-0000-0000-000000000102'; v_debtor uuid; v_creditor uuid; v_refund_a uuid; v_refund_b uuid;
begin
  select financial_version into v_version from public.activities where id=v_activity;
  select debtor_id,creditor_id into v_debtor,v_creditor from ordering_activities where activity_id=v_activity;
  select object_id into v_refund_a from ordering_ids where label='partial_refund_60';
  select object_id into v_refund_b from ordering_ids where label='partial_refund_40';
  perform * from public.create_expense_repayment_v2(v_activity,v_creditor,v_debtor,60,'CNY','TARGETED',array[v_refund_a,v_refund_b],now(),null,v_version,'c2400000-0000-0000-0000-000000000104');
end;
$reverse_repayment$;
select pg_temp.assert_true(not exists(select 1 from public.bilateral_debts where activity_id='c2000000-0000-0000-0000-000000000102'),'reverse debt can be settled against the linked refund Expenses');

-- C03: net same-currency reverse debts before spending prepayment. The balance
-- returns to the original account when a later expense creates the offset.
select pg_temp.authenticate('c2100000-0000-0000-0000-000000000001');
do $prepayment_before_debts$
declare v_version bigint; v_activity uuid := 'c2000000-0000-0000-0000-000000000103'; v_debtor uuid; v_creditor uuid;
begin
  select financial_version into v_version from public.activities where id=v_activity;
  select debtor_id,creditor_id into v_debtor,v_creditor from ordering_activities where activity_id=v_activity;
  perform * from public.create_prepayment_v2(v_activity,v_debtor,v_creditor,100,'CNY',now(),null,v_version,'c2500000-0000-0000-0000-000000000101');
  select financial_version into v_version from public.activities where id=v_activity;
  perform * from public.create_prepayment_v2(v_activity,v_debtor,v_creditor,10,'USD',now(),null,v_version,'c2500000-0000-0000-0000-000000000105');
  select financial_version into v_version from public.activities where id=v_activity;
  perform * from public.create_prepayment_v2(v_activity,v_debtor,v_creditor,10,'JPY',now(),null,v_version,'c2500000-0000-0000-0000-000000000106');
end;
$prepayment_before_debts$;
insert into ordering_ids
select 'net_forward', pg_temp.add_ordering_expense(ledger_unit_id,'prepaid forward debt',creditor_id,debtor_id,100)
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000103';
insert into ordering_ids
select 'net_reverse', pg_temp.add_ordering_expense(ledger_unit_id,'prepaid reverse debt',debtor_id,creditor_id,100)
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000103';
insert into ordering_ids
select 'net_zero_refund', pg_temp.add_ordering_expense(ledger_unit_id,'zero-net linked refund',debtor_id,debtor_id,-10,(select object_id from ordering_ids where label='net_forward'))
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000103';
select pg_temp.assert_true(
  (select balance=100 from public.prepayment_accounts where activity_id='c2000000-0000-0000-0000-000000000103' and owner_participant_id='c2200000-0000-0000-0000-000000000301' and custodian_participant_id='c2200000-0000-0000-0000-000000000302' and currency='CNY')
  and not exists(select 1 from public.prepayment_usages where activity_id='c2000000-0000-0000-0000-000000000103')
  and not exists(select 1 from public.bilateral_debts where activity_id='c2000000-0000-0000-0000-000000000103'),
  'reverse debt netting occurs before PrepaymentUsage; the balance stays available'
);
select pg_temp.assert_true(
  (select total_prepayment=100 and not completed
      and prepayment_by_currency=jsonb_build_array(
        jsonb_build_object('currency','CNY','balance',100),
        jsonb_build_object('currency','JPY','balance',10),
        jsonb_build_object('currency','USD','balance',10)
      )
   from public.activity_financial_status where activity_id='c2000000-0000-0000-0000-000000000103'),
  'Activity status totals only base-currency prepayment and lists positive currency balances in sorted order'
);
select pg_temp.assert_true(
  (select balance_by_currency=jsonb_build_array(
      jsonb_build_object('currency','CNY','receivable',100,'payable',0,'net_balance',100),
      jsonb_build_object('currency','JPY','receivable',10,'payable',0,'net_balance',10),
      jsonb_build_object('currency','USD','receivable',10,'payable',0,'net_balance',10)
    )
   from public.participant_financial_status
   where activity_id='c2000000-0000-0000-0000-000000000103' and participant_id='c2200000-0000-0000-0000-000000000301')
  and (select balance_by_currency=jsonb_build_array(
      jsonb_build_object('currency','CNY','receivable',0,'payable',100,'net_balance',-100),
      jsonb_build_object('currency','JPY','receivable',0,'payable',10,'net_balance',-10),
      jsonb_build_object('currency','USD','receivable',0,'payable',10,'net_balance',-10)
    )
   from public.participant_financial_status
   where activity_id='c2000000-0000-0000-0000-000000000103' and participant_id='c2200000-0000-0000-0000-000000000302'),
  'Participant balances preserve separate currencies, with owner receivable and custodian payable signs'
);

-- C03: prepayment applies only to debt left after a prior TARGETED allocation.
insert into ordering_ids
select 'targeted_original', pg_temp.add_ordering_expense(ledger_unit_id,'targeted before prepayment',creditor_id,debtor_id,100)
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000104';
do $targeted_then_prepayment$
declare v_version bigint; v_activity uuid := 'c2000000-0000-0000-0000-000000000104'; v_debtor uuid; v_creditor uuid; v_expense uuid; v_transfer uuid;
begin
  select financial_version into v_version from public.activities where id=v_activity;
  select debtor_id,creditor_id into v_debtor,v_creditor from ordering_activities where activity_id=v_activity;
  select object_id into v_expense from ordering_ids where label='targeted_original';
  perform * from public.create_expense_repayment_v2(v_activity,v_debtor,v_creditor,40,'CNY','TARGETED',array[v_expense],now(),null,v_version,'c2400000-0000-0000-0000-000000000105');
  select financial_version into v_version from public.activities where id=v_activity;
  select transfer_id into v_transfer from public.create_prepayment_v2(v_activity,v_debtor,v_creditor,100,'CNY',now(),null,v_version,'c2500000-0000-0000-0000-000000000102');
  insert into ordering_ids values ('targeted_prepayment',v_transfer);
end;
$targeted_then_prepayment$;
select pg_temp.assert_true(
  (select balance=40 from public.prepayment_accounts where activity_id='c2000000-0000-0000-0000-000000000104' and currency='CNY')
  and (select count(*)=1 from public.transfer_components where transfer_id=(select object_id from ordering_ids where label='targeted_prepayment') and component_type='settlement' and amount=60)
  and (select count(*)=1 from public.transfer_components where transfer_id=(select object_id from ordering_ids where label='targeted_prepayment') and component_type='prepayment' and amount=40)
  and not exists(select 1 from public.prepayment_usages where activity_id='c2000000-0000-0000-0000-000000000104')
  and not exists(select 1 from public.bilateral_debts where activity_id='c2000000-0000-0000-0000-000000000104'),
  'new Prepayment directly settles only the 60 remaining after prior TARGETED allocation'
);

-- C03: a settled Final path is excluded from later PrepaymentUsage.
insert into ordering_ids
select 'final_original', pg_temp.add_ordering_expense(ledger_unit_id,'final before prepayment',creditor_id,debtor_id,100)
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000105';
do $final_then_prepayment$
declare v_version bigint; v_activity uuid := 'c2000000-0000-0000-0000-000000000105'; v_debtor uuid; v_creditor uuid;
begin
  select financial_version into v_version from public.activities where id=v_activity;
  select debtor_id,creditor_id into v_debtor,v_creditor from ordering_activities where activity_id=v_activity;
  perform * from public.execute_final_settlement_v2(v_activity,v_debtor,v_creditor,100,'CNY','base_unified',v_version,'c2600000-0000-0000-0000-000000000101',now(),null);
  select financial_version into v_version from public.activities where id=v_activity;
  perform * from public.create_prepayment_v2(v_activity,v_debtor,v_creditor,100,'CNY',now(),null,v_version,'c2500000-0000-0000-0000-000000000103');
end;
$final_then_prepayment$;
select pg_temp.assert_true(
  (select balance=100 from public.prepayment_accounts where activity_id='c2000000-0000-0000-0000-000000000105' and currency='CNY')
  and not exists(select 1 from public.prepayment_usages where activity_id='c2000000-0000-0000-0000-000000000105'),
  'an effective Final allocation is not consumed again by PrepaymentUsage'
);

-- C03: a refund can release Usage after it offsets the remaining debt.
do $prepayment_before_refundable_debt$
declare v_version bigint; v_activity uuid := 'c2000000-0000-0000-0000-000000000106'; v_debtor uuid; v_creditor uuid;
begin
  select financial_version into v_version from public.activities where id=v_activity;
  select debtor_id,creditor_id into v_debtor,v_creditor from ordering_activities where activity_id=v_activity;
  perform * from public.create_prepayment_v2(v_activity,v_debtor,v_creditor,50,'CNY',now(),null,v_version,'c2500000-0000-0000-0000-000000000104');
end;
$prepayment_before_refundable_debt$;
insert into ordering_ids
select 'release_original', pg_temp.add_ordering_expense(ledger_unit_id,'prepayment refund original',creditor_id,debtor_id,100)
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000106';
insert into ordering_ids
select 'release_refund', pg_temp.add_ordering_expense(ledger_unit_id,'refund releases Usage',creditor_id,debtor_id,-100,(select object_id from ordering_ids where label='release_original'))
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000106';
select pg_temp.assert_true(
  (select balance=50 from public.prepayment_accounts where activity_id='c2000000-0000-0000-0000-000000000106' and currency='CNY')
  and not exists(select 1 from public.prepayment_usages where activity_id='c2000000-0000-0000-0000-000000000106')
  and not exists(select 1 from public.bilateral_debts where activity_id='c2000000-0000-0000-0000-000000000106'),
  'refund and reverse offset release the historical Usage back to its account'
);

-- C03: same-currency foreign accounts are used before base-currency accounts;
-- a different foreign currency cannot be applied to the debt.
do $mixed_currency_prepayment$
declare v_version bigint; v_activity uuid := 'c2000000-0000-0000-0000-000000000108'; v_debtor uuid; v_creditor uuid;
begin
  select debtor_id,creditor_id into v_debtor,v_creditor from ordering_activities where activity_id=v_activity;
  select financial_version into v_version from public.activities where id=v_activity;
  perform * from public.create_prepayment_v2(v_activity,v_debtor,v_creditor,100,'CNY',now(),null,v_version,'c2500000-0000-0000-0000-000000000108');
  select financial_version into v_version from public.activities where id=v_activity;
  perform * from public.create_prepayment_v2(v_activity,v_debtor,v_creditor,5,'USD',now(),null,v_version,'c2500000-0000-0000-0000-000000000109');
  select financial_version into v_version from public.activities where id=v_activity;
  perform * from public.create_prepayment_v2(v_activity,v_debtor,v_creditor,10,'JPY',now(),null,v_version,'c2500000-0000-0000-0000-000000000110');
end;
$mixed_currency_prepayment$;
insert into ordering_ids
select 'mixed_currency_usd_expense', created.expense_id
from ordering_activities as f
cross join lateral pg_temp.create_expense_fixture(
  f.ledger_unit_id,
  'USD debt for currency priority',
  10,
  'USD',
  7.25,
  'manual',
  jsonb_build_array(jsonb_build_object('participant_id',f.creditor_id,'amount','10')),
  jsonb_build_array(jsonb_build_object('participant_id',f.debtor_id,'amount','10')),
  '{}'::uuid[],now(),null,null
) as created
where f.activity_id='c2000000-0000-0000-0000-000000000108';
select pg_temp.assert_true(
  exists(select 1 from public.prepayment_usages where activity_id='c2000000-0000-0000-0000-000000000108' and prepayment_currency='USD' and debt_currency='USD' and prepayment_amount=5 and debt_amount=5)
  and exists(select 1 from public.prepayment_usages where activity_id='c2000000-0000-0000-0000-000000000108' and prepayment_currency='CNY' and debt_currency='USD')
  and not exists(select 1 from public.prepayment_usages where activity_id='c2000000-0000-0000-0000-000000000108' and prepayment_currency='JPY')
  and (select balance=10 from public.prepayment_accounts where activity_id='c2000000-0000-0000-0000-000000000108' and currency='JPY'),
  'same-currency Usage precedes base-currency conversion and a foreign currency cannot pay another foreign debt'
);

-- C04: a voided Final transfer stops consuming plan capacity; a new execution
-- with the new financial version can settle the same recommendation.
insert into ordering_ids
select 'void_original', pg_temp.add_ordering_expense(ledger_unit_id,'final void source',creditor_id,debtor_id,100)
from ordering_activities where activity_id='c2000000-0000-0000-0000-000000000107';
do $final_void_reexecute$
declare
  v_version bigint;
  v_activity uuid := 'c2000000-0000-0000-0000-000000000107';
  v_debtor uuid;
  v_creditor uuid;
  v_first_transfer uuid;
  v_second_transfer uuid;
begin
  select financial_version into v_version from public.activities where id=v_activity;
  select debtor_id,creditor_id into v_debtor,v_creditor from ordering_activities where activity_id=v_activity;
  select transfer_id into v_first_transfer
  from public.execute_final_settlement_v2(v_activity,v_debtor,v_creditor,100,'CNY','base_unified',v_version,'c2600000-0000-0000-0000-000000000102',now(),null);
  perform * from public.void_settlement_transfer(v_first_transfer,'test void before re-execution');
  select financial_version into v_version from public.activities where id=v_activity;
  if not exists (
    select 1 from public.preview_final_settlement_v2(v_activity,'base_unified') as p
    where p.from_participant_id=v_debtor and p.to_participant_id=v_creditor and p.amount=100 and not p.is_prepayment_return
  ) then raise exception 'voided final execution still consumes the current plan'; end if;
  select transfer_id into v_second_transfer
  from public.execute_final_settlement_v2(v_activity,v_debtor,v_creditor,100,'CNY','base_unified',v_version,'c2600000-0000-0000-0000-000000000103',now(),null);
  insert into ordering_ids values ('voided_final_transfer',v_first_transfer),('reexecuted_final_transfer',v_second_transfer);
end;
$final_void_reexecute$;
select pg_temp.assert_true(
  (select count(*)=2 from public.transfers where activity_id='c2000000-0000-0000-0000-000000000107' and type='final_settlement')
  and (select count(*)=1 from public.transfers where activity_id='c2000000-0000-0000-0000-000000000107' and type='final_settlement' and is_voided)
  and (select count(*)=1 from public.transfers where activity_id='c2000000-0000-0000-0000-000000000107' and type='final_settlement' and not is_voided)
  and not exists(select 1 from public.bilateral_debts where activity_id='c2000000-0000-0000-0000-000000000107'),
  'Final void preserves history but the re-executed transfer settles current debt once'
);

select pass('C02/C03/C04 ordering, refund, prepayment and final re-execution regressions');
select * from extensions.finish();
rollback;
