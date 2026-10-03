\set ON_ERROR_STOP on
BEGIN;
SET LOCAL statement_timeout = '30s';
INSERT INTO auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
VALUES ('00000000-0000-0000-0000-000000000000','6a4710b5-aa72-57fa-a5c1-bbff8356c126','authenticated','authenticated','receipt-harness-local@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());
INSERT INTO public.activities(id,join_code,name,type,base_currency,multi_currency_enabled,created_by,financial_version)
VALUES ('fa2b65a9-06af-5d36-b737-5672e256af7b','32784981','Receipt harness fixture','normal','CNY',true,'6a4710b5-aa72-57fa-a5c1-bbff8356c126',11);
INSERT INTO public.activity_members(activity_id,user_id) VALUES ('fa2b65a9-06af-5d36-b737-5672e256af7b','6a4710b5-aa72-57fa-a5c1-bbff8356c126');
INSERT INTO public.ledger_units(id,activity_id,name,type) VALUES ('d75de571-967c-5276-a1be-05bd29b8ef19','fa2b65a9-06af-5d36-b737-5672e256af7b','Default','default');
INSERT INTO public.participants(id,activity_id,name,participant_order) VALUES ('daf4ead9-d551-5167-9b02-88e82602d7e8','fa2b65a9-06af-5d36-b737-5672e256af7b','fixture-1',0);
INSERT INTO public.participants(id,activity_id,name,participant_order) VALUES ('6eb661f2-881c-5fdb-aa4a-e864b84c05fc','fa2b65a9-06af-5d36-b737-5672e256af7b','fixture-2',1);
INSERT INTO public.expenses(id,ledger_unit_id,title,original_amount,original_currency,fx_rate,base_amount,split_method,occurred_at,note,original_expense_id,created_by,updated_by,version,is_deleted,fx_rate_source,fx_rate_observed_at,icon_key,financial_locked)
VALUES ('724bcbab-b6d4-51d7-8a55-df568a31df31','d75de571-967c-5276-a1be-05bd29b8ef19','设备租赁','100','CNY','1','100','manual','2026-09-14T10:00:00+08:00',NULL,NULL,'6a4710b5-aa72-57fa-a5c1-bbff8356c126','6a4710b5-aa72-57fa-a5c1-bbff8356c126',3,false,'same_currency',NULL,'money',false);
INSERT INTO public.payments(expense_id,participant_id,amount,base_amount) VALUES ('724bcbab-b6d4-51d7-8a55-df568a31df31','daf4ead9-d551-5167-9b02-88e82602d7e8','100',('100'::numeric*'1'::numeric));
INSERT INTO public.splits(expense_id,participant_id,amount,base_amount) VALUES ('724bcbab-b6d4-51d7-8a55-df568a31df31','6eb661f2-881c-5fdb-aa4a-e864b84c05fc','100',('100'::numeric*'1'::numeric));
SET LOCAL ROLE service_role;
DO $fixture_auth$ BEGIN PERFORM set_config('request.jwt.claims',jsonb_build_object('sub','6a4710b5-aa72-57fa-a5c1-bbff8356c126','role','service_role')::text,true); END $fixture_auth$;
SELECT private.rebuild_activity_debt_projection('fa2b65a9-06af-5d36-b737-5672e256af7b');
SELECT jsonb_build_object('rpc','public.get_expense_repayment_progress','rows',coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb))
FROM public.get_expense_repayment_progress('fa2b65a9-06af-5d36-b737-5672e256af7b','724bcbab-b6d4-51d7-8a55-df568a31df31') r;
SELECT jsonb_build_object(
  'status','success','result_id','52906326-7912-5bea-b956-1279bd792266',
  'observed_at',to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
  'financial_version',(SELECT financial_version::text FROM public.activities WHERE id='fa2b65a9-06af-5d36-b737-5672e256af7b'),
  'data',jsonb_build_object(
    'expense',(SELECT jsonb_build_object(
      'id',e.id::text,'activity_id',a.id::text,'ledger_unit_id',e.ledger_unit_id::text,'title',e.title,
      'original',jsonb_build_object('amount',e.original_amount::text,'currency',e.original_currency::text),
      'base',jsonb_build_object('amount',e.base_amount::text,'currency',a.base_currency::text),
      'fx_snapshot',jsonb_build_object('rate',e.fx_rate::text,'source',CASE WHEN e.fx_rate_source='same_currency' THEN 'base_currency' ELSE e.fx_rate_source END,'observed_at',e.fx_rate_observed_at),
      'split_method',e.split_method::text,
      'payments',(SELECT coalesce(jsonb_agg(jsonb_build_object('participant_id',p.participant_id::text,'amount',p.amount::text) ORDER BY p.participant_id),'[]'::jsonb) FROM public.payments p WHERE p.expense_id=e.id),
      'splits',(SELECT coalesce(jsonb_agg(jsonb_build_object('participant_id',sp.participant_id::text,'amount',sp.amount::text) ORDER BY sp.participant_id),'[]'::jsonb) FROM public.splits sp WHERE sp.expense_id=e.id),
      'occurred_at',e.occurred_at,'note',e.note,'icon_key',e.icon_key,'original_expense_id',e.original_expense_id::text,
      'financial_locked',e.financial_locked,'version',e.version::text,'is_deleted',e.is_deleted
    ) FROM public.expenses e JOIN public.ledger_units lu ON lu.id=e.ledger_unit_id JOIN public.activities a ON a.id=lu.activity_id WHERE e.id='724bcbab-b6d4-51d7-8a55-df568a31df31'),
    'repayment_progress',(SELECT coalesce(jsonb_agg(jsonb_build_object(
      'expense_id',r.expense_id::text,'debtor_participant_id',r.debtor_participant_id::text,'creditor_participant_id',r.creditor_participant_id::text,
      'currency',r.debt_currency::text,'base_currency',a.base_currency::text,
      'owed_original_amount',r.debt_original_amount::text,'owed_base_amount',r.debt_base_amount::text,
      'reverse_offset_original_amount',r.offset_original_amount::text,'reverse_offset_base_amount',r.offset_base_amount::text,
      'settled_transfer_original_amount',r.settled_original_amount::text,'settled_transfer_base_amount',r.settled_base_amount::text,
      'prepayment_original_amount',r.prepayment_original_amount::text,'prepayment_base_amount',r.prepayment_base_amount::text,
      'remaining_original_amount',r.remaining_original_amount::text,'remaining_base_amount',r.remaining_base_amount::text
    ) ORDER BY r.debtor_participant_id,r.creditor_participant_id),'[]'::jsonb) FROM public.get_expense_repayment_progress('fa2b65a9-06af-5d36-b737-5672e256af7b','724bcbab-b6d4-51d7-8a55-df568a31df31') r JOIN public.activities a ON a.id='fa2b65a9-06af-5d36-b737-5672e256af7b')
  )
);
ROLLBACK;
