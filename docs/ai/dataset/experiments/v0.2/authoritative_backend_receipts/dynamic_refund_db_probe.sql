\set ON_ERROR_STOP on
BEGIN;
SET LOCAL statement_timeout='30s';
INSERT INTO auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
VALUES ('00000000-0000-0000-0000-000000000000','283973c3-04e6-578a-a551-e03818b6b9fc','authenticated','authenticated','harness-refund@example.invalid',crypt('x',gen_salt('bf')),now(),'{}','{}',now(),now());
INSERT INTO public.activities(id,join_code,name,type,base_currency,created_by) VALUES ('f5ea9b97-aa21-565a-b029-68735b98d440','85578978','Harness dynamic refund probe','normal','CNY','283973c3-04e6-578a-a551-e03818b6b9fc');
INSERT INTO public.ledger_units(id,activity_id,name,type) VALUES ('f5aaed94-328d-5f49-8d86-6e03d64dcaca','f5ea9b97-aa21-565a-b029-68735b98d440','Default','default');
INSERT INTO public.expenses(id,ledger_unit_id,title,original_amount,original_currency,fx_rate,base_amount,split_method,occurred_at,created_by,updated_by,fx_rate_source,icon_key)
VALUES ('318e2d10-f589-5cae-83f2-49ee74adc22e','f5aaed94-328d-5f49-8d86-6e03d64dcaca','probe original',100,'CNY',1,100,'manual',now(),'283973c3-04e6-578a-a551-e03818b6b9fc','283973c3-04e6-578a-a551-e03818b6b9fc','same_currency','money');
INSERT INTO public.expenses(id,ledger_unit_id,title,original_amount,original_currency,fx_rate,base_amount,split_method,occurred_at,original_expense_id,created_by,updated_by,fx_rate_source,icon_key)
VALUES ('1d685d18-3554-5b7e-ba2c-f8a0882ac5b9','f5aaed94-328d-5f49-8d86-6e03d64dcaca','probe refund A',-40,'CNY',1,-40,'manual',now(),'318e2d10-f589-5cae-83f2-49ee74adc22e','283973c3-04e6-578a-a551-e03818b6b9fc','283973c3-04e6-578a-a551-e03818b6b9fc','same_currency','money'),
       ('8fde1421-5c5d-5cc8-aefb-26f9f35b587d','f5aaed94-328d-5f49-8d86-6e03d64dcaca','probe refund B',-60,'CNY',1,-60,'manual',now(),'318e2d10-f589-5cae-83f2-49ee74adc22e','283973c3-04e6-578a-a551-e03818b6b9fc','283973c3-04e6-578a-a551-e03818b6b9fc','same_currency','money');
DO $assert_reject$
BEGIN
  BEGIN
    INSERT INTO public.expenses(id,ledger_unit_id,title,original_amount,original_currency,fx_rate,base_amount,split_method,occurred_at,original_expense_id,created_by,updated_by,fx_rate_source,icon_key)
    VALUES ('7dc3eacf-9e6f-5e45-bc4a-c9c1a34837a5','f5aaed94-328d-5f49-8d86-6e03d64dcaca','probe over limit',-1,'CNY',1,-1,'manual',now(),'318e2d10-f589-5cae-83f2-49ee74adc22e','283973c3-04e6-578a-a551-e03818b6b9fc','283973c3-04e6-578a-a551-e03818b6b9fc','same_currency','money');
    RAISE EXCEPTION 'backend refund limit unexpectedly accepted over-cap event';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $assert_reject$;
SELECT jsonb_build_object('aggregate_original_refund_amount',coalesce(sum(abs(r.original_amount)),0)::text,'refund_events',count(*),'over_limit_insert_rejected',true,'computed_by','public expense refund-limit trigger predicate from migration 20260923032928')
FROM public.expenses r WHERE r.original_expense_id='318e2d10-f589-5cae-83f2-49ee74adc22e' AND NOT r.is_deleted;
ROLLBACK;
