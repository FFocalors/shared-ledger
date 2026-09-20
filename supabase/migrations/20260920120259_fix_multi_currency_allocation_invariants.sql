begin;

-- Preserve an explicitly reconstructed original-currency amount on inserts.
-- The previous trigger always derived it from rounded base debt, which could
-- reintroduce a wrong pair amount immediately after the original-currency
-- rebuild below.
create or replace function private.populate_expense_debt_currency()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_currency character(3);
  v_fx numeric(20,10);
begin
  select e.original_currency, e.fx_rate
    into v_currency, v_fx
  from public.expenses e
  where e.id = new.expense_id;

  if tg_op = 'INSERT' then
    new.original_amount := coalesce(
      new.original_amount,
      pg_catalog.round(new.amount / nullif(v_fx, 0), 4)
    );
  elsif old.expense_id is distinct from new.expense_id
     or new.original_amount is null then
    new.original_amount := pg_catalog.round(new.amount / nullif(v_fx, 0), 4);
  end if;
  new.original_currency := v_currency;
  new.fx_rate := v_fx;
  return new;
end;
$function$;

-- The original participant nets define the debt topology.  Base-currency
-- amounts are then assigned to those same rows, with the stable final row
-- absorbing the one-decimal rounding tail.  This prevents base-only matching
-- from creating an original-currency pair that never existed.
create or replace function private.rebuild_expense_debts_locked(
  p_expense_id uuid,
  p_activity_id uuid
)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_actual_activity_id uuid;
  v_ledger_unit_id uuid;
  v_is_effective boolean;
  v_original_currency character(3);
  v_original_fx numeric(20,10);
  v_original_net_total numeric(20,4);
  v_base_debt_total numeric(20,1);
  v_base_allocated numeric(20,1) := 0;
  v_base_amount numeric(20,1);
  v_pair record;
begin
  select
    lu.activity_id,
    lu.id,
    not e.is_deleted and not lu.is_deleted and not a.is_deleted,
    e.original_currency,
    e.fx_rate
  into
    v_actual_activity_id,
    v_ledger_unit_id,
    v_is_effective,
    v_original_currency,
    v_original_fx
  from public.expenses e
  join public.ledger_units lu on lu.id = e.ledger_unit_id
  join public.activities a on a.id = lu.activity_id
  where e.id = p_expense_id;

  if not found then
    raise exception using errcode = 'P0002', message = 'expense was not found for debt rebuild';
  end if;
  if v_actual_activity_id is distinct from p_activity_id then
    raise exception using errcode = '23514', message = 'expense debt activity mismatch';
  end if;

  delete from public.expense_debts where expense_id = p_expense_id;
  if not v_is_effective then
    return;
  end if;
  select
    coalesce(sum(coalesce(pay.paid, 0) - coalesce(split.owed, 0)), 0)::numeric(20,4),
    coalesce(sum(greatest(
      coalesce(pay.paid_base, 0) - coalesce(split.owed_base, 0), 0
    )), 0)::numeric(20,1)
    into v_original_net_total, v_base_debt_total
  from public.participants p
  left join (
    select participant_id, pg_catalog.sum(amount) as paid,
           pg_catalog.sum(base_amount) as paid_base
    from public.payments
    where expense_id = p_expense_id
    group by participant_id
  ) pay on pay.participant_id = p.id
  left join (
    select participant_id, pg_catalog.sum(amount) as owed,
           pg_catalog.sum(base_amount) as owed_base
    from public.splits
    where expense_id = p_expense_id
    group by participant_id
  ) split on split.participant_id = p.id
  where p.activity_id = p_activity_id
    and (pay.participant_id is not null or split.participant_id is not null);

  if v_original_net_total <> 0 then
    raise exception using errcode = '23514',
      message = 'expense participant original nets do not conserve';
  end if;
  if v_base_debt_total = 0 then
    raise exception using errcode = '23514',
      message = 'expense debt base amount is zero at one-decimal precision';
  end if;

  for v_pair in
    with participant_nets as (
      select
        p.id as participant_id,
        p.participant_order,
        (
          coalesce(pay.paid, 0) - coalesce(split.owed, 0)
        )::numeric(20,4) as net_original
      from public.participants p
      left join (
        select participant_id, pg_catalog.sum(amount) as paid
        from public.payments
        where expense_id = p_expense_id
        group by participant_id
      ) pay on pay.participant_id = p.id
      left join (
        select participant_id, pg_catalog.sum(amount) as owed
        from public.splits
        where expense_id = p_expense_id
        group by participant_id
      ) split on split.participant_id = p.id
      where p.activity_id = p_activity_id
        and (pay.participant_id is not null or split.participant_id is not null)
    ),
    creditors as (
      select participant_id, participant_order, net_original
      from participant_nets
      where net_original > 0
    ),
    debtors as (
      select participant_id, participant_order, -net_original as owed_original
      from participant_nets
      where net_original < 0
    ),
    creditor_ranges as (
      select
        participant_id,
        participant_order,
        coalesce(pg_catalog.sum(net_original) over (
          order by participant_order, participant_id
          rows between unbounded preceding and 1 preceding
        ), 0)::numeric(20,4) as range_start,
        pg_catalog.sum(net_original) over (
          order by participant_order, participant_id
          rows between unbounded preceding and current row
        )::numeric(20,4) as range_end
      from creditors
    ),
    debtor_ranges as (
      select
        participant_id,
        participant_order,
        coalesce(pg_catalog.sum(owed_original) over (
          order by participant_order, participant_id
          rows between unbounded preceding and 1 preceding
        ), 0)::numeric(20,4) as range_start,
        pg_catalog.sum(owed_original) over (
          order by participant_order, participant_id
          rows between unbounded preceding and current row
        )::numeric(20,4) as range_end
      from debtors
    ),
    pairs as (
      select
        d.participant_id as debtor_participant_id,
        d.participant_order as debtor_order,
        c.participant_id as creditor_participant_id,
        c.participant_order as creditor_order,
        (
          least(c.range_end, d.range_end)
          - greatest(c.range_start, d.range_start)
        )::numeric(20,4) as original_amount
      from debtor_ranges d
      cross join creditor_ranges c
      where least(c.range_end, d.range_end) > greatest(c.range_start, d.range_start)
    )
    select
      p.*,
      row_number() over (
        order by p.debtor_order, p.debtor_participant_id,
                 p.creditor_order, p.creditor_participant_id
      ) as pair_no,
      count(*) over () as pair_count
    from pairs p
    order by pair_no
  loop
    v_base_amount := pg_catalog.round(v_pair.original_amount * v_original_fx, 1)::numeric(20,1);
    if v_pair.pair_no = v_pair.pair_count then
      v_base_amount := v_base_debt_total - v_base_allocated;
    end if;
    if v_base_amount <= 0 then
      raise exception using errcode = '23514',
        message = 'expense base amount cannot represent every original debt row';
    end if;

    insert into public.expense_debts(
      activity_id, ledger_unit_id, expense_id,
      debtor_participant_id, creditor_participant_id, amount,
      original_amount, original_currency, fx_rate
    ) values (
      p_activity_id, v_ledger_unit_id, p_expense_id,
      v_pair.debtor_participant_id, v_pair.creditor_participant_id,
      v_base_amount, v_pair.original_amount, v_original_currency, v_original_fx
    );
    v_base_allocated := v_base_allocated + v_base_amount;
  end loop;

  if v_base_allocated <> v_base_debt_total then
    raise exception using errcode = '23514',
      message = 'expense debt base allocation did not conserve base amount';
  end if;
end;
$function$;

-- Zero base-unit allocations are meaningful for tiny external-currency
-- payments: the original amount still reduces the debt, while the final
-- allocation absorbs the accumulated one-decimal base tail.
alter table public.transfer_allocations
  drop constraint if exists transfer_allocations_amount_check;
alter table public.transfer_allocations
  add constraint transfer_allocations_amount_nonnegative check (amount >= 0);
alter table public.transfer_allocations
  add constraint transfer_allocations_base_amount_nonnegative
    check (base_amount is null or base_amount >= 0);
alter table public.transfer_allocations
  add constraint transfer_allocations_original_amount_positive
    check (original_amount is null or original_amount > 0);

alter table public.bilateral_debts
  drop constraint if exists bilateral_debts_amount_check;
alter table public.bilateral_debts
  add constraint bilateral_debts_amount_nonnegative check (amount >= 0);

-- Stable FIFO allocation is also the source of truth for the base residual
-- exposed by bilateral_debts.  A successful ordinary settlement must consume
-- every requested original/base unit; historical overpayment aborts the
-- rebuild transaction instead of being silently discarded.
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
            - pg_catalog.round(r.prepaid_base / nullif(r.debt_fx, 0), 4),
          0::numeric
        )::numeric(20,4) as available_original,
        greatest(
          r.debt_base
            - pg_catalog.round(r.cancelled_original * r.debt_fx, 1)
            - r.allocated_base - r.prepaid_base,
          0::numeric
        )::numeric(20,1) as available_base
      from residual r
      where r.debt_currency = v_transfer.currency
         or v_transfer.currency = (
           select base_currency from public.activities where id = p_activity_id
         )
      order by r.occurred_at, r.created_at, r.expense_id, r.id
    loop
      exit when v_remaining <= 0;
      if v_transfer.currency = (
        select base_currency from public.activities where id = p_activity_id
      ) then
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
            v_allocate_base := pg_catalog.round(
              v_allocate_original * v_debt.debt_fx, 1
            )::numeric(20,1);
          end if;
        else
          continue;
        end if;
      end if;

      if v_allocate_original > 0 then
        insert into public.transfer_allocations(
          activity_id, transfer_id, settlement_component_id, expense_debt_id,
          amount, original_amount, base_amount
        ) values (
          p_activity_id, v_transfer.id, v_transfer.component_id, v_debt.id,
          v_allocate_base, v_allocate_original, v_allocate_base
        );
        v_remaining := v_remaining - case
          when v_transfer.currency = (
            select base_currency from public.activities where id = p_activity_id
          ) then v_allocate_base else v_allocate_original end;
      end if;
    end loop;

    if v_remaining > 0 then
      raise exception using errcode = '23514',
        message = pg_catalog.format(
          'settlement transfer %s has %s unallocated %s',
          v_transfer.id, v_remaining, v_transfer.currency
        );
    end if;
  end loop;
end;
$function$;

-- Bilateral rows now subtract the same original-unit FIFO reverse cancellation
-- and the same per-debt base residual that allocations use.  No weighted
-- average of reverse FX snapshots is used for the user-facing cap.
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
      coalesce(ed.fx_rate, 1)::numeric(20,10) as fx_rate,
      a.base_currency::character(3) as base_currency,
      e.occurred_at,
      e.created_at,
      e.id as expense_id_order
    from public.expense_debts ed
    join public.expenses e on e.id = ed.expense_id
    join public.ledger_units lu on lu.id = e.ledger_unit_id
    join public.activities a on a.id = lu.activity_id
    where ed.activity_id = p_activity_id
      and not e.is_deleted and not lu.is_deleted and not a.is_deleted
  ),
  directional as (
    select
      r.*,
      coalesce(sum(r.gross_original) over (
        partition by r.debtor_participant_id, r.creditor_participant_id, r.currency
        order by r.occurred_at, r.created_at, r.expense_id_order, r.expense_debt_id
        rows between unbounded preceding and 1 preceding
      ), 0::numeric) as prior_original,
      coalesce((
        select sum(reverse_r.gross_original)
        from raw_debts reverse_r
        where reverse_r.debtor_participant_id = r.creditor_participant_id
          and reverse_r.creditor_participant_id = r.debtor_participant_id
          and reverse_r.currency = r.currency
      ), 0::numeric) as reverse_original
    from raw_debts r
  ),
  cancelled as (
    select d.*,
      least(d.gross_original,
        greatest(d.reverse_original - d.prior_original, 0::numeric)
      )::numeric(20,4) as cancelled_original
    from directional d
  ),
  final_totals as (
    select f.activity_id, f.source_expense_id, f.from_participant_id,
           f.to_participant_id, sum(f.amount)::numeric(20,1) as final_base_total
    from public.final_settlement_paths f
    join public.transfers t on t.id = f.transfer_id and t.activity_id = f.activity_id
    where f.activity_id = p_activity_id and not t.is_voided
      and f.component_type = 'settlement'
      and f.source_expense_id is not null
    group by f.activity_id, f.source_expense_id, f.from_participant_id, f.to_participant_id
  ),
  ordered_debts as (
    select c.*,
      coalesce(ft.final_base_total, 0)::numeric(20,1) as final_base_total,
      coalesce(sum(c.gross_base) over (
        partition by c.expense_id, c.debtor_participant_id, c.creditor_participant_id
        order by c.expense_debt_id
        rows between unbounded preceding and 1 preceding
      ), 0)::numeric(20,1) as prior_gross_base
    from cancelled c
    left join final_totals ft
      on ft.activity_id = c.activity_id
     and ft.source_expense_id = c.expense_id
     and ft.from_participant_id = c.debtor_participant_id
     and ft.to_participant_id = c.creditor_participant_id
  ),
  debt_rows as (
    select
      d.activity_id,
      d.debtor_participant_id,
      d.creditor_participant_id,
      d.currency,
      greatest(
        d.gross_original - d.cancelled_original
          - coalesce((select sum(coalesce(ta.original_amount, ta.amount))
                      from public.transfer_allocations ta
                      where ta.expense_debt_id = d.expense_debt_id), 0)
          - pg_catalog.round(
              coalesce((select sum(pu.amount)
                        from public.prepayment_usages pu
                        where pu.expense_debt_id = d.expense_debt_id), 0)
              / nullif(d.fx_rate, 0), 4
            )
          - pg_catalog.round(
              least(d.gross_base,
                    greatest(d.final_base_total - d.prior_gross_base, 0))
              / nullif(d.fx_rate, 0), 4
            ),
        0::numeric
      )::numeric(20,4) as original_residual,
      greatest(
        d.gross_base
          - pg_catalog.round(d.cancelled_original * d.fx_rate, 1)
          - coalesce((select sum(coalesce(ta.base_amount, ta.amount))
                      from public.transfer_allocations ta
                      where ta.expense_debt_id = d.expense_debt_id), 0)
          - coalesce((select sum(pu.amount)
                      from public.prepayment_usages pu
                      where pu.expense_debt_id = d.expense_debt_id), 0)
          - least(d.gross_base,
                  greatest(d.final_base_total - d.prior_gross_base, 0)),
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
      sum(case when d.debtor_participant_id < d.creditor_participant_id
               then d.original_residual else -d.original_residual end) as signed_original,
      sum(case when d.debtor_participant_id < d.creditor_participant_id
               then d.base_residual else -d.base_residual end) as signed_base,
      sum(case when d.debtor_participant_id < d.creditor_participant_id
               then d.base_residual else 0 end) as low_to_high_base,
      sum(case when d.debtor_participant_id > d.creditor_participant_id
               then d.base_residual else 0 end) as high_to_low_base
    from debt_rows d
    group by d.activity_id,
      least(d.debtor_participant_id, d.creditor_participant_id),
      greatest(d.debtor_participant_id, d.creditor_participant_id),
      d.currency
  ),
  positive as (
    select
      g.*,
      abs(g.signed_original)::numeric(20,4) as net_original,
      case when g.signed_original > 0
        then g.low_to_high_base else g.high_to_low_base end::numeric(20,1) as net_base
    from grouped g
    where g.signed_original <> 0
  )
  select
    p.activity_id,
    case when p.signed_original > 0 then p.low_id else p.high_id end,
    case when p.signed_original > 0 then p.high_id else p.low_id end,
    greatest(p.net_base, 0)::numeric(20,1),
    p.net_original,
    p.currency,
    greatest(p.net_base, 0)::numeric(20,1)
  from positive p
  where p.net_original > 0;
end;
$function$;

-- Expose zero-base residual rows for external-currency settlement.  The
-- original amount, not the rounded base amount, is the existence predicate.
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
  where bd.activity_id = p_activity_id
    and coalesce(bd.original_amount, bd.amount) > 0
  order by bd.debtor_participant_id, bd.creditor_participant_id, bd.currency;
end;
$function$;

-- Reject fractional base-currency transfer facts because the projection is
-- stored in one-decimal base units.  External currencies retain four decimals.
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
  v_archived_at timestamptz;
  v_currency character(3) := pg_catalog.upper(pg_catalog.btrim(p_currency));
  v_cap numeric(20,4);
  v_transfer_id uuid;
  v_existing record;
  v_financial_version bigint;
begin
  if v_user_id is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if p_amount is null or p_amount <= 0 then raise exception using errcode='22023',message='transfer amount must be positive'; end if;
  if p_from_participant_id is null or p_to_participant_id is null
     or p_from_participant_id = p_to_participant_id then
    raise exception using errcode='22023',message='transfer parties must be distinct';
  end if;
  if p_occurred_at is null or v_currency is null or v_currency !~ '^[A-Z]{3}$' then
    raise exception using errcode='22023',message='invalid settlement transfer';
  end if;

  perform private.lock_debt_projection_activity(p_activity_id);
  select a.base_currency, a.archived_at into v_base_currency, v_archived_at
  from public.activities a where a.id = p_activity_id and not a.is_deleted for update;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived_at is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if;
  if v_currency = v_base_currency and p_amount <> pg_catalog.round(p_amount, 1) then
    raise exception using errcode='22023',message='base-currency transfer amount must have one decimal place';
  end if;
  if not exists (
    select 1 from public.activity_members am
    where am.activity_id=p_activity_id and am.user_id=v_user_id
  ) then raise exception using errcode='42501',message='caller is not an activity member'; end if;

  if p_request_id is not null then
    select t.* into v_existing
    from public.transfers t
    where t.activity_id=p_activity_id and t.request_id=p_request_id
    for update;
    if found then
      if v_existing.from_participant_id <> p_from_participant_id
         or v_existing.to_participant_id <> p_to_participant_id
         or v_existing.amount <> p_amount
         or v_existing.currency <> v_currency
         or v_existing.occurred_at is distinct from p_occurred_at
         or v_existing.on_behalf_of_participant_id is distinct from p_on_behalf_of_participant_id
         or v_existing.type <> 'settlement'::public.transfer_type then
        raise exception using errcode='23505',message='settlement request id was already used with a different payload';
      end if;
      select a.financial_version into v_financial_version
      from public.activities a where a.id=p_activity_id;
      return query select v_existing.id, v_existing.amount, v_existing.currency, v_financial_version;
      return;
    end if;
  end if;

  perform 1 from public.participants p
  where p.activity_id=p_activity_id
    and p.id in(p_from_participant_id,p_to_participant_id)
    and not p.is_deleted
  order by p.id for update;
  if (select count(*) from public.participants p
      where p.activity_id=p_activity_id and p.id in(p_from_participant_id,p_to_participant_id)
        and not p.is_deleted) <> 2 then
    raise exception using errcode='P0002',message='transfer participant was not found';
  end if;

  perform private.authorize_phase5_actor(
    p_activity_id,p_from_participant_id,p_to_participant_id,p_on_behalf_of_participant_id
  );

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
    activity_id,from_participant_id,to_participant_id,type,amount,currency,
    occurred_at,recorded_by,on_behalf_of_participant_id,request_id
  ) values (
    p_activity_id,p_from_participant_id,p_to_participant_id,'settlement',p_amount,v_currency,
    p_occurred_at,v_user_id,p_on_behalf_of_participant_id,p_request_id
  ) returning id into v_transfer_id;
  insert into public.transfer_components(activity_id,transfer_id,component_type,amount)
    values(p_activity_id,v_transfer_id,'settlement',p_amount);
  perform private.assert_component_total(v_transfer_id);
  perform private.phase5_rebuild_after_transfer(p_activity_id);
  update public.activities a set financial_version=a.financial_version+1
    where a.id=p_activity_id returning a.financial_version into v_financial_version;
  return query select v_transfer_id,p_amount,v_currency,v_financial_version;
end;
$function$;

revoke all on function private.rebuild_expense_debts_locked(uuid,uuid),
  private.rebuild_transfer_allocations_locked(uuid),
  private.rebuild_bilateral_debts_locked(uuid)
  from public, anon, authenticated;

-- Rebuild projections from source facts.  A historical overpayment now aborts
-- this migration with the transfer id rather than being silently truncated.
do $backfill$
declare
  v_activity_id uuid;
begin
  for v_activity_id in
    select id from public.activities where not is_deleted order by id
  loop
    perform private.rebuild_activity_debt_projection(v_activity_id);
  end loop;
end;
$backfill$;

commit;
