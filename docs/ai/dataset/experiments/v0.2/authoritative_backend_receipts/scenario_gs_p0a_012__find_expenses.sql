\set ON_ERROR_STOP on
BEGIN;
SET LOCAL statement_timeout = '30s';
INSERT INTO auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
VALUES ('00000000-0000-0000-0000-000000000000','6baf0140-42b5-586f-804c-c0ccf8e39a95','authenticated','authenticated','receipt-harness-local@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());
INSERT INTO public.activities(id,join_code,name,type,base_currency,multi_currency_enabled,created_by)
VALUES ('30efdb39-223f-5ad1-a0a1-7b4e2d90c3f8','08788390','Receipt harness fixture','normal','CNY',true,'6baf0140-42b5-586f-804c-c0ccf8e39a95');
INSERT INTO public.activity_members(activity_id,user_id) VALUES ('30efdb39-223f-5ad1-a0a1-7b4e2d90c3f8','6baf0140-42b5-586f-804c-c0ccf8e39a95');
INSERT INTO public.ledger_units(id,activity_id,name,type) VALUES ('fe075cab-d132-5f00-a594-5c8a1542630d','30efdb39-223f-5ad1-a0a1-7b4e2d90c3f8','Default','default');
INSERT INTO public.participants(id,activity_id,name,participant_order) VALUES ('b260e598-edcb-57d6-92b0-4d6c31656395','30efdb39-223f-5ad1-a0a1-7b4e2d90c3f8','fixture-1',0);
INSERT INTO public.participants(id,activity_id,name,participant_order) VALUES ('c948c03b-62c4-5696-9972-e8f8723aad5e','30efdb39-223f-5ad1-a0a1-7b4e2d90c3f8','fixture-2',1);
INSERT INTO public.expenses(id,ledger_unit_id,title,original_amount,original_currency,fx_rate,base_amount,split_method,occurred_at,note,original_expense_id,created_by,updated_by,version,is_deleted,fx_rate_source,fx_rate_observed_at,icon_key,financial_locked)
VALUES ('2b6cbad0-6f9a-5371-9e98-0193d6e9475a','fe075cab-d132-5f00-a594-5c8a1542630d','设备租赁','100','CNY','1','100','manual','2026-09-10T18:00:00+08:00',NULL,NULL,'6baf0140-42b5-586f-804c-c0ccf8e39a95','6baf0140-42b5-586f-804c-c0ccf8e39a95',1,false,'same_currency',NULL,'money',false);
INSERT INTO public.payments(expense_id,participant_id,amount,base_amount) VALUES ('2b6cbad0-6f9a-5371-9e98-0193d6e9475a','b260e598-edcb-57d6-92b0-4d6c31656395','100',('100'::numeric*'1'::numeric));
INSERT INTO public.splits(expense_id,participant_id,amount,base_amount) VALUES ('2b6cbad0-6f9a-5371-9e98-0193d6e9475a','c948c03b-62c4-5696-9972-e8f8723aad5e','100',('100'::numeric*'1'::numeric));
SET LOCAL ROLE service_role;
DO $fixture_auth$ BEGIN PERFORM set_config('request.jwt.claims',jsonb_build_object('sub','6baf0140-42b5-586f-804c-c0ccf8e39a95','role','service_role')::text,true); END $fixture_auth$;
SELECT private.rebuild_activity_debt_projection('30efdb39-223f-5ad1-a0a1-7b4e2d90c3f8');
SELECT jsonb_build_object('query','public.expenses + ledger_units + activities', 'rows',coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.occurred_at DESC,e.id),'[]'::jsonb))
FROM public.expenses e JOIN public.ledger_units lu ON lu.id=e.ledger_unit_id JOIN public.activities a ON a.id=lu.activity_id WHERE a.id='30efdb39-223f-5ad1-a0a1-7b4e2d90c3f8' AND e.is_deleted=false AND lu.is_deleted=false AND e.title ILIKE '%'||'设备租赁'||'%';
SELECT jsonb_build_object(
  'status','success','result_id','f7407f6b-f74c-5b77-9378-ae50f7184c10',
  'observed_at',to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
  'financial_version',(SELECT financial_version::text FROM public.activities WHERE id='30efdb39-223f-5ad1-a0a1-7b4e2d90c3f8'),
  'data',jsonb_build_object(
    'items',(SELECT coalesce(jsonb_agg(jsonb_build_object(
      'id',e.id::text,'activity_id',a.id::text,'ledger_unit_id',e.ledger_unit_id::text,'title',e.title,
      'original',jsonb_build_object('amount',e.original_amount::text,'currency',e.original_currency::text),
      'base',jsonb_build_object('amount',e.base_amount::text,'currency',a.base_currency::text),
      'fx_snapshot',jsonb_build_object('rate',e.fx_rate::text,'source',CASE WHEN e.fx_rate_source='same_currency' THEN 'base_currency' ELSE e.fx_rate_source END,'observed_at',e.fx_rate_observed_at),
      'split_method',e.split_method::text,
      'payments',(SELECT coalesce(jsonb_agg(jsonb_build_object('participant_id',p.participant_id::text,'amount',p.amount::text) ORDER BY p.participant_id),'[]'::jsonb) FROM public.payments p WHERE p.expense_id=e.id),
      'splits',(SELECT coalesce(jsonb_agg(jsonb_build_object('participant_id',sp.participant_id::text,'amount',sp.amount::text) ORDER BY sp.participant_id),'[]'::jsonb) FROM public.splits sp WHERE sp.expense_id=e.id),
      'occurred_at',e.occurred_at,'note',e.note,'icon_key',e.icon_key,'original_expense_id',e.original_expense_id::text,
      'financial_locked',e.financial_locked,'version',e.version::text,'is_deleted',e.is_deleted
    ) ORDER BY e.occurred_at DESC,e.id),'[]'::jsonb) FROM public.expenses e JOIN public.ledger_units lu ON lu.id=e.ledger_unit_id JOIN public.activities a ON a.id=lu.activity_id WHERE a.id='30efdb39-223f-5ad1-a0a1-7b4e2d90c3f8' AND e.is_deleted=false AND lu.is_deleted=false AND e.title ILIKE '%'||'设备租赁'||'%'),
    'next_cursor',null,'truncated',false
  )
);
ROLLBACK;
