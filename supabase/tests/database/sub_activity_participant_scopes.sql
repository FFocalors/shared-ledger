\set ON_ERROR_STOP on

begin;

\ir legacy_rpc_fixture_adapters.sql

create extension if not exists pgtap with schema extensions;
select extensions.plan(1);

create function pg_temp.assert_true(p_condition boolean, p_message text)
returns void language plpgsql as $function$
begin
  if p_condition is not true then raise exception 'assertion failed: %', p_message; end if;
end;
$function$;

create function pg_temp.authenticate(p_user uuid) returns void language plpgsql as $function$
begin
  perform set_config('request.jwt.claims', json_build_object('sub',p_user,'role','authenticated')::text, true);
end;
$function$;

insert into auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
values
 ('00000000-0000-0000-0000-000000000000','f7300000-0000-0000-0000-000000000001','authenticated','authenticated','scope.creator@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','f7300000-0000-0000-0000-000000000002','authenticated','authenticated','scope.member@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','f7300000-0000-0000-0000-000000000003','authenticated','authenticated','scope.outsider@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());

create temporary table scope_join_codes(ordinal integer primary key, join_code text unique) on commit drop;
insert into scope_join_codes(ordinal,join_code)
select row_number() over(order by candidate)::integer, candidate::text
from (
  select code as candidate
  from generate_series(90000000,99999999) as code
  where not exists(select 1 from public.activities where join_code=code::text)
  order by code
  limit 2
) available_codes;

insert into public.activities(id,join_code,name,type,base_currency,created_by) values
 ('f7000000-0000-0000-0000-000000000001',(select join_code from scope_join_codes where ordinal=1),'Scope large','large','CNY','f7300000-0000-0000-0000-000000000001'),
 ('f7000000-0000-0000-0000-000000000002',(select join_code from scope_join_codes where ordinal=2),'Scope other large','large','CNY','f7300000-0000-0000-0000-000000000003');
insert into public.activity_members(activity_id,user_id) values
 ('f7000000-0000-0000-0000-000000000001','f7300000-0000-0000-0000-000000000001'),
 ('f7000000-0000-0000-0000-000000000001','f7300000-0000-0000-0000-000000000002'),
 ('f7000000-0000-0000-0000-000000000002','f7300000-0000-0000-0000-000000000003');
insert into public.ledger_units(id,activity_id,name,type) values
 ('f7100000-0000-0000-0000-000000000001','f7000000-0000-0000-0000-000000000001','root','root'),
 ('f7100000-0000-0000-0000-000000000002','f7000000-0000-0000-0000-000000000002','root','root'),
 ('f7100000-0000-0000-0000-000000000003','f7000000-0000-0000-0000-000000000001','pre-migration legacy child','sub_activity'),
 ('f7100000-0000-0000-0000-000000000004','f7000000-0000-0000-0000-000000000001','configured empty corruption case','sub_activity');
update public.ledger_units set participant_scope_configured=true where id='f7100000-0000-0000-0000-000000000004';
insert into public.participants(id,activity_id,name,participant_order,is_deleted) values
 ('f7200000-0000-0000-0000-000000000001','f7000000-0000-0000-0000-000000000001','同名',0,false),
 ('f7200000-0000-0000-0000-000000000002','f7000000-0000-0000-0000-000000000001','同名',1,false),
 ('f7200000-0000-0000-0000-000000000003','f7000000-0000-0000-0000-000000000001','未选成员',2,false),
 ('f7200000-0000-0000-0000-000000000004','f7000000-0000-0000-0000-000000000002','其他活动参与人',0,false),
 ('f7200000-0000-0000-0000-000000000005','f7000000-0000-0000-0000-000000000001','已删除参与人',3,true);

create temporary table scope_test_ids(label text primary key, object_id uuid not null) on commit drop;
create temporary table scope_test_originals(label text primary key, expense_id uuid not null, unit_id uuid not null, version bigint not null) on commit drop;
grant all on scope_test_ids, scope_test_originals to authenticated;
insert into scope_test_ids values('configured_empty','f7100000-0000-0000-0000-000000000004');

create function pg_temp.insert_scope_test_split(p_expense_id uuid,p_participant_id uuid)
returns void language sql security definer set search_path = '' as $function$
  insert into public.splits(expense_id,participant_id,amount) values(p_expense_id,p_participant_id,1);
$function$;
create function pg_temp.scope_has_transfer_source(p_expense_id uuid)
returns boolean language sql stable security definer set search_path = '' as $function$
  select exists (
    select 1 from public.transfer_source_expenses as source
    where source.expense_id = p_expense_id
  );
$function$;

set local role authenticated;
select pg_temp.authenticate('f7300000-0000-0000-0000-000000000001');

insert into scope_test_ids
select 'configured_child', created.ledger_unit_id
from public.create_sub_activity(
  'f7000000-0000-0000-0000-000000000001', 'selected two',
  array['f7200000-0000-0000-0000-000000000001','f7200000-0000-0000-0000-000000000002']::uuid[]
) as created;
insert into scope_test_ids
select 'move_destination', created.ledger_unit_id
from public.create_sub_activity(
  'f7000000-0000-0000-0000-000000000001', 'selected two move destination',
  array['f7200000-0000-0000-0000-000000000001','f7200000-0000-0000-0000-000000000002']::uuid[]
) as created;

select pg_temp.assert_true(
  (select participant_scope_configured from public.ledger_units where id=(select object_id from scope_test_ids where label='configured_child'))
  and (select count(*)=2 from public.sub_activity_participants where ledger_unit_id=(select object_id from scope_test_ids where label='configured_child')),
  'explicit stable participant ids must be persisted as configured scope'
);

-- A soft delete/restore keeps the exact configured membership rows.
select public.delete_sub_activity((select object_id from scope_test_ids where label='configured_child'));
select public.restore_sub_activity((select object_id from scope_test_ids where label='configured_child'));
select pg_temp.assert_true(
  (select count(*)=2 from public.sub_activity_participants where ledger_unit_id=(select object_id from scope_test_ids where label='configured_child')),
  'soft delete and restore must preserve scope membership'
);

-- The old RPC remains callable, but a new child created through it freezes all
-- currently active participants into an explicit scope.
insert into scope_test_ids
select 'legacy_rpc_child', created.ledger_unit_id
from public.create_sub_activity('f7000000-0000-0000-0000-000000000001','legacy client') as created;
select pg_temp.assert_true(
  (select participant_scope_configured from public.ledger_units where id=(select object_id from scope_test_ids where label='legacy_rpc_child'))
  and (select count(*)=3 from public.sub_activity_participants where ledger_unit_id=(select object_id from scope_test_ids where label='legacy_rpc_child')),
  'two-argument compatibility RPC must configure the full active participant list'
);
insert into scope_test_ids
select 'single_person_child', created.ledger_unit_id
from public.create_sub_activity(
  'f7000000-0000-0000-0000-000000000001','single person',
  array['f7200000-0000-0000-0000-000000000001']::uuid[]
) as created;

insert into scope_test_originals
select 'single_person_expense', created.expense_id,
       (select object_id from scope_test_ids where label='single_person_child'), created.version
from public.create_expense_auto_rate(
  (select object_id from scope_test_ids where label='single_person_child'),
  'one selected participant', 12, 'CNY', 'aa',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"12"}]',
  '[]', array['f7200000-0000-0000-0000-000000000001']::uuid[], now(), null, null, 'money'
) as created;
select pg_temp.assert_true(
  (select count(*)=1 from public.payments where expense_id=(select expense_id from scope_test_originals where label='single_person_expense') and participant_id='f7200000-0000-0000-0000-000000000001')
  and (select count(*)=1 from public.splits where expense_id=(select expense_id from scope_test_originals where label='single_person_expense') and participant_id='f7200000-0000-0000-0000-000000000001'),
  'one-person child AA expense must succeed through the public auto-rate RPC'
);

do $test$
declare v_code text; v_message text; v_before integer;
begin
  select count(*) into v_before from public.expenses;
  begin
    perform * from public.create_expense_auto_rate(
      (select object_id from scope_test_ids where label='configured_empty'), 'empty scope payer', 3, 'CNY', 'manual',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"3"}]',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"3"}]',
      '{}'::uuid[], now(), null, null, 'money'
    );
    raise exception 'configured-empty scope payer unexpectedly succeeded';
  exception when check_violation then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'payment participant is outside the configured sub-activity scope' then raise; end if;
  end;
  if (select count(*) from public.expenses) <> v_before then raise exception 'configured-empty scope rejection left an expense'; end if;
end;
$test$;

do $test$
declare v_code text; v_message text; v_original uuid;
begin
  select expense_id into v_original from scope_test_originals where label='single_person_expense';
  begin
    perform * from public.create_expense_auto_rate(
      (select object_id from scope_test_ids where label='single_person_child'), 'outside AA participant', 4, 'CNY', 'aa',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"4"}]', '[]',
      array['f7200000-0000-0000-0000-000000000001','f7200000-0000-0000-0000-000000000003']::uuid[],
      now(), null, null, 'money'
    );
    raise exception 'out-of-scope AA participant succeeded through the public RPC';
  exception when check_violation then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'split participant is outside the configured sub-activity scope' then raise; end if;
  end;
  begin
    perform * from public.update_expense_auto_rate(
      v_original, (select object_id from scope_test_ids where label='single_person_child'),
      'scope-invalid update', 4, 'CNY', 'manual',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"4"}]',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000003","amount":"4"}]',
      '{}'::uuid[], now(), null, null, 'money'
    );
    raise exception 'same-child out-of-scope update succeeded through the public RPC';
  exception when check_violation then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'split participant is outside the configured sub-activity scope' then raise; end if;
  end;
  if not exists(select 1 from public.expenses where id=v_original and original_amount=12 and version=1)
     or not exists(select 1 from public.payments where expense_id=v_original and participant_id='f7200000-0000-0000-0000-000000000001' and amount=12)
     or not exists(select 1 from public.splits where expense_id=v_original and participant_id='f7200000-0000-0000-0000-000000000001' and amount=12) then
    raise exception 'rejected auto-rate update changed expense version or financial children';
  end if;
  perform * from public.create_expense_auto_rate(
    (select object_id from scope_test_ids where label='single_person_child'), 'valid partial refund', -2, 'CNY', 'manual',
    '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"-2"}]',
    '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"-2"}]',
    '{}'::uuid[], now(), null, v_original, 'money'
  );
end;
$test$;

-- A prepayment usage is a rebuildable projection, not a permanent settlement
-- lock. Moving its eligible Expense must rebuild the usage against the new
-- ExpenseDebt and preserve the account funding/balance totals.
select pg_temp.assert_true(
  not exists (
    select 1 from public.expense_debts
    where activity_id='f7000000-0000-0000-0000-000000000001'
      and debtor_participant_id='f7200000-0000-0000-0000-000000000002'
      and creditor_participant_id='f7200000-0000-0000-0000-000000000001'
  ),
  'prepayment must be funded before any debt exists in its direction'
);
create temp table scope_prepayment_funding as
select * from public.create_prepayment_v2(
  'f7000000-0000-0000-0000-000000000001',
  'f7200000-0000-0000-0000-000000000002',
  'f7200000-0000-0000-0000-000000000001',
  3, 'CNY', now() - interval '1 hour', null,
  (select financial_version from public.activities where id='f7000000-0000-0000-0000-000000000001'),
  'f7400000-0000-0000-0000-000000000002'
);
select pg_temp.assert_true(
  (select settlement_amount=0 and prepayment_amount=3 from scope_prepayment_funding)
  and (select balance=3
       from public.prepayment_accounts
       where activity_id='f7000000-0000-0000-0000-000000000001'
         and owner_participant_id='f7200000-0000-0000-0000-000000000002'
         and custodian_participant_id='f7200000-0000-0000-0000-000000000001'
         and currency='CNY')
  and not exists (select 1 from public.prepayment_usages),
  'prepayment must create funding without settling or consuming a pre-existing debt'
);
insert into scope_test_originals
select 'prepayment_move', created.expense_id,
       (select object_id from scope_test_ids where label='configured_child'), created.version
from public.create_expense_auto_rate(
  (select object_id from scope_test_ids where label='configured_child'),
  'prepayment usage move', 8, 'CNY', 'manual',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"8"}]',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000002","amount":"8"}]',
  '{}'::uuid[], now(), null, null, 'money'
) as created;
select pg_temp.assert_true(
  (select count(*)=1
   from public.prepayment_usages as usage
   join public.expense_debts as debt
     on debt.activity_id=usage.activity_id and debt.id=usage.expense_debt_id
   where debt.expense_id=(select expense_id from scope_test_originals where label='prepayment_move')
     and usage.prepayment_amount=3)
  and (select balance=0
       from public.prepayment_accounts
       where activity_id='f7000000-0000-0000-0000-000000000001'
         and owner_participant_id='f7200000-0000-0000-0000-000000000002'
         and custodian_participant_id='f7200000-0000-0000-0000-000000000001'
         and currency='CNY')
  and (select not financial_locked from public.expenses
       where id=(select expense_id from scope_test_originals where label='prepayment_move'))
  and not pg_temp.scope_has_transfer_source(
       (select expense_id from scope_test_originals where label='prepayment_move')),
  'new expense must consume existing prepayment as usage without becoming financially locked'
);
create temp table scope_prepayment_move_totals_before as
select
  (select coalesce(sum(component.amount),0)
   from public.transfers as transfer
   join public.transfer_components as component
     on component.activity_id=transfer.activity_id and component.transfer_id=transfer.id
   where transfer.activity_id='f7000000-0000-0000-0000-000000000001'
     and transfer.from_participant_id='f7200000-0000-0000-0000-000000000002'
     and transfer.to_participant_id='f7200000-0000-0000-0000-000000000001'
     and not transfer.is_voided and component.component_type='prepayment') as funded,
  (select coalesce(sum(usage.prepayment_amount),0)
   from public.prepayment_usages as usage
   join public.prepayment_accounts as account on account.id=usage.account_id
   where account.activity_id='f7000000-0000-0000-0000-000000000001'
     and account.owner_participant_id='f7200000-0000-0000-0000-000000000002'
     and account.custodian_participant_id='f7200000-0000-0000-0000-000000000001'
     and account.currency='CNY') as used,
  (select coalesce(sum(account.balance),0)
   from public.prepayment_accounts as account
   where account.activity_id='f7000000-0000-0000-0000-000000000001'
     and account.owner_participant_id='f7200000-0000-0000-0000-000000000002'
     and account.custodian_participant_id='f7200000-0000-0000-0000-000000000001'
     and account.currency='CNY') as balance,
  (select coalesce(sum(coalesce(debt.base_amount,debt.amount)),0)
   from public.bilateral_debts as debt
   where debt.activity_id='f7000000-0000-0000-0000-000000000001'
     and debt.debtor_participant_id='f7200000-0000-0000-0000-000000000002'
     and debt.creditor_participant_id='f7200000-0000-0000-0000-000000000001'
     and coalesce(debt.currency,'CNY')='CNY') as ordinary_debt;
create temp table scope_prepayment_move_result as
select *
from public.update_expense_auto_rate(
  (select expense_id from scope_test_originals where label='prepayment_move'),
  (select object_id from scope_test_ids where label='move_destination'),
  'prepayment usage moved', 8, 'CNY', 'manual',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"8"}]',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000002","amount":"8"}]',
  '{}'::uuid[], now(), null, null, 'money'
);
select pg_temp.assert_true(
  (select version=2 from scope_prepayment_move_result)
  and exists (
    select 1 from public.expenses
    where id=(select expense_id from scope_test_originals where label='prepayment_move')
      and ledger_unit_id=(select object_id from scope_test_ids where label='move_destination')
  )
  and (select count(*)=1
       from public.prepayment_usages as usage
       join public.expense_debts as debt
         on debt.activity_id=usage.activity_id and debt.id=usage.expense_debt_id
       where debt.expense_id=(select expense_id from scope_test_originals where label='prepayment_move')
         and debt.ledger_unit_id=(select object_id from scope_test_ids where label='move_destination')
         and usage.prepayment_amount=3)
  and (select balance=0
       from public.prepayment_accounts
       where activity_id='f7000000-0000-0000-0000-000000000001'
         and owner_participant_id='f7200000-0000-0000-0000-000000000002'
         and custodian_participant_id='f7200000-0000-0000-0000-000000000001'
         and currency='CNY')
  and (select
    before.funded = after_totals.funded
    and before.used = after_totals.used
    and before.balance = after_totals.balance
    and before.ordinary_debt = after_totals.ordinary_debt
   from scope_prepayment_move_totals_before as before
   cross join lateral (
     select
       (select coalesce(sum(component.amount),0)
        from public.transfers as transfer
        join public.transfer_components as component
          on component.activity_id=transfer.activity_id and component.transfer_id=transfer.id
        where transfer.activity_id='f7000000-0000-0000-0000-000000000001'
          and transfer.from_participant_id='f7200000-0000-0000-0000-000000000002'
          and transfer.to_participant_id='f7200000-0000-0000-0000-000000000001'
          and not transfer.is_voided and component.component_type='prepayment') as funded,
       (select coalesce(sum(usage.prepayment_amount),0)
        from public.prepayment_usages as usage
        join public.prepayment_accounts as account on account.id=usage.account_id
        where account.activity_id='f7000000-0000-0000-0000-000000000001'
          and account.owner_participant_id='f7200000-0000-0000-0000-000000000002'
          and account.custodian_participant_id='f7200000-0000-0000-0000-000000000001'
          and account.currency='CNY') as used,
       (select coalesce(sum(account.balance),0)
        from public.prepayment_accounts as account
        where account.activity_id='f7000000-0000-0000-0000-000000000001'
          and account.owner_participant_id='f7200000-0000-0000-0000-000000000002'
          and account.custodian_participant_id='f7200000-0000-0000-0000-000000000001'
          and account.currency='CNY') as balance,
       (select coalesce(sum(coalesce(debt.base_amount,debt.amount)),0)
        from public.bilateral_debts as debt
        where debt.activity_id='f7000000-0000-0000-0000-000000000001'
          and debt.debtor_participant_id='f7200000-0000-0000-0000-000000000002'
          and debt.creditor_participant_id='f7200000-0000-0000-0000-000000000001'
          and coalesce(debt.currency,'CNY')='CNY') as ordinary_debt
   ) as after_totals
  ),
  'legal move must rebuild debt and usage while preserving funded, used, balance, and ordinary debt totals'
);

do $test$
declare v_code text; v_message text; v_before integer;
begin
  select count(*) into v_before from public.ledger_units where activity_id='f7000000-0000-0000-0000-000000000001';
  begin
    perform * from public.create_sub_activity('f7000000-0000-0000-0000-000000000001','empty scope','{}'::uuid[]);
    raise exception 'empty scope creation unexpectedly succeeded';
  exception when others then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'a sub-activity requires at least one participant' then raise; end if;
  end;
  begin
    perform * from public.create_sub_activity('f7000000-0000-0000-0000-000000000001','null scope',null::uuid[]);
    raise exception 'null scope creation unexpectedly succeeded';
  exception when others then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'a sub-activity requires at least one participant' then raise; end if;
  end;
  begin
    perform * from public.create_sub_activity(
      'f7000000-0000-0000-0000-000000000001','null member id',
      array['f7200000-0000-0000-0000-000000000001',null]::uuid[]
    );
    raise exception 'null participant id unexpectedly succeeded';
  exception when others then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'sub-activity participant ids must not contain null' then raise; end if;
  end;
  if (select count(*) from public.ledger_units where activity_id='f7000000-0000-0000-0000-000000000001') <> v_before then
    raise exception 'failed empty-scope creation left a ledger unit';
  end if;
  begin
    perform * from public.create_sub_activity(
      'f7000000-0000-0000-0000-000000000001','duplicate ids',
      array['f7200000-0000-0000-0000-000000000001','f7200000-0000-0000-0000-000000000001']::uuid[]
    );
    raise exception 'duplicate participant ids unexpectedly succeeded';
  exception when others then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'sub-activity participant ids must be unique' then raise; end if;
  end;
  begin
    perform * from public.create_sub_activity(
      'f7000000-0000-0000-0000-000000000001','cross activity id',
      array['f7200000-0000-0000-0000-000000000004']::uuid[]
    );
    raise exception 'cross-activity participant unexpectedly succeeded';
  exception when others then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'all sub-activity participants must be active in the same activity' then raise; end if;
  end;
  begin
    perform * from public.create_sub_activity(
      'f7000000-0000-0000-0000-000000000001','deleted participant id',
      array['f7200000-0000-0000-0000-000000000005']::uuid[]
    );
    raise exception 'deleted participant id unexpectedly succeeded';
  exception when others then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'all sub-activity participants must be active in the same activity' then raise; end if;
  end;
  if (select count(*) from public.ledger_units where activity_id='f7000000-0000-0000-0000-000000000001') <> v_before then
    raise exception 'failed invalid-scope creation left a ledger unit';
  end if;
end;
$test$;

select pg_temp.authenticate('f7300000-0000-0000-0000-000000000003');
do $test$
declare v_code text; v_message text; v_before integer;
begin
  select count(*) into v_before from public.ledger_units where activity_id='f7000000-0000-0000-0000-000000000001';
  begin
    perform * from public.create_sub_activity(
      'f7000000-0000-0000-0000-000000000001','nonmember attempt',
      array['f7200000-0000-0000-0000-000000000001']::uuid[]
    );
    raise exception 'nonmember creation unexpectedly succeeded';
  exception when insufficient_privilege then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '42501' or v_message <> 'activity not found, archived, or caller is not a member' then raise; end if;
  end;
  if (select count(*) from public.ledger_units where activity_id='f7000000-0000-0000-0000-000000000001') <> v_before then
    raise exception 'nonmember creation attempt left a ledger unit';
  end if;
end;
$test$;
select pg_temp.authenticate('f7300000-0000-0000-0000-000000000001');

do $test$
declare v_code text; v_message text;
begin
  begin
    update public.ledger_units set participant_scope_configured=false
    where id=(select object_id from scope_test_ids where label='configured_child');
    raise exception 'direct scope configuration update unexpectedly succeeded';
  exception when insufficient_privilege then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '42501' then raise; end if;
  end;
end;
$test$;

select pg_temp.assert_true(
  not has_table_privilege('authenticated','public.sub_activity_participants','INSERT')
  and not has_table_privilege('authenticated','public.sub_activity_participants','UPDATE')
  and not has_table_privilege('authenticated','public.sub_activity_participants','DELETE')
  and not has_table_privilege('authenticated','public.ledger_units','UPDATE')
  and not has_function_privilege('authenticated','private.create_sub_activity_impl(uuid,text)','EXECUTE')
  and (select count(*)=2 from public.sub_activity_participants where ledger_unit_id=(select object_id from scope_test_ids where label='configured_child')),
  'members may read their scope, but cannot directly mutate it or invoke the unscoped helper'
);

-- A caller with no membership in this Activity sees no child-scope rows.
select pg_temp.authenticate('f7300000-0000-0000-0000-000000000003');
select pg_temp.assert_true(
  (select count(*)=0 from public.sub_activity_participants where activity_id='f7000000-0000-0000-0000-000000000001'),
  'RLS must hide participant scopes from non-members'
);
select pg_temp.authenticate('f7300000-0000-0000-0000-000000000001');

-- Pre-migration rows with the default false marker remain legacy-unscoped.
select pg_temp.assert_true(
  not (select participant_scope_configured from public.ledger_units where id='f7100000-0000-0000-0000-000000000003')
  and not exists(select 1 from public.sub_activity_participants where ledger_unit_id='f7100000-0000-0000-0000-000000000003'),
  'old sub-activities remain unscoped without invented historical membership'
);

-- Valid selected payer and bearer may differ.
insert into scope_test_originals
select 'valid_child_expense', expense_id, (select object_id from scope_test_ids where label='configured_child'), version
from pg_temp.create_expense_fixture(
  (select object_id from scope_test_ids where label='configured_child'), 'valid selected expense', 10, 'CNY', 1,
  'manual', '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"10"}]',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000002","amount":"10"}]'
);

do $test$
declare v_code text; v_message text; v_before integer;
begin
  select count(*) into v_before from public.expenses;
  begin
    perform * from pg_temp.create_expense_fixture(
      (select object_id from scope_test_ids where label='configured_child'), 'outside payer', 10, 'CNY', 1,
      'manual', '[{"participant_id":"f7200000-0000-0000-0000-000000000003","amount":"10"}]',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000002","amount":"10"}]'
    );
    raise exception 'out-of-scope payer unexpectedly succeeded';
  exception when others then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'payment participant is outside the configured sub-activity scope' then raise; end if;
  end;
  if (select count(*) from public.expenses) <> v_before then raise exception 'rejected payer write left an expense'; end if;

  begin
    perform * from pg_temp.create_expense_fixture(
      (select object_id from scope_test_ids where label='configured_child'), 'outside manual split', 10, 'CNY', 1,
      'manual', '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"10"}]',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000003","amount":"10"}]'
    );
    raise exception 'out-of-scope manual split unexpectedly succeeded';
  exception when others then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'split participant is outside the configured sub-activity scope' then raise; end if;
  end;

  begin
    perform * from pg_temp.create_expense_fixture(
      (select object_id from scope_test_ids where label='configured_child'), 'outside AA split', 10, 'CNY', 1,
      'aa', '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"10"}]', '[]',
      array['f7200000-0000-0000-0000-000000000001','f7200000-0000-0000-0000-000000000003']::uuid[]
    );
    raise exception 'out-of-scope AA split unexpectedly succeeded';
  exception when others then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'split participant is outside the configured sub-activity scope' then raise; end if;
  end;
end;
$test$;

-- Refund payment and split rows are checked by the same target-unit triggers.
do $test$
declare v_code text; v_message text; v_original uuid;
begin
  select expense_id into v_original from scope_test_originals where label='valid_child_expense';
  begin
    perform * from pg_temp.create_expense_fixture(
      (select object_id from scope_test_ids where label='configured_child'), 'outside refund payer', -2, 'CNY', 1,
      'manual', '[{"participant_id":"f7200000-0000-0000-0000-000000000003","amount":"-2"}]',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000002","amount":"-2"}]', '{}', now(), null, v_original
    );
    raise exception 'out-of-scope refund payer unexpectedly succeeded';
  exception when others then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'payment participant is outside the configured sub-activity scope' then raise; end if;
  end;
  begin
    perform * from pg_temp.create_expense_fixture(
      (select object_id from scope_test_ids where label='configured_child'), 'outside refund split', -2, 'CNY', 1,
      'manual', '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"-2"}]',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000003","amount":"-2"}]', '{}', now(), null, v_original
    );
    raise exception 'out-of-scope refund split unexpectedly succeeded';
  exception when others then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'split participant is outside the configured sub-activity scope' then raise; end if;
  end;
end;
$test$;

-- An update first moves the Expense row, replaces all children, then trigger
-- checks the resulting target scope. Legal moves succeed atomically.
insert into scope_test_originals
select 'legal_move', created.expense_id, 'f7100000-0000-0000-0000-000000000001', created.version
from public.create_expense_auto_rate(
  'f7100000-0000-0000-0000-000000000001', 'move into child', 5, 'CNY', 'manual',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000003","amount":"5"}]',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000003","amount":"5"}]',
  '{}'::uuid[], now(), null, null, 'money'
) as created;
create temp table scope_legal_move_result as
select *
from public.update_expense_auto_rate(
  (select expense_id from scope_test_originals where label='legal_move'),
  (select object_id from scope_test_ids where label='configured_child'), 'legal move', 5, 'CNY', 'manual',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"5"}]',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000002","amount":"5"}]',
  '{}'::uuid[], now(), null, null, 'money'
);
select pg_temp.assert_true(
  (select version=2 from scope_legal_move_result)
  and exists (
   select 1 from public.expenses
   where id=(select expense_id from scope_test_originals where label='legal_move')
     and ledger_unit_id=(select object_id from scope_test_ids where label='configured_child')
  )
  and exists (
   select 1 from public.payments
   where expense_id=(select expense_id from scope_test_originals where label='legal_move')
     and participant_id='f7200000-0000-0000-0000-000000000001' and amount=5
  )
  and exists (
   select 1 from public.splits
   where expense_id=(select expense_id from scope_test_originals where label='legal_move')
     and participant_id='f7200000-0000-0000-0000-000000000002' and amount=5
  ),
  'a scope-valid move must replace payment and split rows atomically'
);

-- A real targeted payment creates immutable settlement-source evidence. A
-- subsequent cross-unit move must fail before it cascades any projections.
insert into scope_test_originals
select 'locked_transfer_move', created.expense_id,
       (select object_id from scope_test_ids where label='configured_child'), created.version
from public.create_expense_auto_rate(
  (select object_id from scope_test_ids where label='configured_child'),
  'settled expense stays in scope', 6, 'CNY', 'manual',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"6"}]',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000002","amount":"6"}]',
  '{}'::uuid[], now(), null, null, 'money'
) as created;
select *
from public.create_expense_repayment_v2(
  'f7000000-0000-0000-0000-000000000001',
  'f7200000-0000-0000-0000-000000000002',
  'f7200000-0000-0000-0000-000000000001',
  1, 'CNY', 'TARGETED',
  array[(select expense_id from scope_test_originals where label='locked_transfer_move')]::uuid[],
  now(), 'f7200000-0000-0000-0000-000000000002',
  (select financial_version from public.activities where id='f7000000-0000-0000-0000-000000000001'),
  'f7400000-0000-0000-0000-000000000001'
);
select pg_temp.assert_true(
  (select financial_locked from public.expenses where id=(select expense_id from scope_test_originals where label='locked_transfer_move'))
  and pg_temp.scope_has_transfer_source((select expense_id from scope_test_originals where label='locked_transfer_move')),
  'real targeted settlement must lock its source Expense'
);
do $test$
declare v_code text; v_message text; v_id uuid;
begin
  select expense_id into v_id from scope_test_originals where label='locked_transfer_move';
  begin
    perform * from public.update_expense_auto_rate(
      v_id, (select object_id from scope_test_ids where label='move_destination'),
      'settled expense move rejected', 6, 'CNY', 'manual',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"6"}]',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000002","amount":"6"}]',
      '{}'::uuid[], now(), null, null, 'money'
    );
    raise exception 'settled Expense unexpectedly moved';
  exception when check_violation then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'settled expense financial fields are immutable' then raise; end if;
  end;
  if not exists(select 1 from public.expenses where id=v_id and version=1
      and ledger_unit_id=(select object_id from scope_test_ids where label='configured_child'))
     or not exists(select 1 from public.payments where expense_id=v_id and participant_id='f7200000-0000-0000-0000-000000000001' and amount=6)
     or not exists(select 1 from public.splits where expense_id=v_id and participant_id='f7200000-0000-0000-0000-000000000002' and amount=6)
     or not exists(select 1 from public.expense_debts where expense_id=v_id and ledger_unit_id=(select object_id from scope_test_ids where label='configured_child'))
     or not pg_temp.scope_has_transfer_source(v_id) then
    raise exception 'rejected settled move changed its Expense or financial projections';
  end if;
end;
$test$;

-- A linked refund also locks its source, even though the refund's own Expense
-- has no settlement transfer.
insert into scope_test_originals
select 'locked_refund_move', created.expense_id,
       (select object_id from scope_test_ids where label='configured_child'), created.version
from public.create_expense_auto_rate(
  (select object_id from scope_test_ids where label='configured_child'),
  'refund source stays in scope', 5, 'CNY', 'manual',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"5"}]',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000002","amount":"5"}]',
  '{}'::uuid[], now(), null, null, 'money'
) as created;
select *
from public.create_expense_auto_rate(
  (select object_id from scope_test_ids where label='configured_child'),
  'linked refund locks parent', -2, 'CNY', 'manual',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"-2"}]',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000002","amount":"-2"}]',
  '{}'::uuid[], now(), null,
  (select expense_id from scope_test_originals where label='locked_refund_move'), 'money'
);
select pg_temp.assert_true(
  (select financial_locked from public.expenses where id=(select expense_id from scope_test_originals where label='locked_refund_move')),
  'linked refund must lock its source Expense'
);
do $test$
declare v_code text; v_message text; v_id uuid;
begin
  select expense_id into v_id from scope_test_originals where label='locked_refund_move';
  begin
    perform * from public.update_expense_auto_rate(
      v_id, (select object_id from scope_test_ids where label='move_destination'),
      'refund-locked expense move rejected', 5, 'CNY', 'manual',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"5"}]',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000002","amount":"5"}]',
      '{}'::uuid[], now(), null, null, 'money'
    );
    raise exception 'refund-locked Expense unexpectedly moved';
  exception when check_violation then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'settled expense financial fields are immutable' then raise; end if;
  end;
  if not exists(select 1 from public.expenses where id=v_id and version=1
      and ledger_unit_id=(select object_id from scope_test_ids where label='configured_child'))
     or not exists(select 1 from public.payments where expense_id=v_id and participant_id='f7200000-0000-0000-0000-000000000001' and amount=5)
     or not exists(select 1 from public.splits where expense_id=v_id and participant_id='f7200000-0000-0000-0000-000000000002' and amount=5)
     or not exists(select 1 from public.expense_debts where expense_id=v_id and ledger_unit_id=(select object_id from scope_test_ids where label='configured_child')) then
    raise exception 'rejected refund-locked move changed its Expense or debt projection';
  end if;
end;
$test$;

-- An invalid replacement is rejected after the target unit is set, but the
-- enclosing RPC transaction restores the old unit, version, and child rows.
insert into scope_test_originals
select 'rejected_move', expense_id, 'f7100000-0000-0000-0000-000000000001', version
from pg_temp.create_expense_fixture(
  'f7100000-0000-0000-0000-000000000001', 'rejected move', 7, 'CNY', 1,
  'manual', '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"7"}]',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000002","amount":"7"}]'
);
do $test$
declare v_code text; v_message text; v_id uuid;
begin
  select expense_id into v_id from scope_test_originals where label='rejected_move';
  begin
    perform * from pg_temp.update_expense_fixture(
      v_id, (select object_id from scope_test_ids where label='configured_child'), 'rejected move', 7, 'CNY', 1, 'manual',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"7"}]',
      '[{"participant_id":"f7200000-0000-0000-0000-000000000003","amount":"7"}]'
    );
    raise exception 'out-of-scope expense move unexpectedly succeeded';
  exception when others then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'split participant is outside the configured sub-activity scope' then raise; end if;
  end;
  if not exists(select 1 from public.expenses where id=v_id and ledger_unit_id='f7100000-0000-0000-0000-000000000001' and version=1)
     or not exists(select 1 from public.payments where expense_id=v_id and participant_id='f7200000-0000-0000-0000-000000000001' and amount=7)
     or not exists(select 1 from public.splits where expense_id=v_id and participant_id='f7200000-0000-0000-0000-000000000002' and amount=7) then
    raise exception 'rejected scope move changed the expense or its financial children';
  end if;
end;
$test$;

-- Root and pre-migration children keep their Activity-wide scope.
select pg_temp.assert_true(
  (select count(*)=1 from pg_temp.create_expense_fixture(
    'f7100000-0000-0000-0000-000000000001','root remains activity wide',4,'CNY',1,'manual',
    '[{"participant_id":"f7200000-0000-0000-0000-000000000003","amount":"4"}]',
    '[{"participant_id":"f7200000-0000-0000-0000-000000000003","amount":"4"}]'
  ))
  and (select count(*)=1 from pg_temp.create_expense_fixture(
    'f7100000-0000-0000-0000-000000000003','legacy child remains unscoped',4,'CNY',1,'manual',
    '[{"participant_id":"f7200000-0000-0000-0000-000000000003","amount":"4"}]',
    '[{"participant_id":"f7200000-0000-0000-0000-000000000003","amount":"4"}]'
  )),
  'root and old child expenses remain Activity-wide'
);

-- Simulate a configured-but-empty corruption after an unlocked expense has
-- been created. Use a separate Expense from the refunded one above so the
-- historical financial-child lock remains the first guard for that fact.
insert into scope_test_originals
select 'empty_scope_split_expense', expense_id,
       (select object_id from scope_test_ids where label='single_person_child'), version
from pg_temp.create_expense_fixture(
  (select object_id from scope_test_ids where label='single_person_child'),
  'configured empty scope split test', 6, 'CNY', 1, 'manual',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"6"}]',
  '[{"participant_id":"f7200000-0000-0000-0000-000000000001","amount":"6"}]'
);

reset role;
delete from public.sub_activity_participants
where ledger_unit_id=(select object_id from scope_test_ids where label='single_person_child');
set local role authenticated;
select pg_temp.authenticate('f7300000-0000-0000-0000-000000000001');
do $test$
declare v_code text; v_message text; v_expense_id uuid;
begin
  select expense_id into v_expense_id from scope_test_originals where label='empty_scope_split_expense';
  begin
    perform pg_temp.insert_scope_test_split(v_expense_id,'f7200000-0000-0000-0000-000000000001');
    raise exception 'configured-empty split write unexpectedly succeeded';
  exception when check_violation then
    get stacked diagnostics v_code = returned_sqlstate, v_message = message_text;
    if v_code <> '23514' or v_message <> 'split participant is outside the configured sub-activity scope' then raise; end if;
  end;
end;
$test$;

select pass('sub-activity participant scope is persisted and enforced atomically');
select * from extensions.finish();

rollback;
