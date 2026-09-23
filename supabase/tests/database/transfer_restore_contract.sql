\set ON_ERROR_STOP on

begin;
create extension if not exists pgtap with schema extensions;
select extensions.plan(1);

select extensions.ok(
  not has_function_privilege('anon','public.restore_transfer(uuid,text)','EXECUTE')
  and not has_function_privilege('authenticated','public.restore_transfer(uuid,text)','EXECUTE')
  and not has_function_privilege('service_role','public.restore_transfer(uuid,text)','EXECUTE')
  and not has_function_privilege('anon','private.restore_transfer_impl(uuid,text)','EXECUTE')
  and not has_function_privilege('authenticated','private.restore_transfer_impl(uuid,text)','EXECUTE')
  and not has_function_privilege('service_role','private.restore_transfer_impl(uuid,text)','EXECUTE'),
  'the historical transfer-restore API is unavailable to client and server roles'
);

select * from extensions.finish();
rollback;
