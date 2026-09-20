begin;

-- Ordinary settlement now carries the currency that was actually paid.  The
-- legacy amount columns remain base-currency amounts for prepayment and final
-- settlement compatibility; the new original/base columns are authoritative
-- for ordinary settlement allocations.
alter table public.expense_debts
  add column if not exists original_amount numeric(20,4),
  add column if not exists original_currency character(3),
  add column if not exists fx_rate numeric(20,10);

update public.expense_debts ed
set original_amount = pg_catalog.round(ed.amount / nullif(e.fx_rate,0),4),
    original_currency = e.original_currency,
    fx_rate = e.fx_rate
from public.expenses e
where e.id = ed.expense_id
  and (ed.original_amount is null or ed.original_currency is null or ed.fx_rate is null);

alter table public.expense_debts
  add constraint expense_debts_original_amount_positive
    check (original_amount is null or original_amount > 0),
  add constraint expense_debts_original_currency_valid
    check (original_currency is null or original_currency ~ '^[A-Z]{3}$'),
  add constraint expense_debts_fx_rate_positive
    check (fx_rate is null or fx_rate > 0);

create or replace function private.populate_expense_debt_currency()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare v_currency character(3); v_fx numeric(20,10);
begin
  select e.original_currency, e.fx_rate into v_currency, v_fx
  from public.expenses e
  where e.id = new.expense_id;
  if tg_op = 'INSERT' then
    new.original_amount := pg_catalog.round(new.amount / nullif(v_fx,0),4);
  elsif old.expense_id is distinct from new.expense_id or new.original_amount is null then
    new.original_amount := pg_catalog.round(new.amount / nullif(v_fx,0),4);
  end if;
  new.original_currency := coalesce(new.original_currency,v_currency);
  new.fx_rate := coalesce(new.fx_rate,v_fx);
  return new;
end;
$function$;

drop trigger if exists expense_debts_currency_snapshot on public.expense_debts;
create trigger expense_debts_currency_snapshot
before insert or update on public.expense_debts
for each row execute function private.populate_expense_debt_currency();

-- A single Expense may produce several ExpenseDebt rows.  Never copy the
-- complete Expense original amount into every row: distribute it by each
-- row's base amount and let the final stable row absorb the four-decimal tail.
create or replace function private.normalize_expense_debt_currency(p_expense_id uuid)
returns void
language sql
volatile
security definer
set search_path = ''
as $function$
  with ranked as (
    select ed.id, e.original_amount, e.fx_rate,
      row_number() over (order by debtor.participant_order, debtor.id, creditor.participant_order, creditor.id, ed.id) as rn,
      count(*) over () as cnt,
      coalesce(sum(pg_catalog.round(ed.amount / nullif(e.fx_rate,0),4)) over (
        order by debtor.participant_order, debtor.id, creditor.participant_order, creditor.id, ed.id
        rows between unbounded preceding and 1 preceding
      ),0)::numeric(20,4) as prior_rounded
    from public.expense_debts ed
    join public.expenses e on e.id=ed.expense_id
    join public.participants debtor on debtor.activity_id=ed.activity_id and debtor.id=ed.debtor_participant_id
    join public.participants creditor on creditor.activity_id=ed.activity_id and creditor.id=ed.creditor_participant_id
    where ed.expense_id=p_expense_id
  )
  update public.expense_debts ed
  set original_amount = case when r.rn=r.cnt
    then (r.original_amount-r.prior_rounded)::numeric(20,4)
    else pg_catalog.round(ed.amount/nullif(r.fx_rate,0),4)::numeric(20,4) end,
    original_currency = e.original_currency,
    fx_rate = e.fx_rate
  from ranked r join public.expenses e on e.id=p_expense_id
  where ed.id=r.id;
$function$;

create or replace function private.rebuild_expense_and_bilateral_debts(
  p_expense_id uuid, p_activity_id uuid
)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare v_archived_at timestamptz; v_deleted boolean;
begin
  perform private.lock_debt_projection_activity(p_activity_id);
  select a.archived_at,a.is_deleted into v_archived_at,v_deleted
  from public.activities a where a.id=p_activity_id for update;
  if not found or v_deleted then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived_at is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if;
  perform private.redistribute_aa_split_base_amounts(p_expense_id);
  perform private.normalize_expense_debt_currency(p_expense_id);
  perform private.rebuild_expense_debts_locked(p_expense_id,p_activity_id);
  perform private.normalize_expense_debt_currency(p_expense_id);
  perform private.rebuild_transfer_allocations_locked(p_activity_id);
  perform private.rebuild_prepayment_projections_locked(p_activity_id);
  perform private.rebuild_bilateral_debts_locked(p_activity_id);
  update public.activities a set financial_version=a.financial_version+1 where a.id=p_activity_id;
end;
$function$;

create or replace function private.rebuild_activity_debt_projection(p_activity_id uuid)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare v_expense_id uuid;
begin
  if not exists(select 1 from public.activities a where a.id=p_activity_id) then
    raise exception using errcode='P0002',message='activity was not found for debt rebuild';
  end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  delete from public.prepayment_usages where activity_id=p_activity_id;
  delete from public.prepayment_accounts where activity_id=p_activity_id;
  delete from public.transfer_allocations where activity_id=p_activity_id;
  delete from public.expense_debts where activity_id=p_activity_id;
  for v_expense_id in
    select e.id from public.expenses e join public.ledger_units lu on lu.id=e.ledger_unit_id
    join public.activities a on a.id=lu.activity_id
    where lu.activity_id=p_activity_id and not e.is_deleted and not lu.is_deleted and not a.is_deleted
    order by e.id
  loop
    perform private.redistribute_aa_split_base_amounts(v_expense_id);
    perform private.rebuild_expense_debts_locked(v_expense_id,p_activity_id);
    perform private.normalize_expense_debt_currency(v_expense_id);
  end loop;
  perform private.rebuild_transfer_allocations_locked(p_activity_id);
  perform private.rebuild_prepayment_projections_locked(p_activity_id);
  perform private.rebuild_bilateral_debts_locked(p_activity_id);
end;
$function$;

alter table public.transfer_allocations
  add column if not exists original_amount numeric(20,4),
  add column if not exists base_amount numeric(20,1);

update public.transfer_allocations ta
set base_amount = coalesce(ta.base_amount, ta.amount),
    original_amount = coalesce(ta.original_amount, ta.amount)
where ta.base_amount is null or ta.original_amount is null;

alter table public.transfers
  alter column amount type numeric(20,4);
alter table public.transfer_components
  alter column amount type numeric(20,4);

alter table public.bilateral_debts
  add column if not exists original_amount numeric(20,4),
  add column if not exists currency character(3),
  add column if not exists base_amount numeric(20,1);

-- The previous projection allowed only one row per unordered pair.  Currency
-- is now part of the projection identity; same-currency opposite debts still
-- net, while debts in different currencies remain separate rows.
drop index if exists public.bilateral_debts_activity_unordered_pair_key;
create unique index if not exists bilateral_debts_activity_pair_currency_key
  on public.bilateral_debts (
    activity_id,
    least(debtor_participant_id, creditor_participant_id),
    greatest(debtor_participant_id, creditor_participant_id),
    currency
  );

alter table public.transfers
  add column if not exists request_id uuid;
create unique index if not exists transfers_activity_request_id_key
  on public.transfers(activity_id, request_id)
  where request_id is not null;

-- A settled Expense is financially immutable.  This trigger covers every
-- Expense update path (including the icon wrapper) and the soft-delete path,
-- while allowing harmless presentation edits after settlement.
create or replace function private.assert_expense_financial_mutation_allowed()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_activity_id uuid;
  v_creator uuid;
  v_user uuid := (select auth.uid());
  v_settled boolean;
begin
  select lu.activity_id, a.created_by
    into v_activity_id, v_creator
  from public.ledger_units lu
  join public.activities a on a.id = lu.activity_id
  where lu.id = old.ledger_unit_id;

  select exists (
    select 1
    from public.expense_debts ed
    join public.transfer_allocations ta
      on ta.activity_id = ed.activity_id and ta.expense_debt_id = ed.id
    join public.transfers t on t.id = ta.transfer_id
    where ed.expense_id = old.id
      and not t.is_voided
      and coalesce(ta.base_amount, ta.amount) > 0
  ) into v_settled;

  if tg_op = 'DELETE' then
    if v_settled then
      raise exception using errcode = '23514', message = 'settled expense cannot be deleted';
    end if;
    if v_creator is distinct from v_user and old.created_by is distinct from v_user then
      raise exception using errcode = '42501', message = 'only expense creator or activity creator may delete expense';
    end if;
    return old;
  end if;

  -- delete_expense is a soft update, so apply the same ownership guard here.
  if old.is_deleted = false and new.is_deleted = true then
    if v_settled then
      raise exception using errcode = '23514', message = 'settled expense cannot be deleted';
    end if;
    if v_creator is distinct from v_user and old.created_by is distinct from v_user then
      raise exception using errcode = '42501', message = 'only expense creator or activity creator may delete expense';
    end if;
  end if;

  if v_settled and (
       new.ledger_unit_id is distinct from old.ledger_unit_id
    or new.original_amount is distinct from old.original_amount
    or new.original_currency is distinct from old.original_currency
    or new.fx_rate is distinct from old.fx_rate
    or new.base_amount is distinct from old.base_amount
    or new.split_method is distinct from old.split_method
    or new.occurred_at is distinct from old.occurred_at
    or new.original_expense_id is distinct from old.original_expense_id
    or new.is_deleted is distinct from old.is_deleted
  ) then
    raise exception using errcode = '23514', message = 'settled expense financial fields are immutable';
  end if;
  return new;
end;
$function$;

drop trigger if exists expenses_financial_mutation_guard on public.expenses;
create trigger expenses_financial_mutation_guard
before update or delete on public.expenses
for each row execute function private.assert_expense_financial_mutation_allowed();

create or replace function private.assert_expense_children_mutation_allowed()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare v_expense_id uuid := case when tg_op='DELETE' then old.expense_id else new.expense_id end;
begin
  if exists (
    select 1 from public.expense_debts ed
    join public.transfer_allocations ta on ta.activity_id=ed.activity_id and ta.expense_debt_id=ed.id
    join public.transfers t on t.id=ta.transfer_id
    where ed.expense_id=v_expense_id and not t.is_voided and coalesce(ta.base_amount,ta.amount)>0
  ) then
    raise exception using errcode='23514',message='settled expense financial children are immutable';
  end if;
  if tg_op='DELETE' then return old; else return new; end if;
end;
$function$;

drop trigger if exists payments_settlement_guard on public.payments;
create trigger payments_settlement_guard before insert or update or delete on public.payments
for each row execute function private.assert_expense_children_mutation_allowed();
drop trigger if exists splits_settlement_guard on public.splits;
create trigger splits_settlement_guard before insert or update or delete on public.splits
for each row execute function private.assert_expense_children_mutation_allowed();

-- Stable FIFO helper.  The columns are intentionally nullable for old direct
-- test fixtures; all projection-created rows and the migration backfill carry
-- the complete tuple.
create or replace function private.rebuild_transfer_allocations_locked(p_activity_id uuid)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_transfer record;
  v_debt record;
  v_remaining numeric(20,4);
  v_allocate_original numeric(20,4);
  v_allocate_base numeric(20,1);
  v_debt_base_available numeric(20,1);
begin
  delete from public.transfer_allocations where activity_id = p_activity_id;

  for v_transfer in
    select t.id, t.from_participant_id, t.to_participant_id, t.currency,
           c.id component_id, c.amount
    from public.transfers t
    join public.transfer_components c
      on c.transfer_id = t.id and c.activity_id = t.activity_id
    where t.activity_id = p_activity_id
      and not t.is_voided
      and t.type <> 'final_settlement'::public.transfer_type
      and c.component_type = 'settlement'
    order by t.occurred_at, t.created_at, t.id
  loop
    v_remaining := v_transfer.amount;

    for v_debt in
      with directional as (
        select
          ed.id,
          ed.amount as debt_base,
          coalesce(ed.original_amount, ed.amount)::numeric(20,4) as debt_original,
          coalesce(ed.original_currency, a.base_currency)::character(3) as debt_currency,
          coalesce(ed.fx_rate, 1)::numeric(20,10) as debt_fx,
          e.occurred_at,
          e.created_at,
          e.id as expense_id,
          coalesce(sum(coalesce(ed.original_amount, ed.amount)) over (
            partition by ed.debtor_participant_id, ed.creditor_participant_id,
                         coalesce(ed.original_currency, a.base_currency)
            order by e.occurred_at, e.created_at, e.id, ed.id
            rows between unbounded preceding and 1 preceding
          ), 0::numeric) as prior_original,
          coalesce((
            select sum(coalesce(reverse_ed.original_amount, reverse_ed.amount))
            from public.expense_debts reverse_ed
            where reverse_ed.activity_id = p_activity_id
              and reverse_ed.debtor_participant_id = v_transfer.to_participant_id
              and reverse_ed.creditor_participant_id = v_transfer.from_participant_id
              and coalesce(reverse_ed.original_currency, a.base_currency) =
                  coalesce(ed.original_currency, a.base_currency)
          ), 0::numeric) as reverse_original,
          coalesce((
            select sum(coalesce(ta.original_amount, ta.amount))
            from public.transfer_allocations ta
            where ta.activity_id = p_activity_id and ta.expense_debt_id = ed.id
          ), 0::numeric) as allocated_original,
          coalesce((
            select sum(coalesce(ta.base_amount, ta.amount))
            from public.transfer_allocations ta
            where ta.activity_id = p_activity_id and ta.expense_debt_id = ed.id
          ), 0::numeric) as allocated_base,
          coalesce((
            select sum(pu.amount)
            from public.prepayment_usages pu
            where pu.activity_id = p_activity_id and pu.expense_debt_id = ed.id
          ), 0::numeric) as prepaid_base
        from public.expense_debts ed
        join public.expenses e on e.id = ed.expense_id
        join public.ledger_units lu on lu.id = e.ledger_unit_id
        join public.activities a on a.id = lu.activity_id
        where ed.activity_id = p_activity_id
          and ed.debtor_participant_id = v_transfer.from_participant_id
          and ed.creditor_participant_id = v_transfer.to_participant_id
          and not e.is_deleted and not lu.is_deleted and not a.is_deleted
      ), residual as (
        select d.*,
          least(d.debt_original,
            greatest(d.reverse_original - d.prior_original, 0::numeric)) as cancelled_original
        from directional d
      )
      select r.*,
          greatest(
          r.debt_original - r.cancelled_original - r.allocated_original
            - pg_catalog.round(r.prepaid_base / nullif(r.debt_fx,0),4),
          0::numeric
        )::numeric(20,4) as available_original,
        greatest(
          r.debt_base
          - pg_catalog.round(r.cancelled_original * r.debt_fx, 1)
          - r.allocated_base
          - r.prepaid_base,
          0::numeric
        )::numeric(20,1) as available_base
      from residual r
      where r.debt_currency = v_transfer.currency
         or v_transfer.currency = (select base_currency from public.activities where id = p_activity_id)
      order by r.occurred_at, r.created_at, r.expense_id, r.id
    loop
      exit when v_remaining <= 0;
      if v_transfer.currency = (select base_currency from public.activities where id = p_activity_id) then
        v_debt_base_available := v_debt.available_base;
        if v_debt_base_available > 0 then
          v_allocate_base := least(v_remaining, v_debt_base_available)::numeric(20,1);
          if v_allocate_base >= v_debt_base_available then
            v_allocate_original := v_debt.available_original;
          else
            v_allocate_original := least(
              v_debt.available_original,
              pg_catalog.round(v_allocate_base / nullif(v_debt.debt_fx, 0), 4)
            )::numeric(20,4);
          end if;
        else
          continue;
        end if;
      else
        if v_debt.available_original > 0 then
          v_allocate_original := least(v_remaining, v_debt.available_original)::numeric(20,4);
          if v_allocate_original >= v_debt.available_original then
            v_allocate_base := v_debt.available_base;
          else
            v_allocate_base := pg_catalog.round(v_allocate_original * v_debt.debt_fx, 1)::numeric(20,1);
          end if;
        else
          continue;
        end if;
      end if;

      if v_allocate_original > 0 and v_allocate_base > 0 then
        insert into public.transfer_allocations(
          activity_id, transfer_id, settlement_component_id, expense_debt_id,
          amount, original_amount, base_amount
        ) values (
          p_activity_id, v_transfer.id, v_transfer.component_id, v_debt.id,
          v_allocate_base, v_allocate_original, v_allocate_base
        );
        v_remaining := v_remaining - case
          when v_transfer.currency = (select base_currency from public.activities where id = p_activity_id)
            then v_allocate_base else v_allocate_original end;
      end if;
    end loop;
  end loop;
end;
$function$;

-- Bilateral projection is currency-aware.  Residual debt facts are netted only
-- within the same currency and pair; FX differences therefore never create a
-- phantom base-currency debt.  The base amount of a residual row uses the
-- winning direction's own snapshot-weighted residual, while `amount` remains
-- the legacy base amount consumed by prepayment/final-settlement code.
create or replace function private.rebuild_bilateral_debts_locked(p_activity_id uuid)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
begin
  delete from public.bilateral_debts where activity_id = p_activity_id;

  insert into public.bilateral_debts(
    activity_id, debtor_participant_id, creditor_participant_id,
    amount, original_amount, currency, base_amount
  )
  with raw_debts as (
    select
      ed.id as expense_debt_id,
      ed.expense_id,
      ed.activity_id,
      ed.debtor_participant_id,
      ed.creditor_participant_id,
      coalesce(ed.original_currency, a.base_currency)::character(3) as currency,
      coalesce(ed.original_amount, ed.amount)::numeric(20,4) as gross_original,
      ed.amount::numeric(20,1) as gross_base,
      coalesce(ed.fx_rate,1)::numeric(20,10) as fx_rate,
      a.base_currency::character(3) as base_currency
    from public.expense_debts ed
    join public.expenses e on e.id = ed.expense_id
    join public.ledger_units lu on lu.id = e.ledger_unit_id
    join public.activities a on a.id = lu.activity_id
    where ed.activity_id = p_activity_id and not e.is_deleted and not lu.is_deleted and not a.is_deleted
  ),
  final_totals as (
    select f.activity_id, f.source_expense_id, f.from_participant_id,
           f.to_participant_id, sum(f.amount)::numeric(20,1) as base_amount
    from public.final_settlement_paths f
    join public.transfers t on t.id = f.transfer_id and t.activity_id = f.activity_id
    where f.activity_id = p_activity_id and not t.is_voided
      and f.component_type = 'settlement'
      and f.source_expense_id is not null
    group by f.activity_id, f.source_expense_id, f.from_participant_id, f.to_participant_id
  ),
  ordered_debts as (
    select r.*,
      coalesce(ft.base_amount,0)::numeric(20,1) as final_base_total,
      coalesce(sum(r.gross_base) over (
        partition by r.expense_id, r.debtor_participant_id, r.creditor_participant_id
        order by r.expense_debt_id
        rows between unbounded preceding and 1 preceding
      ),0)::numeric(20,1) as prior_gross_base
    from raw_debts r
    left join final_totals ft
      on ft.activity_id = r.activity_id
     and ft.source_expense_id = r.expense_id
     and ft.from_participant_id = r.debtor_participant_id
     and ft.to_participant_id = r.creditor_participant_id
  ),
  debt_rows as (
    select
      d.activity_id,
      d.debtor_participant_id,
      d.creditor_participant_id,
      d.currency,
      greatest(
        d.gross_original
        - coalesce((select sum(coalesce(ta.original_amount, ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id = d.expense_debt_id),0)
        - pg_catalog.round(coalesce((select sum(pu.amount) from public.prepayment_usages pu where pu.expense_debt_id = d.expense_debt_id),0) / nullif(d.fx_rate,0),4)
        - pg_catalog.round(least(d.gross_base, greatest(d.final_base_total - d.prior_gross_base,0)) / nullif(d.fx_rate,0),4),
        0::numeric
      )::numeric(20,4) as original_residual,
      greatest(
        d.gross_base
        - coalesce((select sum(coalesce(ta.base_amount, ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id = d.expense_debt_id),0)
        - case when d.currency = d.base_currency
               then coalesce((select sum(pu.amount) from public.prepayment_usages pu where pu.expense_debt_id = d.expense_debt_id),0)
               else 0 end
        - least(d.gross_base, greatest(d.final_base_total - d.prior_gross_base,0)),
        0::numeric
      )::numeric(20,1) as base_residual
    from ordered_debts d
  ),
  grouped as (
    select
      d.activity_id,
      least(d.debtor_participant_id, d.creditor_participant_id) as low_id,
      greatest(d.debtor_participant_id, d.creditor_participant_id) as high_id,
      d.currency,
      sum(case when d.debtor_participant_id < d.creditor_participant_id then d.original_residual else -d.original_residual end) as signed_original,
      sum(case when d.debtor_participant_id < d.creditor_participant_id then d.base_residual else -d.base_residual end) as signed_base,
      sum(case when d.debtor_participant_id < d.creditor_participant_id then d.original_residual else 0 end) as low_to_high_original,
      sum(case when d.debtor_participant_id < d.creditor_participant_id then d.base_residual else 0 end) as low_to_high_base,
      sum(case when d.debtor_participant_id > d.creditor_participant_id then d.original_residual else 0 end) as high_to_low_original,
      sum(case when d.debtor_participant_id > d.creditor_participant_id then d.base_residual else 0 end) as high_to_low_base
    from debt_rows d
    group by d.activity_id, least(d.debtor_participant_id, d.creditor_participant_id),
             greatest(d.debtor_participant_id, d.creditor_participant_id), d.currency
  ),
  positive as (
    select g.*,
      case when g.signed_original > 0 then g.signed_original else -g.signed_original end as net_original,
      case when g.signed_original > 0 then
        greatest(g.low_to_high_base - pg_catalog.round(
          least(g.low_to_high_original, g.high_to_low_original)
          * case when g.low_to_high_original > 0 then g.low_to_high_base / g.low_to_high_original else 0 end, 1), 0)
      else
        greatest(g.high_to_low_base - pg_catalog.round(
          least(g.low_to_high_original, g.high_to_low_original)
          * case when g.high_to_low_original > 0 then g.high_to_low_base / g.high_to_low_original else 0 end, 1), 0)
      end as net_base
    from grouped g
    where g.signed_original <> 0
  )
  select
    p.activity_id,
    case when p.signed_original > 0 then p.low_id else p.high_id end,
    case when p.signed_original > 0 then p.high_id else p.low_id end,
    pg_catalog.round(p.net_base, 1)::numeric(20,1),
    p.net_original::numeric(20,4),
    p.currency,
    pg_catalog.round(p.net_base, 1)::numeric(20,1)
  from positive p
  where p.net_original > 0;

  -- Existing prepayment and final-settlement projections are base-currency
  -- facts.  Their consumers still read `amount`; adding them here preserves
  -- that behavior without allowing them to create external-currency rows.
  -- Ordinary settlement is already represented by residual expense debts.
end;
$function$;

-- Candidate contract consumed by Android.  It is intentionally derived from
-- the projection and is independent of the currently enabled ECB currency
-- list, so old external debts remain payable after the activity toggle is off.
create or replace function public.list_settlement_options(p_activity_id uuid)
returns table(
  debtor_participant_id uuid,
  creditor_participant_id uuid,
  currency character(3),
  original_amount numeric(20,4),
  base_amount numeric(20,1),
  base_total numeric(20,1),
  financial_version bigint
)
language plpgsql
stable
security invoker
set search_path = ''
as $function$
begin
  if not exists (
    select 1 from public.activity_members am
    where am.activity_id = p_activity_id and am.user_id = (select auth.uid())
  ) then
    raise exception using errcode = '42501', message = 'caller is not an activity member';
  end if;
  return query
  select bd.debtor_participant_id, bd.creditor_participant_id,
         coalesce(bd.currency, a.base_currency)::character(3),
         coalesce(bd.original_amount, bd.amount)::numeric(20,4),
         coalesce(bd.base_amount, bd.amount)::numeric(20,1),
         sum(coalesce(bd.base_amount, bd.amount)) over (
           partition by bd.activity_id, bd.debtor_participant_id, bd.creditor_participant_id
         )::numeric(20,1),
         a.financial_version
  from public.bilateral_debts bd
  join public.activities a on a.id = bd.activity_id
  where bd.activity_id = p_activity_id and bd.amount > 0
  order by bd.debtor_participant_id, bd.creditor_participant_id, bd.currency;
end;
$function$;

-- The new implementation accepts currency and request_id.  A request_id is
-- replay-safe under the Activity lock; a conflicting payload is rejected.
create or replace function private.create_settlement_transfer_impl(
  p_activity_id uuid,
  p_from_participant_id uuid,
  p_to_participant_id uuid,
  p_amount numeric(20,4),
  p_currency character(3),
  p_occurred_at timestamptz,
  p_on_behalf_of_participant_id uuid,
  p_request_id uuid
)
returns table(transfer_id uuid, amount numeric(20,4), currency character(3), financial_version bigint)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_user_id uuid := (select auth.uid());
  v_base_currency character(3);
  v_currency character(3) := pg_catalog.upper(pg_catalog.btrim(p_currency));
  v_archived_at timestamptz;
  v_cap numeric(20,4);
  v_transfer_id uuid;
  v_existing record;
  v_financial_version bigint;
begin
  if v_user_id is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if p_amount is null or p_amount <= 0 then raise exception using errcode='22023',message='transfer amount must be positive'; end if;
  if p_from_participant_id is null or p_to_participant_id is null or p_from_participant_id = p_to_participant_id then raise exception using errcode='22023',message='transfer parties must be distinct'; end if;
  if p_occurred_at is null or v_currency is null or v_currency !~ '^[A-Z]{3}$' then raise exception using errcode='22023',message='invalid settlement transfer'; end if;

  perform private.lock_debt_projection_activity(p_activity_id);
  select a.base_currency, a.archived_at into v_base_currency, v_archived_at
  from public.activities a where a.id = p_activity_id and not a.is_deleted for update;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived_at is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if;
  if not exists (select 1 from public.activity_members am where am.activity_id=p_activity_id and am.user_id=v_user_id) then raise exception using errcode='42501',message='caller is not an activity member'; end if;

  if p_request_id is not null then
    select t.* into v_existing from public.transfers t where t.activity_id=p_activity_id and t.request_id=p_request_id for update;
    if found then
      if v_existing.from_participant_id <> p_from_participant_id or v_existing.to_participant_id <> p_to_participant_id
         or v_existing.amount <> p_amount or v_existing.currency <> v_currency
         or v_existing.type <> 'settlement'::public.transfer_type then
        raise exception using errcode='23505',message='settlement request id was already used with a different payload';
      end if;
      select a.financial_version into v_financial_version from public.activities a where a.id=p_activity_id;
      return query select v_existing.id, v_existing.amount, v_existing.currency, v_financial_version;
      return;
    end if;
  end if;

  -- Lock both participant rows in UUID order before reading the projection.
  perform 1 from public.participants p
   where p.activity_id=p_activity_id and p.id in(p_from_participant_id,p_to_participant_id) and not p.is_deleted
   order by p.id for update;
  if (select count(*) from public.participants p where p.activity_id=p_activity_id and p.id in(p_from_participant_id,p_to_participant_id) and not p.is_deleted) <> 2 then
    raise exception using errcode='P0002',message='transfer participant was not found';
  end if;

  -- Authorisation retains the established on-behalf semantics.
  perform private.authorize_phase5_actor(p_activity_id,p_from_participant_id,p_to_participant_id,p_on_behalf_of_participant_id);

  -- Projection rows are authoritative for the user-facing cap.  For the base
  -- currency all residual currency buckets are available; for an external
  -- currency only that original bucket is available.
  select coalesce(sum(
    case when v_currency = v_base_currency then coalesce(bd.base_amount,bd.amount)
         else coalesce(bd.original_amount,bd.amount) end
  ),0)::numeric(20,4)
    into v_cap
  from public.bilateral_debts bd
  where bd.activity_id=p_activity_id
    and bd.debtor_participant_id=p_from_participant_id
    and bd.creditor_participant_id=p_to_participant_id
    and (v_currency = v_base_currency or bd.currency = v_currency);
  if v_cap <= 0 or p_amount > v_cap then
    raise exception using errcode='23514',message='settlement exceeds current debt for currency';
  end if;

  insert into public.transfers(
    activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,recorded_by,on_behalf_of_participant_id,request_id
  ) values (
    p_activity_id,p_from_participant_id,p_to_participant_id,'settlement',p_amount,v_currency,p_occurred_at,v_user_id,p_on_behalf_of_participant_id,p_request_id
  ) returning id into v_transfer_id;
  insert into public.transfer_components(activity_id,transfer_id,component_type,amount)
    values(p_activity_id,v_transfer_id,'settlement',p_amount);
  perform private.assert_component_total(v_transfer_id);
  perform private.phase5_rebuild_after_transfer(p_activity_id);
  update public.activities a set financial_version=a.financial_version+1 where a.id=p_activity_id returning a.financial_version into v_financial_version;
  return query select v_transfer_id,p_amount,v_currency,v_financial_version;
end;
$function$;

-- Legacy private callers (prepayment/finalization and old clients) continue to
-- create a base-currency settlement without request-id semantics.
create or replace function private.create_settlement_transfer_impl(
  p_activity_id uuid,p_from_participant_id uuid,p_to_participant_id uuid,
  p_amount numeric(20,1),p_occurred_at timestamptz,p_on_behalf_of_participant_id uuid
)
returns table(transfer_id uuid, amount numeric(20,1), currency character(3), financial_version bigint)
language sql volatile security definer set search_path=''
as $function$
  select x.transfer_id, x.amount::numeric(20,1), x.currency, x.financial_version
  from private.create_settlement_transfer_impl(
    $1,$2,$3,$4,(select a.base_currency from public.activities a where a.id = $1),$5,$6,null::uuid
  ) x;
$function$;

create or replace function public.create_settlement_transfer(
  activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,4), currency character(3), occurred_at timestamptz,
  on_behalf_of_participant_id uuid, request_id uuid
)
returns table(transfer_id uuid, amount numeric(20,4), currency character(3), financial_version bigint)
language sql volatile security invoker set search_path=''
as $function$
  select * from private.create_settlement_transfer_impl($1,$2,$3,$4,$5,$6,$7,$8);
$function$;

-- Preserve the old public six-argument endpoint as a compatibility shim.
create or replace function public.create_settlement_transfer(
  activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,1), occurred_at timestamptz default pg_catalog.now(),
  on_behalf_of_participant_id uuid default null
)
returns table(transfer_id uuid, amount numeric(20,1), currency character(3), financial_version bigint)
language sql volatile security invoker set search_path=''
as $function$
  select x.transfer_id, x.amount::numeric(20,1), x.currency, x.financial_version
  from private.create_settlement_transfer_impl($1,$2,$3,$4,$5,$6) as x;
$function$;

revoke all on function private.create_settlement_transfer_impl(uuid,uuid,uuid,numeric(20,4),character(3),timestamptz,uuid,uuid) from public,anon,authenticated;
grant execute on function private.create_settlement_transfer_impl(uuid,uuid,uuid,numeric(20,4),character(3),timestamptz,uuid,uuid) to authenticated;
revoke all on function public.create_settlement_transfer(uuid,uuid,uuid,numeric(20,4),character(3),timestamptz,uuid,uuid) from public,anon,authenticated;
grant execute on function public.create_settlement_transfer(uuid,uuid,uuid,numeric(20,4),character(3),timestamptz,uuid,uuid) to authenticated;
revoke all on function public.list_settlement_options(uuid) from public,anon;
grant execute on function public.list_settlement_options(uuid) to authenticated;

-- Final Settlement remains a base-currency-only feature.  The multi-currency
-- bilateral projection stores one row per currency, so aggregate every pair
-- by its base_amount before running the existing flow decomposition.  This
-- preserves the old final-settlement graph semantics without making final
-- settlement eligible to choose an external currency.
create or replace function private.build_final_settlement_flow(p_activity_id uuid)
returns table(path_no integer, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,1), hops jsonb)
language plpgsql stable security definer set search_path = ''
as $function$
declare
  v_edge_from uuid[] := '{}'::uuid[]; v_edge_to uuid[] := '{}'::uuid[];
  v_edge_remaining numeric[] := '{}'::numeric[]; v_edge_count integer := 0;
  v_sources uuid[] := '{}'::uuid[]; v_source_remaining numeric[] := '{}'::numeric[];
  v_creditors uuid[] := '{}'::uuid[]; v_creditor_remaining numeric[] := '{}'::numeric[];
  v_queue_i integer;
  v_source_left numeric; v_match numeric; v_hop_no integer; v_path_no integer := 0;
  v_node uuid; v_target uuid; v_current_path jsonb; v_found_path jsonb; v_hops jsonb;
  v_queue_nodes uuid[]; v_queue_paths jsonb[]; v_visited uuid[];
  v_rec record; v_edge_path_i integer; v_edge_path_text text;
  v_uid uuid := (select auth.uid()); v_activity_type public.activity_type;
begin
  if v_uid is null then raise exception using errcode='28000', message='authentication is required'; end if;
  if not exists (select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=v_uid) then
    raise exception using errcode='42501', message='caller is not an activity member';
  end if;
  select a.type into v_activity_type from public.activities a where a.id=p_activity_id and not a.is_deleted;
  if not found then raise exception using errcode='P0002', message='activity was not found'; end if;
  if v_activity_type <> 'large'::public.activity_type then
    raise exception using errcode='23514', message='final settlement requires a large activity';
  end if;

  for v_rec in
    select b.debtor_participant_id, b.creditor_participant_id,
           sum(coalesce(b.base_amount,b.amount))::numeric(20,1) as amount
    from public.bilateral_debts b
    join public.participants dp on dp.activity_id=b.activity_id and dp.id=b.debtor_participant_id
    join public.participants cp on cp.activity_id=b.activity_id and cp.id=b.creditor_participant_id
    where b.activity_id=p_activity_id and coalesce(b.base_amount,b.amount)>0
      and not dp.is_deleted and not cp.is_deleted
    group by b.debtor_participant_id,b.creditor_participant_id,
             dp.participant_order,dp.id,cp.participant_order,cp.id
    order by dp.participant_order,dp.id,cp.participant_order,cp.id
  loop
    v_edge_count := v_edge_count + 1;
    v_edge_from := array_append(v_edge_from,v_rec.debtor_participant_id);
    v_edge_to := array_append(v_edge_to,v_rec.creditor_participant_id);
    v_edge_remaining := array_append(v_edge_remaining,v_rec.amount);
  end loop;

  for v_rec in
    with edges as (
      select b.debtor_participant_id, b.creditor_participant_id,
             sum(coalesce(b.base_amount,b.amount))::numeric(20,1) as amount
      from public.bilateral_debts b
      where b.activity_id=p_activity_id
      group by b.debtor_participant_id,b.creditor_participant_id
    )
    select p.id, sum(case when e.creditor_participant_id=p.id then e.amount else -e.amount end)::numeric(20,1) net_amount
    from public.participants p join edges e
      on e.debtor_participant_id=p.id or e.creditor_participant_id=p.id
    where p.activity_id=p_activity_id and not p.is_deleted
    group by p.id,p.participant_order
    having sum(case when e.creditor_participant_id=p.id then e.amount else -e.amount end) < 0
    order by p.participant_order,p.id
  loop
    v_sources := array_append(v_sources,v_rec.id);
    v_source_remaining := array_append(v_source_remaining,abs(v_rec.net_amount));
  end loop;
  for v_rec in
    with edges as (
      select b.debtor_participant_id, b.creditor_participant_id,
             sum(coalesce(b.base_amount,b.amount))::numeric(20,1) as amount
      from public.bilateral_debts b
      where b.activity_id=p_activity_id
      group by b.debtor_participant_id,b.creditor_participant_id
    )
    select p.id, sum(case when e.creditor_participant_id=p.id then e.amount else -e.amount end)::numeric(20,1) net_amount
    from public.participants p join edges e
      on e.debtor_participant_id=p.id or e.creditor_participant_id=p.id
    where p.activity_id=p_activity_id and not p.is_deleted
    group by p.id,p.participant_order
    having sum(case when e.creditor_participant_id=p.id then e.amount else -e.amount end) > 0
    order by p.participant_order,p.id
  loop
    v_creditors := array_append(v_creditors,v_rec.id);
    v_creditor_remaining := array_append(v_creditor_remaining,v_rec.net_amount);
  end loop;

  for v_source_i in 1..coalesce(array_length(v_sources,1),0) loop
    v_source_left := v_source_remaining[v_source_i];
    while v_source_left > 0 loop
      v_queue_nodes := array[v_sources[v_source_i]];
      v_queue_paths := array['[]'::jsonb];
      v_visited := array[v_sources[v_source_i]];
      v_queue_i := 1; v_target := null; v_found_path := null;
      while v_queue_i <= coalesce(array_length(v_queue_nodes,1),0) loop
        v_node := v_queue_nodes[v_queue_i];
        v_current_path := v_queue_paths[v_queue_i];
        v_queue_i := v_queue_i + 1;
        for v_creditor_i in 1..coalesce(array_length(v_creditors,1),0) loop
          if v_creditors[v_creditor_i]=v_node and v_creditor_remaining[v_creditor_i]>0 and jsonb_array_length(v_current_path)>0 then
            v_target := v_node; v_found_path := v_current_path; exit;
          end if;
        end loop;
        exit when v_target is not null;
        for v_edge_i in 1..v_edge_count loop
          if v_edge_from[v_edge_i]=v_node and v_edge_remaining[v_edge_i]>0
             and not (v_edge_to[v_edge_i]=any(v_visited)) then
            v_visited := array_append(v_visited,v_edge_to[v_edge_i]);
            v_queue_nodes := array_append(v_queue_nodes,v_edge_to[v_edge_i]);
            v_queue_paths := array_append(v_queue_paths,v_current_path || to_jsonb(v_edge_i));
          end if;
        end loop;
      end loop;
      if v_target is null then
        raise exception using errcode='P0001', message='final settlement flow cannot decompose directed debt graph';
      end if;
      v_match := v_source_left;
      for v_edge_path_text in select jsonb_array_elements_text(v_found_path) loop
        v_edge_path_i := v_edge_path_text::integer;
        v_match := least(v_match,v_edge_remaining[v_edge_path_i]);
      end loop;
      for v_creditor_i in 1..coalesce(array_length(v_creditors,1),0) loop
        if v_creditors[v_creditor_i]=v_target then
          v_match := least(v_match,v_creditor_remaining[v_creditor_i]); exit;
        end if;
      end loop;
      if v_match <= 0 then raise exception using errcode='P0001', message='final settlement flow has zero residual capacity'; end if;
      v_path_no := v_path_no + 1; v_hops := '[]'::jsonb; v_hop_no := 0;
      for v_edge_path_text in select jsonb_array_elements_text(v_found_path) loop
        v_edge_path_i := v_edge_path_text::integer; v_hop_no := v_hop_no + 1;
        v_hops := v_hops || jsonb_build_array(jsonb_build_object(
          'hop_no',v_hop_no,'from_participant_id',v_edge_from[v_edge_path_i],
          'to_participant_id',v_edge_to[v_edge_path_i],'amount',v_match));
        v_edge_remaining[v_edge_path_i] := v_edge_remaining[v_edge_path_i] - v_match;
      end loop;
      v_source_left := v_source_left - v_match; v_source_remaining[v_source_i] := v_source_left;
      for v_creditor_i in 1..coalesce(array_length(v_creditors,1),0) loop
        if v_creditors[v_creditor_i]=v_target then
          v_creditor_remaining[v_creditor_i] := v_creditor_remaining[v_creditor_i] - v_match; exit;
        end if;
      end loop;
      return query select v_path_no,v_sources[v_source_i],v_target,v_match::numeric(20,1),v_hops;
    end loop;
  end loop;
  for v_source_i in 1..coalesce(array_length(v_source_remaining,1),0) loop
    if v_source_remaining[v_source_i]<>0 then raise exception using errcode='P0001', message='final settlement source flow did not conserve'; end if;
  end loop;
  for v_creditor_i in 1..coalesce(array_length(v_creditor_remaining,1),0) loop
    if v_creditor_remaining[v_creditor_i]<>0 then raise exception using errcode='P0001', message='final settlement creditor flow did not conserve'; end if;
  end loop;
end;
$function$;

-- Restore is deliberately no longer part of the product contract.  Keep the
-- old object for migration compatibility, but remove every client role's
-- execute privilege so a deleted Expense cannot be resurrected.
revoke all on function public.restore_expense(uuid), private.restore_expense_impl(uuid) from public,anon,authenticated;

-- Recreate all projection rows once under the new currency contract.  Existing
-- ordinary transfers are base-currency facts, so their original/base values
-- are backfilled deterministically by the allocation rebuild.
do $backfill$
declare
  v_activity_id uuid;
begin
  for v_activity_id in select id from public.activities order by id loop
    perform private.rebuild_activity_debt_projection(v_activity_id);
  end loop;
end;
$backfill$;

commit;
