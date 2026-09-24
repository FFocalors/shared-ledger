\set ON_ERROR_STOP on

create extension if not exists pgtap with schema extensions;

begin;

\ir legacy_rpc_fixture_adapters.sql

select plan(28);

insert into auth.users(
  instance_id, id, aud, role, email, encrypted_password,
  email_confirmed_at, raw_app_meta_data, raw_user_meta_data, created_at, updated_at
)
values (
  '00000000-0000-0000-0000-000000000000',
  'aa300000-0000-0000-0000-000000000001',
  'authenticated', 'authenticated', 'aa.original@example.invalid',
  crypt('fixture', gen_salt('bf')), now(), '{}', '{}', now(), now()
);

-- Each case has its own Activity so the BilateralDebt projection cannot net
-- unrelated cases against each other.
create temporary table aa_cases on commit drop as
select label, n,
       ('aa000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid activity_id,
       ('aa100000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid unit_id
from (values
  ('single_payer', 1), ('multi_payer', 2), ('multi_creditor', 3),
  ('foreign_aa', 4), ('negative_aa', 5), ('micro_foreign', 6)
) as cases(label, n);

insert into public.activities(
  id, join_code, name, type, base_currency, multi_currency_enabled, created_by
)
select activity_id, '9410000' || n::text, 'AA original ' || label,
       (case when label = 'negative_aa' then 'large' else 'normal' end)::public.activity_type,
       'CNY', true, 'aa300000-0000-0000-0000-000000000001'::uuid
from aa_cases;

insert into public.activity_members(activity_id, user_id)
select activity_id, 'aa300000-0000-0000-0000-000000000001'::uuid
from aa_cases;

insert into public.ledger_units(id, activity_id, name, type)
select unit_id, activity_id, 'Main', 'default'
from aa_cases;

create temporary table aa_people on commit drop as
select c.label, p.ord,
       chr(64 + p.ord) as person,
       ('aa200000-0000-0000-0000-' || lpad((c.n * 10 + p.ord)::text, 12, '0'))::uuid participant_id,
       c.activity_id
from aa_cases c cross join generate_series(1, 4) as p(ord);

insert into public.participants(id, activity_id, name, participant_order)
select participant_id, activity_id, person, ord - 1
from aa_people;

select set_config(
  'request.jwt.claims',
  '{"sub":"aa300000-0000-0000-0000-000000000001","role":"authenticated"}',
  true
);

create temporary table aa_expenses(
  label text primary key,
  case_label text not null,
  expense_id uuid not null
) on commit drop;

-- Case 1: 100 CNY / 3, including an original 0.0001 tail and independent
-- 0.1 base rounding.
with c as (select * from aa_cases where label = 'single_payer'),
created as (
  select r.expense_id from c cross join lateral pg_temp.create_expense_fixture(
    c.unit_id, '100 / 3 AA', 100, 'CNY', 1, 'aa',
    jsonb_build_array(jsonb_build_object(
      'participant_id', (select participant_id from aa_people where label = c.label and person = 'A'),
      'amount', '100')),
    '[]'::jsonb,
    array(select participant_id from aa_people where label = c.label and ord <= 3 order by ord),
    '2026-09-23 10:00:00+08', null, null, 'money'
  ) r
)
insert into aa_expenses select 'single_payer', 'single_payer', expense_id from created;

-- Case 2: the exact v0.2 Smoke failure. Original C->A/C->B is
-- 26.6666/6.6667 despite base debt 26.7/6.6.
with c as (select * from aa_cases where label = 'multi_payer'),
created as (
  select r.expense_id from c cross join lateral pg_temp.create_expense_fixture(
    c.unit_id, 'Multi-payer group meal', 100, 'CNY', 1, 'aa',
    jsonb_build_array(
      jsonb_build_object('participant_id', (select participant_id from aa_people where label = c.label and person = 'A'), 'amount', '60'),
      jsonb_build_object('participant_id', (select participant_id from aa_people where label = c.label and person = 'B'), 'amount', '40')),
    '[]'::jsonb,
    array(select participant_id from aa_people where label = c.label and ord <= 3 order by ord),
    '2026-09-23 10:01:00+08', null, null, 'money'
  ) r
)
insert into aa_expenses select 'multi_payer', 'multi_payer', expense_id from created;

-- Case 3: two creditors and two debtors; original greedy matching is
-- C->A=25, D->A=10, D->B=15, with no cross-pair ghost debt.
with c as (select * from aa_cases where label = 'multi_creditor'),
created as (
  select r.expense_id from c cross join lateral pg_temp.create_expense_fixture(
    c.unit_id, 'Two creditors', 100, 'CNY', 1, 'aa',
    jsonb_build_array(
      jsonb_build_object('participant_id', (select participant_id from aa_people where label = c.label and person = 'A'), 'amount', '60'),
      jsonb_build_object('participant_id', (select participant_id from aa_people where label = c.label and person = 'B'), 'amount', '40')),
    '[]'::jsonb,
    array(select participant_id from aa_people where label = c.label order by ord),
    '2026-09-23 10:02:00+08', null, null, 'money'
  ) r
)
insert into aa_expenses select 'multi_creditor', 'multi_creditor', expense_id from created;

-- Case 4: USD repeats the multi-payer split with a fixed historical FX
-- snapshot. The original pairs must remain 26.6666/6.6667 USD.
with c as (select * from aa_cases where label = 'foreign_aa'),
created as (
  select r.expense_id from c cross join lateral pg_temp.create_expense_fixture(
    c.unit_id, 'Foreign multi-payer AA', 100, 'USD', 7.25, 'aa',
    jsonb_build_array(
      jsonb_build_object('participant_id', (select participant_id from aa_people where label = c.label and person = 'A'), 'amount', '60'),
      jsonb_build_object('participant_id', (select participant_id from aa_people where label = c.label and person = 'B'), 'amount', '40')),
    '[]'::jsonb,
    array(select participant_id from aa_people where label = c.label and ord <= 3 order by ord),
    '2026-09-23 10:03:00+08', null, null, 'money'
  ) r
)
insert into aa_expenses select 'foreign_aa', 'foreign_aa', expense_id from created;

-- Case 5: leave an earlier 156.2 / 3 AA debt in the same Activity. A later
-- equal positive/negative AA pair must leave its BilateralDebt and Final plan
-- unchanged even when one base debt absorbs a 0.1 tail.
with c as (select * from aa_cases where label = 'negative_aa'),
created as (
  select r.expense_id from c cross join lateral pg_temp.create_expense_fixture(
    c.unit_id, 'Unrelated AA debt before refund', 156.2, 'CNY', 1, 'aa',
    jsonb_build_array(jsonb_build_object(
      'participant_id', (select participant_id from aa_people where label = c.label and person = 'A'),
      'amount', '156.2')),
    '[]'::jsonb,
    array(select participant_id from aa_people where label = c.label and ord <= 3 order by ord),
    '2026-09-23 10:03:30+08', null, null, 'money'
  ) r
)
insert into aa_expenses select 'negative_anchor', 'negative_aa', expense_id from created;

create temporary table aa_negative_bilateral_before on commit drop as
select debtor_participant_id, creditor_participant_id, currency,
       original_amount, base_amount
from public.bilateral_debts
where activity_id = (select activity_id from aa_cases where label = 'negative_aa');

create temporary table aa_negative_plan_before on commit drop as
select from_participant_id, to_participant_id, amount, ordinary_amount,
       prepayment_return_amount, currency
from public.preview_activity_settlement(
  (select activity_id from aa_cases where label = 'negative_aa'));

-- The following linked negative AA fact reverses every original net and pair.
with c as (select * from aa_cases where label = 'negative_aa'),
created as (
  select r.expense_id from c cross join lateral pg_temp.create_expense_fixture(
    c.unit_id, 'Refund parent', 100, 'CNY', 1, 'aa',
    jsonb_build_array(
      jsonb_build_object('participant_id', (select participant_id from aa_people where label = c.label and person = 'A'), 'amount', '60'),
      jsonb_build_object('participant_id', (select participant_id from aa_people where label = c.label and person = 'B'), 'amount', '40')),
    '[]'::jsonb,
    array(select participant_id from aa_people where label = c.label and ord <= 3 order by ord),
    '2026-09-23 10:04:00+08', null, null, 'money'
  ) r
)
insert into aa_expenses select 'refund_parent', 'negative_aa', expense_id from created;

with c as (select * from aa_cases where label = 'negative_aa'),
created as (
  select r.expense_id from c cross join lateral pg_temp.create_expense_fixture(
    c.unit_id, 'Negative AA linked refund', -100, 'CNY', 1, 'aa',
    jsonb_build_array(
      jsonb_build_object('participant_id', (select participant_id from aa_people where label = c.label and person = 'A'), 'amount', '-60'),
      jsonb_build_object('participant_id', (select participant_id from aa_people where label = c.label and person = 'B'), 'amount', '-40')),
    '[]'::jsonb,
    array(select participant_id from aa_people where label = c.label and ord <= 3 order by ord),
    '2026-09-23 10:05:00+08', null,
    (select expense_id from aa_expenses where label = 'refund_parent'), 'money'
  ) r
)
insert into aa_expenses select 'negative_aa', 'negative_aa', expense_id from created;

-- Case 6: two real 0.0033 JPY debts from a 0.01 JPY AA Expense, although
-- Expense, Payment, Split and Debt base amounts all round to zero.
with c as (select * from aa_cases where label = 'micro_foreign'),
created as (
  select r.expense_id from c cross join lateral pg_temp.create_expense_fixture(
    c.unit_id, 'Micro JPY AA', 0.01, 'JPY', 0.05, 'aa',
    jsonb_build_array(jsonb_build_object(
      'participant_id', (select participant_id from aa_people where label = c.label and person = 'A'),
      'amount', '0.01')),
    '[]'::jsonb,
    array(select participant_id from aa_people where label = c.label and ord <= 3 order by ord),
    '2026-09-23 10:06:00+08', null, null, 'money'
  ) r
)
insert into aa_expenses select 'micro_foreign', 'micro_foreign', expense_id from created;

select ok(not exists (
  select 1 from aa_expenses x join public.expenses e on e.id = x.expense_id
  where (select sum(amount) from public.payments where expense_id = e.id) is distinct from e.original_amount
), 'each Expense conserves original Payment amount');

select ok(not exists (
  select 1 from aa_expenses x join public.expenses e on e.id = x.expense_id
  where (select sum(amount) from public.splits where expense_id = e.id) is distinct from e.original_amount
), 'each Expense conserves original Split amount');

select ok(not exists (
  select 1 from aa_expenses x join public.expenses e on e.id = x.expense_id
  where (select sum(base_amount) from public.payments where expense_id = e.id) is distinct from e.base_amount
), 'each Expense independently conserves base Payment amount');

select ok(not exists (
  select 1 from aa_expenses x join public.expenses e on e.id = x.expense_id
  where (select sum(base_amount) from public.splits where expense_id = e.id) is distinct from e.base_amount
), 'each Expense independently conserves base Split amount');

with base_nets as (
  select x.expense_id, p.participant_id,
         coalesce((select sum(base_amount) from public.payments where expense_id = x.expense_id and participant_id = p.participant_id), 0)
         - coalesce((select sum(base_amount) from public.splits where expense_id = x.expense_id and participant_id = p.participant_id), 0) net_amount
  from aa_expenses x join aa_people p on p.label = x.case_label
), positive_base as (
  select expense_id, sum(greatest(net_amount, 0)) debt_total
  from base_nets group by expense_id
)
select ok(not exists (
  select 1 from positive_base n
  where n.debt_total is distinct from
    coalesce((select sum(amount) from public.expense_debts where expense_id = n.expense_id), 0)
), 'each Expense base debt sum independently equals positive Participant base nets');

-- The fundamental invariant checks every Participant in every Expense. It
-- detects a redistributed creditor amount even when the total debt is right.
with original_net as (
  select x.expense_id, p.participant_id,
         coalesce((select sum(amount) from public.payments where expense_id = x.expense_id and participant_id = p.participant_id), 0)
         - coalesce((select sum(amount) from public.splits where expense_id = x.expense_id and participant_id = p.participant_id), 0) net_amount
  from aa_expenses x join aa_people p on p.label = x.case_label
)
select ok(not exists (
  select 1 from original_net n
  where n.net_amount is distinct from
    coalesce((select sum(original_amount) from public.expense_debts
              where expense_id = n.expense_id and creditor_participant_id = n.participant_id), 0)
    - coalesce((select sum(original_amount) from public.expense_debts
                where expense_id = n.expense_id and debtor_participant_id = n.participant_id), 0)
), 'every Participant original Payment minus Split equals incoming minus outgoing ExpenseDebt');

with original_net as (
  select x.expense_id, p.participant_id,
         coalesce((select sum(amount) from public.payments where expense_id = x.expense_id and participant_id = p.participant_id), 0)
         - coalesce((select sum(amount) from public.splits where expense_id = x.expense_id and participant_id = p.participant_id), 0) net_amount
  from aa_expenses x join aa_people p on p.label = x.case_label
)
select ok(not exists (
  select 1 from public.expense_debts d
  join aa_expenses x on x.expense_id = d.expense_id
  join original_net debtor on debtor.expense_id = d.expense_id and debtor.participant_id = d.debtor_participant_id
  join original_net creditor on creditor.expense_id = d.expense_id and creditor.participant_id = d.creditor_participant_id
  where d.original_amount <= 0 or d.debtor_participant_id = d.creditor_participant_id
     or debtor.net_amount >= 0 or creditor.net_amount <= 0
), 'original net signs determine debtor and creditor topology, including negative AA');

select ok(not exists (
  select 1 from public.payments p join aa_expenses x on x.expense_id = p.expense_id
  where p.amount <> round(p.amount, 4) or p.base_amount <> round(p.base_amount, 1)
  union all
  select 1 from public.splits s join aa_expenses x on x.expense_id = s.expense_id
  where s.amount <> round(s.amount, 4) or s.base_amount <> round(s.base_amount, 1)
  union all
  select 1 from public.expense_debts d join aa_expenses x on x.expense_id = d.expense_id
  where d.original_amount <> round(d.original_amount, 4) or d.amount <> round(d.amount, 1)
), 'original facts and Debt retain four decimals while base retains one decimal');

select is(
  (select array_agg(s.amount order by p.ord) from public.splits s
   join aa_people p on p.participant_id = s.participant_id
   where s.expense_id = (select expense_id from aa_expenses where label = 'single_payer')),
  array[33.3334, 33.3333, 33.3333]::numeric[],
  '100 / 3 AA original Split distributes the four-decimal tail');

select is(
  (select array_agg(s.base_amount order by p.ord) from public.splits s
   join aa_people p on p.participant_id = s.participant_id
   where s.expense_id = (select expense_id from aa_expenses where label = 'single_payer')),
  array[33.4, 33.3, 33.3]::numeric[],
  '100 / 3 AA base Split independently distributes the 0.1 tail');

select is(
  (select array_agg(d.original_amount order by p.ord) from public.expense_debts d
   join aa_people p on p.participant_id = d.debtor_participant_id
   where d.expense_id = (select expense_id from aa_expenses where label = 'single_payer')),
  array[33.3333, 33.3333]::numeric[],
  'single payer receives exact original debts from B and C');

select is(
  (select array_agg(p.amount order by person.ord) from public.payments p
   join aa_people person on person.participant_id = p.participant_id
   where p.expense_id = (select expense_id from aa_expenses where label = 'multi_payer')),
  array[60, 40]::numeric[],
  'Smoke multi-payer original Payment facts are 60 and 40');

select is(
  (select array_agg(s.amount order by p.ord) from public.splits s
   join aa_people p on p.participant_id = s.participant_id
   where s.expense_id = (select expense_id from aa_expenses where label = 'multi_payer')),
  array[33.3334, 33.3333, 33.3333]::numeric[],
  'Smoke multi-payer original Split facts remain intact');

select is(
  (select array_agg(d.original_amount order by creditor.ord) from public.expense_debts d
   join aa_people creditor on creditor.participant_id = d.creditor_participant_id
   join aa_people debtor on debtor.participant_id = d.debtor_participant_id
   where d.expense_id = (select expense_id from aa_expenses where label = 'multi_payer')
     and debtor.person = 'C'),
  array[26.6666, 6.6667]::numeric[],
  'Smoke C->A and C->B original debts are exactly 26.6666 and 6.6667');

select is(
  (select array_agg(d.amount order by creditor.ord) from public.expense_debts d
   join aa_people creditor on creditor.participant_id = d.creditor_participant_id
   where d.expense_id = (select expense_id from aa_expenses where label = 'multi_payer')),
  array[26.7, 6.6]::numeric[],
  'Smoke base debt 26.7/6.6 is allowed without changing original creditor amounts');

select is(
  (select array_agg(d.original_amount order by creditor.ord) from public.bilateral_debts d
   join aa_people creditor on creditor.participant_id = d.creditor_participant_id
   where d.activity_id = (select activity_id from aa_cases where label = 'multi_payer')),
  array[26.6666, 6.6667]::numeric[],
  'BilateralDebt inherits the correct original amount for each creditor');

select is(
  (select array_agg(debtor.person || '>' || creditor.person || ':' || d.original_amount::text
                    order by debtor.ord, creditor.ord)
   from public.expense_debts d
   join aa_people debtor on debtor.participant_id = d.debtor_participant_id
   join aa_people creditor on creditor.participant_id = d.creditor_participant_id
   where d.expense_id = (select expense_id from aa_expenses where label = 'multi_creditor')),
  array['C>A:25.0000', 'D>A:10.0000', 'D>B:15.0000']::text[],
  'multiple creditors keep the exact three original greedy pairs');

select is(
  (select sum(original_amount) from public.expense_debts d
   where d.expense_id = (select expense_id from aa_expenses where label = 'multi_creditor')
     and d.creditor_participant_id = (select participant_id from aa_people where label = 'multi_creditor' and person = 'B')),
  15::numeric,
  'the second creditor receives exactly 15 original currency units');

select ok(
  (select original_currency = 'USD' and fx_rate = 7.25 and base_amount = 725
   from public.expenses where id = (select expense_id from aa_expenses where label = 'foreign_aa')),
  'foreign AA retains its USD/7.25 FX snapshot and independently rounded base amount');

select is(
  (select array_agg(d.original_amount order by creditor.ord) from public.expense_debts d
   join aa_people creditor on creditor.participant_id = d.creditor_participant_id
   where d.expense_id = (select expense_id from aa_expenses where label = 'foreign_aa')),
  array[26.6666, 6.6667]::numeric[],
  'USD AA original debts equal USD Payment minus Split, irrespective of FX rounding');

select is(
  (select array_agg(d.amount order by creditor.ord) from public.expense_debts d
   join aa_people creditor on creditor.participant_id = d.creditor_participant_id
   where d.expense_id = (select expense_id from aa_expenses where label = 'foreign_aa')),
  array[193.3, 48.3]::numeric[],
  'USD AA base debt amounts independently conserve 241.6 CNY');

select ok(not exists (
  select 1 from public.splits refund
  join public.splits parent on parent.participant_id = refund.participant_id
  where refund.expense_id = (select expense_id from aa_expenses where label = 'negative_aa')
    and parent.expense_id = (select expense_id from aa_expenses where label = 'refund_parent')
    and refund.amount <> -parent.amount
), 'linked negative AA Split reverses the original Split per Participant');

select is(
  (select array_agg(debtor.person || '>' || creditor.person || ':' || d.original_amount::text
                    order by debtor.ord, creditor.ord)
   from public.expense_debts d
   join aa_people debtor on debtor.participant_id = d.debtor_participant_id
   join aa_people creditor on creditor.participant_id = d.creditor_participant_id
   where d.expense_id = (select expense_id from aa_expenses where label = 'negative_aa')),
  array['A>C:26.6666', 'B>C:6.6667']::text[],
  'negative AA reverses the exact original debt topology and amounts');

select ok(
  not exists (
    (select * from aa_negative_bilateral_before)
    except all
    (select debtor_participant_id, creditor_participant_id, currency,
            original_amount, base_amount
     from public.bilateral_debts
     where activity_id = (select activity_id from aa_cases where label = 'negative_aa'))
  )
  and not exists (
    (select debtor_participant_id, creditor_participant_id, currency,
            original_amount, base_amount
     from public.bilateral_debts
     where activity_id = (select activity_id from aa_cases where label = 'negative_aa'))
    except all
    (select * from aa_negative_bilateral_before)
  ),
  'equal linked positive and negative AA facts leave earlier BilateralDebt original and base intact'
);

with after_plan as (
  select from_participant_id, to_participant_id, amount, ordinary_amount,
         prepayment_return_amount, currency
  from public.preview_activity_settlement(
    (select activity_id from aa_cases where label = 'negative_aa'))
)
select ok(
  not exists (select * from aa_negative_plan_before except all select * from after_plan)
  and not exists (select * from after_plan except all select * from aa_negative_plan_before),
  'equal linked positive and negative AA facts leave the existing Final plan intact'
);

select ok(
  (select original_amount = 0.01 and base_amount = 0 and fx_rate = 0.05
   from public.expenses where id = (select expense_id from aa_expenses where label = 'micro_foreign'))
  and (select count(*) = 2 and sum(original_amount) = 0.0066 and bool_and(amount = 0)
       from public.expense_debts where expense_id = (select expense_id from aa_expenses where label = 'micro_foreign')),
  '0.01 JPY AA retains two nonzero original debts while every base debt is zero');

select is(
  (select array_agg(d.original_amount order by debtor.ord) from public.expense_debts d
   join aa_people debtor on debtor.participant_id = d.debtor_participant_id
   where d.expense_id = (select expense_id from aa_expenses where label = 'micro_foreign')),
  array[0.0033, 0.0033]::numeric[],
  'zero-base JPY rounding never moves one debtor original amount onto another');

-- A full projection rebuild may recalculate base estimates, but must preserve
-- each Payment, Split and ExpenseDebt original fact and pair identity.
create temporary table aa_before on commit drop as
select 'payment'::text kind, p.expense_id, p.participant_id actor_id,
       null::uuid counterparty_id, p.amount original_amount, p.base_amount,
       e.original_currency, e.fx_rate
from public.payments p join aa_expenses x on x.expense_id = p.expense_id
join public.expenses e on e.id = p.expense_id
union all
select 'split', s.expense_id, s.participant_id, null::uuid, s.amount,
       s.base_amount, e.original_currency, e.fx_rate
from public.splits s join aa_expenses x on x.expense_id = s.expense_id
join public.expenses e on e.id = s.expense_id
union all
select 'debt', d.expense_id, d.debtor_participant_id, d.creditor_participant_id,
       d.original_amount, d.amount, d.original_currency, d.fx_rate
from public.expense_debts d join aa_expenses x on x.expense_id = d.expense_id;

select private.rebuild_activity_debt_projection(activity_id)
from aa_cases order by n;

with after_rebuild as (
  select 'payment'::text kind, p.expense_id, p.participant_id actor_id,
         null::uuid counterparty_id, p.amount original_amount, p.base_amount,
         e.original_currency, e.fx_rate
  from public.payments p join aa_expenses x on x.expense_id = p.expense_id
  join public.expenses e on e.id = p.expense_id
  union all
  select 'split', s.expense_id, s.participant_id, null::uuid, s.amount,
         s.base_amount, e.original_currency, e.fx_rate
  from public.splits s join aa_expenses x on x.expense_id = s.expense_id
  join public.expenses e on e.id = s.expense_id
  union all
  select 'debt', d.expense_id, d.debtor_participant_id, d.creditor_participant_id,
         d.original_amount, d.amount, d.original_currency, d.fx_rate
  from public.expense_debts d join aa_expenses x on x.expense_id = d.expense_id
)
select ok(
  not exists (select * from aa_before except all select * from after_rebuild)
  and not exists (select * from after_rebuild except all select * from aa_before),
  'full projection rebuild leaves original Payment, Split, Debt and pair topology unchanged'
);

select * from extensions.finish();
rollback;
