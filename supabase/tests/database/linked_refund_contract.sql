\set ON_ERROR_STOP on

begin;
create extension if not exists pgtap with schema extensions;
select extensions.plan(16);

insert into auth.users(instance_id,id,aud,role,email,encrypted_password,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
values ('00000000-0000-0000-0000-000000000000','c4900000-0000-0000-0000-000000000001','authenticated','authenticated','refund-contract@example.invalid',crypt('x',gen_salt('bf')),'{}','{}',now(),now());

insert into public.activities(id,join_code,name,type,base_currency,created_by) values
 ('c4000000-0000-0000-0000-000000000001','99110101','linked refund contract','normal','CNY','c4900000-0000-0000-0000-000000000001'),
 ('c4000000-0000-0000-0000-000000000002','99110102','other refund activity','normal','CNY','c4900000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id) values
 ('c4000000-0000-0000-0000-000000000001','c4900000-0000-0000-0000-000000000001'),
 ('c4000000-0000-0000-0000-000000000002','c4900000-0000-0000-0000-000000000001');
insert into public.ledger_units(id,activity_id,name,type) values
 ('c4100000-0000-0000-0000-000000000001','c4000000-0000-0000-0000-000000000001','refund','default'),
 ('c4100000-0000-0000-0000-000000000002','c4000000-0000-0000-0000-000000000002','other','default');
insert into public.participants(id,activity_id,name,participant_order) values
 ('c4200000-0000-0000-0000-000000000001','c4000000-0000-0000-0000-000000000001','debtor',0),
 ('c4200000-0000-0000-0000-000000000002','c4000000-0000-0000-0000-000000000001','creditor',1),
 ('c4200000-0000-0000-0000-000000000003','c4000000-0000-0000-0000-000000000002','debtor',0),
 ('c4200000-0000-0000-0000-000000000004','c4000000-0000-0000-0000-000000000002','creditor',1);

create temporary table refund_contract_ids(label text primary key,id uuid not null) on commit drop;
grant select,insert,update on refund_contract_ids to authenticated,service_role;
create function pg_temp.add_refund(p_title text,p_amount numeric,p_parent uuid)
returns uuid language sql volatile security invoker set search_path=''
as $function$
  select expense_id
  from public.create_expense_auto_rate(
    'c4100000-0000-0000-0000-000000000001',p_title,p_amount,'CNY','manual',
    jsonb_build_array(jsonb_build_object('participant_id','c4200000-0000-0000-0000-000000000001'::uuid,'amount',p_amount::text)),
    jsonb_build_array(jsonb_build_object('participant_id','c4200000-0000-0000-0000-000000000002'::uuid,'amount',p_amount::text)),
    '{}'::uuid[],now(),null,p_parent,'money'
  )
$function$;

set local role authenticated;
select set_config('request.jwt.claims','{"sub":"c4900000-0000-0000-0000-000000000001","role":"authenticated"}',true);

with created as (
  select * from public.create_expense_auto_rate(
    'c4100000-0000-0000-0000-000000000001','original bill',100,'CNY','manual',
    '[{"participant_id":"c4200000-0000-0000-0000-000000000002","amount":"100"}]',
    '[{"participant_id":"c4200000-0000-0000-0000-000000000001","amount":"100"}]','{}',now(),null,null,'money'
  )
)
insert into refund_contract_ids values ('parent', (select expense_id from created));

with created as (
  select * from public.create_expense_auto_rate(
    'c4100000-0000-0000-0000-000000000002','other-activity source',10,'CNY','manual',
    '[{"participant_id":"c4200000-0000-0000-0000-000000000004","amount":"10"}]',
    '[{"participant_id":"c4200000-0000-0000-0000-000000000003","amount":"10"}]','{}',now(),null,null,'money'
  )
)
insert into refund_contract_ids values ('other_activity_parent',(select expense_id from created));

with created as (
  select pg_temp.add_refund('refund 60',-60,(select id from refund_contract_ids where label='parent')) as id
)
insert into refund_contract_ids values ('refund_60',(select id from created));

select extensions.throws_ok(
  $$select * from public.delete_expense((select id from refund_contract_ids where label='parent'))$$,
  '23514',null,'an active linked refund prevents deletion of its parent Expense'
);

with created as (
  select pg_temp.add_refund('refund 40',-40,(select id from refund_contract_ids where label='parent')) as id
)
insert into refund_contract_ids values ('refund_40',(select id from created));

select extensions.throws_ok(
  $$select pg_temp.add_refund('over cap',-0.01,(select id from refund_contract_ids where label='parent'))$$,
  '23514',null,'active linked refunds cannot exceed the original currency amount'
);

select extensions.throws_ok(
  $$select pg_temp.add_refund('refund points to negative parent',-1,(select id from refund_contract_ids where label='refund_60'))$$,
  '22023',null,'a linked refund cannot use another negative Expense as its parent'
);

select extensions.ok(
  (select deleted from public.delete_expense((select id from refund_contract_ids where label='refund_60'))),
  'soft-deleting a linked refund succeeds'
);

with created as (
  select pg_temp.add_refund('refund after released cap',-60,(select id from refund_contract_ids where label='parent')) as id
)
insert into refund_contract_ids values ('refund_replacement',(select id from created));
select extensions.ok(
  (select sum(abs(original_amount))=100
   from public.expenses
   where original_expense_id=(select id from refund_contract_ids where label='parent') and not is_deleted),
  'deleted refunds release cap for later refunds without increasing the active refund total'
);

select extensions.throws_ok(
  $$select pg_temp.add_refund('cross-activity parent',-1,(select id from refund_contract_ids where label='other_activity_parent'))$$,
  '22023',null,'a refund cannot link to an Expense in another Activity'
);

select extensions.throws_ok(
  $$select pg_temp.add_refund('positive linked refund',1,(select id from refund_contract_ids where label='parent'))$$,
  '22023',null,'a linked refund must have a negative original amount'
);

select extensions.throws_ok(
  $$select pg_temp.add_refund('missing parent',-1,'c4000000-0000-0000-0000-000000000099')$$,
  '22023',null,'a refund reference must resolve to a valid parent Expense'
);

with created as (
  select * from public.create_expense_auto_rate(
    'c4100000-0000-0000-0000-000000000001','deleted source',10,'CNY','manual',
    '[{"participant_id":"c4200000-0000-0000-0000-000000000002","amount":"10"}]',
    '[{"participant_id":"c4200000-0000-0000-0000-000000000001","amount":"10"}]','{}',now(),null,null,'money'
  )
)
insert into refund_contract_ids values ('deleted_parent',(select expense_id from created));
select * from public.delete_expense((select id from refund_contract_ids where label='deleted_parent'));
select extensions.throws_ok(
  $$select pg_temp.add_refund('deleted parent reference',-1,(select id from refund_contract_ids where label='deleted_parent'))$$,
  '22023',null,'a deleted Expense cannot be used as a refund parent'
);

reset role;
set local role service_role;
select extensions.throws_ok(
  $$update public.expenses set fx_rate=fx_rate+0.01 where id=(select id from refund_contract_ids where label='refund_40')$$,
  '22023',null,'internal finance updates cannot change the inherited FX snapshot on a linked refund'
);
select extensions.throws_ok(
  $$update public.payments set amount=amount+1 where expense_id=(select id from refund_contract_ids where label='parent')$$,
  '23514',null,'payment rows remain immutable for a parent with linked-refund history'
);
select extensions.throws_ok(
  $$update public.splits set amount=amount+1 where expense_id=(select id from refund_contract_ids where label='parent')$$,
  '23514',null,'split rows remain immutable for a parent with linked-refund history'
);
select extensions.throws_ok(
  $$update public.expenses set fx_rate_source='legacy_manual' where id=(select id from refund_contract_ids where label='parent')$$,
  '23514',null,'the complete FX snapshot metadata is immutable on a parent with linked-refund history'
);
reset role;
set local role authenticated;
select set_config('request.jwt.claims','{"sub":"c4900000-0000-0000-0000-000000000001","role":"authenticated"}',true);

select * from public.delete_expense((select id from refund_contract_ids where label='refund_40'));
select * from public.delete_expense((select id from refund_contract_ids where label='refund_replacement'));
select extensions.throws_ok(
  $$select * from public.update_expense_auto_rate(
    (select id from refund_contract_ids where label='parent'),
    'c4100000-0000-0000-0000-000000000001','changed parent',99,'CNY','manual',
    '[{"participant_id":"c4200000-0000-0000-0000-000000000002","amount":"99"}]',
    '[{"participant_id":"c4200000-0000-0000-0000-000000000001","amount":"99"}]',
    '{}'::uuid[],now(),null,null,'money'
  )$$,
  '23514',null,'a historical refund permanently prevents parent financial edits after all refunds are deleted'
);
select extensions.throws_ok(
  $$select * from public.delete_expense((select id from refund_contract_ids where label='parent'))$$,
  '23514',null,'a historical refund permanently prevents parent deletion after all refunds are deleted'
);
with before_update as (
  select a.financial_version,e.version
  from public.activities a
  join public.expenses e on e.ledger_unit_id='c4100000-0000-0000-0000-000000000001'
  where a.id='c4000000-0000-0000-0000-000000000001'
    and e.id=(select id from refund_contract_ids where label='parent')
), updated as (
  select * from public.update_expense_presentation(
    (select id from refund_contract_ids where label='parent'),
    'renamed parent','presentation remains editable','money',(select version from before_update)
  )
)
select extensions.ok(
  (select u.financial_locked
      and u.financial_version=b.financial_version
      and a.financial_version=b.financial_version
   from updated u cross join before_update b
   join public.activities a on a.id='c4000000-0000-0000-0000-000000000001'),
  'presentation-only update is allowed, retains the permanent lock, and does not advance financial_version'
);

select * from extensions.finish();
rollback;
