\set ON_ERROR_STOP on

begin;
create extension if not exists pgtap with schema extensions;
select extensions.plan(69);

create function pg_temp.authenticate(p_user uuid) returns void
language plpgsql as $function$
begin
  perform set_config('request.jwt.claims', json_build_object('sub',p_user,'role','authenticated')::text, true);
end;
$function$;

insert into auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
values
 ('00000000-0000-0000-0000-000000000000','f9700000-0000-0000-0000-000000000001','authenticated','authenticated','phase7.creator@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','f9700000-0000-0000-0000-000000000002','authenticated','authenticated','phase7.member@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','f9700000-0000-0000-0000-000000000003','authenticated','authenticated','phase7.outsider@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());
insert into public.activities(id,join_code,name,type,base_currency,created_by)
values ('f9700000-0000-0000-0000-000000000001','97000071','Phase 7 normal','normal','CNY','f9700000-0000-0000-0000-000000000001'),
       ('f9700000-0000-0000-0000-000000000002','97000072','Phase 7 large','large','CNY','f9700000-0000-0000-0000-000000000001'),
       ('f9700000-0000-0000-0000-000000000003','97000073','Phase 7 admin','normal','CNY','f9700000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id) values
 ('f9700000-0000-0000-0000-000000000001','f9700000-0000-0000-0000-000000000001'),
 ('f9700000-0000-0000-0000-000000000001','f9700000-0000-0000-0000-000000000002'),
 ('f9700000-0000-0000-0000-000000000002','f9700000-0000-0000-0000-000000000001'),
 ('f9700000-0000-0000-0000-000000000003','f9700000-0000-0000-0000-000000000001'),
 ('f9700000-0000-0000-0000-000000000003','f9700000-0000-0000-0000-000000000002');
insert into public.ledger_units(id,activity_id,name,type) values
 ('f9710000-0000-0000-0000-000000000001','f9700000-0000-0000-0000-000000000001','default','default'),
 ('f9710000-0000-0000-0000-000000000002','f9700000-0000-0000-0000-000000000002','root','root'),
 ('f9710000-0000-0000-0000-000000000003','f9700000-0000-0000-0000-000000000003','default','default');
insert into public.participants(id,activity_id,name,participant_order) values
 ('f9720000-0000-0000-0000-000000000001','f9700000-0000-0000-0000-000000000003','Admin participant',0);
insert into public.exchange_rate_cache(base_currency,quote_currency,rate,observed_at,source)
values ('CNY','USD',0.14,now(),'test');

set local role authenticated;
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000001');
select ok((select activity_name='Phase 7 configured' from public.update_activity_settings('f9700000-0000-0000-0000-000000000003','Phase 7 configured','CNY',false)), 'creator can update Activity settings while active');
select ok((select rate=0.14 from public.get_exchange_rate('CNY','USD')), 'authenticated member can read exchange cache');
select participant_id into temporary phase7_transfer_participant from public.create_participant('f9700000-0000-0000-0000-000000000003','transfer referenced',null);
set local role postgres;
insert into public.transfers(id,activity_id,from_participant_id,to_participant_id,type,amount,currency,recorded_by)
select extensions.gen_random_uuid(),'f9700000-0000-0000-0000-000000000003',p.participant_id,'f9720000-0000-0000-0000-000000000001','settlement',1,'CNY','f9700000-0000-0000-0000-000000000001' from phase7_transfer_participant p;
set local role authenticated;
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000001');
select throws_ok($$select public.delete_participant((select participant_id from phase7_transfer_participant))$$,'23514',null,'participant referenced by a Transfer cannot be deleted before list lock');

select ok((select count(*)=1 from public.create_participant('f9700000-0000-0000-0000-000000000001','Creator',null)), 'member can create participant before list lock');
select ok((select count(*)=1 from public.create_participant('f9700000-0000-0000-0000-000000000001','Member',null)), 'second participant is deterministic');
select ok((select is_new from public.claim_participant('f9700000-0000-0000-0000-000000000001',(select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=0))), 'user can claim an unbound participant');
select ok((select count(*)=1 from public.participant_claims where activity_id='f9700000-0000-0000-0000-000000000001'), 'claim is persisted');

select expense_id into temporary phase7_expense from public.create_expense(
 'f9710000-0000-0000-0000-000000000001','phase7 expense',10,'CNY',1,'manual',
 jsonb_build_array(jsonb_build_object('participant_id',(select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=0),'amount',10)),
 jsonb_build_array(jsonb_build_object('participant_id',(select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=1),'amount',10)),
 '{}'::uuid[] ,now(),null,null);
select ok((select participants_locked_at is not null from public.activities where id='f9700000-0000-0000-0000-000000000001'), 'first expense locks normal participant list');
select throws_ok($$select public.update_activity_settings('f9700000-0000-0000-0000-000000000001','locked','USD',false)$$,'55000',null,'base currency locks after financial write');
select throws_ok($$select public.create_participant('f9700000-0000-0000-0000-000000000001','late',null)$$,'55000',null,'locked normal list rejects additions');
select ok((select deleted from public.delete_expense((select expense_id from phase7_expense))), 'expense logical delete succeeds');
do $$ begin perform public.archive_activity('f9700000-0000-0000-0000-000000000001'); end $$;
select throws_ok($$select public.restore_expense((select expense_id from phase7_expense))$$,'55000',null,'restore rejects archived Activity');
do $$ begin perform public.unarchive_activity('f9700000-0000-0000-0000-000000000001'); end $$;
set local role postgres;
select e.version into temporary phase7_restore_before from public.expenses e where e.id=(select expense_id from phase7_expense);
grant select on phase7_restore_before to authenticated;
set local role authenticated;
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000001');
select * into temporary phase7_restore_result from public.restore_expense((select expense_id from phase7_expense));
select ok((select restored from phase7_restore_result), 'restore_expense restores a deleted fact');
select ok((select version=(select version+1 from phase7_restore_before) from phase7_restore_result), 'restore increments financial fact version exactly once');
select ok((select not is_deleted and exists(select 1 from public.expense_debts where expense_id=(select expense_id from phase7_expense)) from public.expenses where id=(select expense_id from phase7_expense)), 'restore atomically rebuilds debt projection');
select ok((select not restored and version=(select version from public.expenses where id=(select expense_id from phase7_expense)) from public.restore_expense((select expense_id from phase7_expense))), 'restore no-op does not change version');
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000003');
select throws_ok($$select public.restore_expense((select expense_id from phase7_expense))$$,'42501',null,'non-member cannot restore expense');
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000001');

with created as (select * from public.create_expense('f9710000-0000-0000-0000-000000000001','restore original',4,'CNY',1,'manual',jsonb_build_array(jsonb_build_object('participant_id',(select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=0),'amount',4)),jsonb_build_array(jsonb_build_object('participant_id',(select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=1),'amount',4)), '{}'::uuid[],now(),null,null)) select expense_id into temporary phase7_refund_original from created;
with created as (select * from public.create_expense('f9710000-0000-0000-0000-000000000001','restore linked refund',-1,'CNY',1,'manual',jsonb_build_array(jsonb_build_object('participant_id',(select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=0),'amount',-1)),jsonb_build_array(jsonb_build_object('participant_id',(select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=1),'amount',-1)), '{}'::uuid[],now(),null,(select expense_id from phase7_refund_original))) select expense_id into temporary phase7_linked_refund from created;
select ok((select deleted from public.delete_expense((select expense_id from phase7_linked_refund))), 'linked refund can be logically deleted');
select ok((select deleted from public.delete_expense((select expense_id from phase7_refund_original))), 'original can be deleted after refund deletion');
select throws_ok($$select public.restore_expense((select expense_id from phase7_linked_refund))$$,'23514',null,'restore linked refund rejects deleted original');
set local role postgres;
select ok(coalesce((select is_deleted from public.expenses where id=(select expense_id from phase7_linked_refund)),false) and coalesce((select is_deleted from public.expenses where id=(select expense_id from phase7_refund_original)),false), 'failed linked refund restore leaves original and refund unchanged');
set local role authenticated;
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000001');

do $$ begin perform public.create_sub_activity('f9700000-0000-0000-0000-000000000002','first sub-activity'); end $$;
select throws_ok($$select public.create_participant('f9700000-0000-0000-0000-000000000002','late large',null)$$,'55000',null,'large list locked by first sub-activity');
select ok((select private.is_activity_member('f9700000-0000-0000-0000-000000000001')), 'member predicate permits active member');
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000002');
select ok((select is_new from public.claim_participant('f9700000-0000-0000-0000-000000000001',(select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=1))), 'member can claim after list lock');
select ok((select public.unclaim_participant('f9700000-0000-0000-0000-000000000001')), 'member can release its claimed participant');
select throws_ok($$select public.claim_participant('f9700000-0000-0000-0000-000000000001',(select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=0))$$,'23505',null,'one user cannot claim a second participant');
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000003');
select throws_ok($$select public.claim_participant('f9700000-0000-0000-0000-000000000001',(select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=1))$$,'42501',null,'outsider cannot claim participant');
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000001');

select ok((select public.remove_activity_member('f9700000-0000-0000-0000-000000000001','f9700000-0000-0000-0000-000000000002')), 'creator removes member access');
select ok((select not exists(select 1 from public.activity_members where activity_id='f9700000-0000-0000-0000-000000000001' and user_id='f9700000-0000-0000-0000-000000000002') and exists(select 1 from public.participants where activity_id='f9700000-0000-0000-0000-000000000001')), 'member removal preserves participant history');

select ok((select bucket='activity-attachments' and path like 'f9700000-0000-0000-0000-000000000001/%' from public.create_attachment('f9700000-0000-0000-0000-000000000001','f9710000-0000-0000-0000-000000000001',null,'receipt.jpg','image/jpeg',1000)), 'attachment metadata allocates isolated Storage path');
do $$ begin for i in 1..9 loop perform public.create_attachment('f9700000-0000-0000-0000-000000000001','f9710000-0000-0000-0000-000000000001',null,'receipt-'||i||'.jpg','image/jpeg',1000); end loop; end $$;
select throws_ok($$select public.create_attachment('f9700000-0000-0000-0000-000000000001','f9710000-0000-0000-0000-000000000001',null,'receipt-11.jpg','image/jpeg',1000)$$,'54000',null,'attachment limit is enforced per LedgerUnit target');
select id,storage_path into temporary phase7_storage_attachment from public.attachments where activity_id='f9700000-0000-0000-0000-000000000001' order by created_at limit 1;
insert into storage.objects(id,bucket_id,name,owner_id,metadata) select extensions.gen_random_uuid(),'activity-attachments',storage_path,(select auth.uid())::text,'{}'::jsonb from phase7_storage_attachment;
select ok((select count(*)=1 from storage.objects o join phase7_storage_attachment x on x.storage_path=o.name where o.bucket_id='activity-attachments'), 'member can upload a pending object through Storage metadata policy');
select ok((select public.complete_attachment(id) from phase7_storage_attachment), 'member can complete an uploaded attachment');
do $$ begin perform set_config('storage.allow_delete_query','true',true); end $$;
delete from storage.objects o using phase7_storage_attachment x where o.bucket_id='activity-attachments' and o.name=x.storage_path;
select ok((select count(*)=0 from storage.objects o join phase7_storage_attachment x on x.storage_path=o.name), 'member can delete its Storage object');
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000003');
select throws_ok($$insert into storage.objects(id,bucket_id,name,owner_id,metadata) values(extensions.gen_random_uuid(),'activity-attachments','f9700000-0000-0000-0000-000000000001/no-metadata.jpg',(select auth.uid())::text,'{}'::jsonb)$$,'42501',null,'outsider cannot upload without Activity membership and metadata');
set local role anon;
select ok((select count(*)=0 from storage.objects where bucket_id='activity-attachments'), 'anon cannot read private Storage objects');
set local role authenticated;
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000001');
select ok((select public.delete_attachment(id) from phase7_storage_attachment), 'creator can retire attachment metadata before archive');
select attachment_id,path into temporary phase7_archived_attachment from public.create_attachment('f9700000-0000-0000-0000-000000000001','f9710000-0000-0000-0000-000000000001',null,'archive.jpg','image/jpeg',1000);
insert into storage.objects(id,bucket_id,name,owner_id,metadata) select extensions.gen_random_uuid(),'activity-attachments',path,(select auth.uid())::text,'{}'::jsonb from phase7_archived_attachment;
do $$ begin perform public.archive_activity('f9700000-0000-0000-0000-000000000001'); end $$;
select throws_ok($$insert into storage.objects(id,bucket_id,name,owner_id,metadata) values(extensions.gen_random_uuid(),'activity-attachments','f9700000-0000-0000-0000-000000000001/archived-no-metadata.jpg',(select auth.uid())::text,'{}'::jsonb)$$,'42501',null,'archived Activity rejects Storage upload');
do $$ declare n integer; begin perform set_config('storage.allow_delete_query','true',true); delete from storage.objects o using phase7_archived_attachment x where o.bucket_id='activity-attachments' and o.name=x.path; get diagnostics n=row_count; if n<>0 then raise exception 'archived Storage deletion unexpectedly removed an object'; end if; end $$;
select pass('archived Activity rejects Storage deletion');
do $$ begin perform public.unarchive_activity('f9700000-0000-0000-0000-000000000001'); end $$;
select ok((select public.complete_attachment(attachment_id) from phase7_archived_attachment), 'pending attachment completes after unarchive');
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000001');
set local role postgres;
select throws_ok($$insert into public.attachments(activity_id,ledger_unit_id,expense_id,storage_path,mime_type,size_bytes,uploaded_by) values('f9700000-0000-0000-0000-000000000001','f9710000-0000-0000-0000-000000000003',(select expense_id from phase7_expense),'phase7/cross-activity.jpg','image/jpeg',1000,'f9700000-0000-0000-0000-000000000001')$$,'23503',null,'service role cannot cross-link attachment expense and ledger unit');
select ok((select exists(select 1 from storage.buckets b where b.id='activity-attachments' and b.public is false)), 'attachment bucket is private');
set local role authenticated;
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000001');
select ok((select exists(select 1 from pg_policies where schemaname='storage' and tablename='objects' and policyname='activity_attachments_upload')), 'Storage upload policy exists');
select ok((select exists(select 1 from pg_publication_tables where pubname='supabase_realtime' and schemaname='public' and tablename='expenses')), 'expenses are in Realtime publication');
select ok((select count(*)=16 from pg_publication_tables where pubname='supabase_realtime' and schemaname='public' and tablename in ('activities','activity_members','ledger_units','participants','participant_claims','expenses','transfers','expense_debts','bilateral_debts','transfer_allocations','transfer_components','prepayment_accounts','prepayment_usages','final_settlement_paths','attachments','transfer_disputes')), 'all integration tables are in Realtime publication');
select ok((select count(*) > 0 from public.audit_logs where activity_id='f9700000-0000-0000-0000-000000000001'), 'successful collaboration writes are audited');
select ok((select not has_function_privilege('anon','public.restore_expense(uuid)','execute')), 'anon cannot call restore RPC');
select ok((select not has_table_privilege('authenticated','public.transfer_disputes','insert')), 'authenticated cannot directly insert disputes');
select ok((select not has_table_privilege('authenticated','public.activities','truncate')), 'authenticated cannot truncate business tables');
select ok((select not has_table_privilege('authenticated','public.activities','trigger')), 'authenticated cannot create business triggers');
select ok((select not has_table_privilege('authenticated','public.activities','references')), 'authenticated cannot add business references');
select ok((select not has_table_privilege('authenticated','public.activity_members','update') and not has_table_privilege('authenticated','public.ledger_units','delete')), 'lifecycle direct update/delete are revoked');
select ok((select has_function_privilege('authenticated','private.restore_expense_impl(uuid)','execute') and not has_function_privilege('anon','private.restore_expense_impl(uuid)','execute')), 'private implementations are not exposed to anon/Data API');
select ok((select not has_table_privilege('anon','public.exchange_rate_cache','select') and not has_table_privilege('authenticated','public.exchange_rate_cache','insert')), 'exchange cache is read-only to clients');
select ok((select not exists(select 1 from (values ('activities'),('expenses'),('transfers'),('attachments'),('audit_logs')) as x(table_name) where has_table_privilege('authenticated','public.'||x.table_name,'truncate') or has_table_privilege('authenticated','public.'||x.table_name,'trigger') or has_table_privilege('authenticated','public.'||x.table_name,'references'))), 'authenticated has no dangerous privileges on business tables');

do $$ begin perform public.archive_activity('f9700000-0000-0000-0000-000000000003'); end $$;
select throws_ok($$select public.update_activity_settings('f9700000-0000-0000-0000-000000000003','blocked','CNY',false)$$,'42501',null,'archived Activity rejects settings writes');
select throws_ok($$select public.create_participant('f9700000-0000-0000-0000-000000000003','blocked',null)$$,'42501',null,'archived Activity rejects participant writes');
select throws_ok($$select public.claim_participant('f9700000-0000-0000-0000-000000000003','f9720000-0000-0000-0000-000000000001')$$,'42501',null,'archived Activity rejects claim writes');
select throws_ok($$select public.create_attachment('f9700000-0000-0000-0000-000000000003','f9710000-0000-0000-0000-000000000003',null,'x.jpg','image/jpeg',100)$$,'42501',null,'archived Activity rejects attachment writes');
do $$ begin perform public.unarchive_activity('f9700000-0000-0000-0000-000000000003'); end $$;
select participant_id into temporary phase7_deletable_participant from public.create_participant('f9700000-0000-0000-0000-000000000003','deletable',null);
select ok((select deleted from public.delete_participant((select participant_id from phase7_deletable_participant))), 'unclaimed participant can be logically deleted before list lock');
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000002');
select throws_ok($$select public.claim_participant('f9700000-0000-0000-0000-000000000003',(select participant_id from phase7_deletable_participant))$$,'P0002',null,'deleted participant cannot be claimed');
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000001');

select transfer_id into temporary phase7_transfer from public.create_settlement_transfer(
 'f9700000-0000-0000-0000-000000000001',
 (select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=1),
 (select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=0),10,now(),
 (select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=1));
select ok((select created from public.add_transfer_dispute((select transfer_id from phase7_transfer),(select id from public.participants where activity_id='f9700000-0000-0000-0000-000000000001' and participant_order=0),'check')), 'related participant can add dispute marker');
select financial_version into temporary phase7_dispute_version from public.activities where id='f9700000-0000-0000-0000-000000000001';
select ok((select public.remove_transfer_dispute((select id from public.transfer_disputes where transfer_id=(select transfer_id from phase7_transfer))) and (select financial_version=(select financial_version from phase7_dispute_version) from public.activities where id='f9700000-0000-0000-0000-000000000001')), 'dispute marker can be removed without financial mutation');
select ok((select count(*) > 0 from public.audit_logs where action in ('dispute.create','dispute.remove') and activity_id='f9700000-0000-0000-0000-000000000001'), 'dispute writes are audited');

select ok((select public.transfer_activity_creator('f9700000-0000-0000-0000-000000000003','f9700000-0000-0000-0000-000000000002') = 'f9700000-0000-0000-0000-000000000002'::uuid), 'creator identity transfer requires active member');
select pg_temp.authenticate('f9700000-0000-0000-0000-000000000002');
select ok((select public.delete_activity('f9700000-0000-0000-0000-000000000003')), 'new creator can logically delete Activity');
select ok((select not exists(select 1 from public.activities where id='f9700000-0000-0000-0000-000000000003')), 'logically deleted Activity is hidden from member reads');
select ok((select not exists(select 1 from public.ledger_units where activity_id='f9700000-0000-0000-0000-000000000003') and not exists(select 1 from public.participants where activity_id='f9700000-0000-0000-0000-000000000003') and not exists(select 1 from public.expenses e join public.ledger_units l on l.id=e.ledger_unit_id where l.activity_id='f9700000-0000-0000-0000-000000000003')), 'deleted Activity hides child ledger and financial rows');
set local role postgres;
select ok((select is_deleted from public.activities where id='f9700000-0000-0000-0000-000000000003'), 'logical deletion preserves Activity history');
set local role authenticated;

select * from extensions.finish();
rollback;
