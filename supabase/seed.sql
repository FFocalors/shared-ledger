-- Local-only deterministic fixtures. These auth rows are suitable for FK/RLS tests;
-- passwords are intentionally not treated as production credentials.
insert into auth.users (instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
values
 ('00000000-0000-0000-0000-000000000000','10000000-0000-0000-0000-000000000001','authenticated','authenticated','demo.zhang@example.invalid',crypt('demo-password',gen_salt('bf')),now(),'{}','{"display_name":"张三"}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','10000000-0000-0000-0000-000000000002','authenticated','authenticated','demo.li@example.invalid',crypt('demo-password',gen_salt('bf')),now(),'{}','{"display_name":"李四"}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','10000000-0000-0000-0000-000000000003','authenticated','authenticated','demo.wang@example.invalid',crypt('demo-password',gen_salt('bf')),now(),'{}','{"display_name":"王五"}',now(),now()),
 ('00000000-0000-0000-0000-000000000000','10000000-0000-0000-0000-000000000004','authenticated','authenticated','demo.zhao@example.invalid',crypt('demo-password',gen_salt('bf')),now(),'{}','{"display_name":"赵六"}',now(),now());

insert into public.activities (id,join_code,name,type,created_by) values
 ('20000000-0000-0000-0000-000000000001','12345678','日本旅行','large','10000000-0000-0000-0000-000000000001'),
 ('20000000-0000-0000-0000-000000000002','23456789','周末聚餐','normal','10000000-0000-0000-0000-000000000001');
insert into public.activity_members(activity_id,user_id) select a.id,u.id from public.activities a cross join auth.users u where a.id='20000000-0000-0000-0000-000000000001' and u.id in ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000004');
insert into public.activity_members(activity_id,user_id) select '20000000-0000-0000-0000-000000000002',u.id from auth.users u where u.id in ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000003');
insert into public.ledger_units(activity_id,name,type) values
 ('20000000-0000-0000-0000-000000000001','活动根账本','root'),('20000000-0000-0000-0000-000000000001','早餐','sub_activity'),('20000000-0000-0000-0000-000000000001','门票','sub_activity'),('20000000-0000-0000-0000-000000000001','住宿','sub_activity'),('20000000-0000-0000-0000-000000000002','默认账本','default');
insert into public.participants(activity_id,name,participant_order) values
 ('20000000-0000-0000-0000-000000000001','张三',0),('20000000-0000-0000-0000-000000000001','李四',1),('20000000-0000-0000-0000-000000000001','王五',2),('20000000-0000-0000-0000-000000000001','赵六',3),
 ('20000000-0000-0000-0000-000000000002','张三',0),('20000000-0000-0000-0000-000000000002','李四',1),('20000000-0000-0000-0000-000000000002','王五',2);
