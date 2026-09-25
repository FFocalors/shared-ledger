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
    ),
    ordered_pairs as (
      select
        p.*,
        row_number() over (
          order by p.debtor_order, p.debtor_participant_id,
                   p.creditor_order, p.creditor_participant_id
        ) as pair_no,
        count(*) over () as pair_count
      from pairs p
    ),
    legacy as (
      select
        p.*,
        pg_catalog.round(p.original_amount * v_original_fx, 1)::numeric(20,1) as rounded_base,
        coalesce(pg_catalog.sum(
          pg_catalog.round(p.original_amount * v_original_fx, 1)
        ) filter (where p.pair_no < p.pair_count) over (), 0)::numeric(20,1) as prelast_base
      from ordered_pairs p
    ),
    fallback_basis as (
      select
        p.*,
        (p.original_amount * 10000)::numeric as weight,
        pg_catalog.sum(p.original_amount * 10000) over ()::numeric as total_weight
      from legacy p
    ),
    fallback_quotas as (
      select
        p.*,
        pg_catalog.floor((v_base_debt_total * 10) * p.weight / p.total_weight) as floor_units,
        pg_catalog.mod((v_base_debt_total * 10) * p.weight, p.total_weight) as remainder_numerator
      from fallback_basis p
    ),
    ranked_quotas as (
      select
        p.*,
        row_number() over (order by p.remainder_numerator desc, p.pair_no) as remainder_rank,
        pg_catalog.sum(p.floor_units) over () as total_floor_units
      from fallback_quotas p
    )
    select
      p.*,
      case
        when p.prelast_base <= v_base_debt_total then
          case when p.pair_no = p.pair_count
            then v_base_debt_total - p.prelast_base
            else p.rounded_base
          end
        else
          -- Allocate only the overflowing case in whole 0.1 base units.
          -- Pair order breaks equal-remainder ties reproducibly.
          (p.floor_units + case
            when p.remainder_rank <= v_base_debt_total * 10 - p.total_floor_units then 1
            else 0
          end) / 10
      end::numeric(20,1) as allocated_base
    from ranked_quotas p
    order by p.pair_no
  loop
    v_base_amount := v_pair.allocated_base;
    if v_base_amount < 0 then
      raise exception using errcode = '23514',
        message = 'expense base debt allocation cannot be negative';
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
