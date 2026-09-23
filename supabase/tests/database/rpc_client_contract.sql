\set ON_ERROR_STOP on

begin;

create extension if not exists pgtap with schema extensions;
select extensions.plan(2);

select ok(
  not exists (
    select 1
    from (values
      ('public.create_expense(uuid,text,numeric,character,numeric,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)'),
      ('public.create_expense(uuid,text,numeric,character,numeric,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid,text)'),
      ('public.update_expense(uuid,uuid,text,numeric,character,numeric,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)'),
      ('public.update_expense(uuid,uuid,text,numeric,character,numeric,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid,text)'),
      ('public.create_settlement_transfer(uuid,uuid,uuid,numeric,timestamptz,uuid)'),
      ('public.create_settlement_transfer(uuid,uuid,uuid,numeric,character,timestamptz,uuid,uuid)'),
      ('public.create_prepayment(uuid,uuid,uuid,numeric,timestamptz,uuid)'),
      ('public.create_prepayment_return(uuid,uuid,uuid,numeric,timestamptz,uuid)'),
      ('public.create_final_settlement(uuid,uuid,uuid,numeric,timestamptz,uuid)'),
      ('public.execute_final_settlement(uuid,uuid,uuid,numeric,timestamptz,uuid)'),
      ('public.execute_final_settlement_item(uuid,uuid,uuid,numeric,timestamptz,uuid)')
    ) as legacy(signature)
    where has_function_privilege('anon', legacy.signature::regprocedure::oid, 'EXECUTE')
       or has_function_privilege('authenticated', legacy.signature::regprocedure::oid, 'EXECUTE')
  ),
  'every manual-FX and legacy financial write overload is denied to anon and authenticated clients'
);

select ok(
  not exists (
    select 1
    from (values
      ('public.create_expense_auto_rate(uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)'),
      ('public.create_expense_auto_rate(uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid,text)'),
      ('public.update_expense_auto_rate(uuid,uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid)'),
      ('public.update_expense_auto_rate(uuid,uuid,text,numeric,character,public.expense_split_method,jsonb,jsonb,uuid[],timestamptz,text,uuid,text)'),
      ('public.update_expense_presentation(uuid,text,text,text,bigint)'),
      ('public.create_expense_repayment_v2(uuid,uuid,uuid,numeric,character,text,uuid[],timestamptz,uuid,bigint,uuid)'),
      ('public.preview_expense_repayment(uuid,uuid,uuid,numeric,character,text,uuid[],bigint)'),
      ('public.list_transfer_expense_candidates(uuid,uuid,uuid,character)'),
      ('public.get_expense_repayment_progress(uuid,uuid)'),
      ('public.preview_prepayment(uuid,uuid,uuid,numeric,character)'),
      ('public.create_prepayment_v2(uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid)'),
      ('public.create_prepayment_return_v2(uuid,uuid,uuid,numeric,character,timestamptz,uuid,bigint,uuid)'),
      ('public.preview_final_settlement_v2(uuid,text)'),
      ('public.create_final_settlement_v2(uuid,uuid,uuid,numeric,character,text,bigint,uuid,timestamptz,uuid)'),
      ('public.execute_final_settlement_v2(uuid,uuid,uuid,numeric,character,text,bigint,uuid,timestamptz,uuid)')
    ) as expected(signature)
    where not has_function_privilege('authenticated', expected.signature::regprocedure::oid, 'EXECUTE')
       or has_function_privilege('anon', expected.signature::regprocedure::oid, 'EXECUTE')
  ),
  'each current client finance contract is callable by authenticated and denied to anon'
);

select * from extensions.finish();
rollback;
