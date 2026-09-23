begin;

-- Finalize financial history semantics using a forward-only migration.

begin;


-- Replaced definition: private.resolve_expense_fx_snapshot.
create or replace function private.resolve_expense_fx_snapshot(
  p_ledger_unit_id uuid,
  p_original_currency character(3),
  p_original_expense_id uuid default null,
  p_existing_expense_id uuid default null
)
returns table(fx_rate numeric(20,10), fx_rate_source text, fx_rate_observed_at timestamptz)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_activity_id uuid;
  v_base_currency character(3);
  v_multi_currency_enabled boolean;
  v_currency character(3) := pg_catalog.upper(pg_catalog.btrim(p_original_currency));
  v_existing_activity_id uuid;
  v_existing_currency character(3);
  v_rate numeric(20,10);
  v_source text;
  v_observed_at timestamptz;
begin
  select lu.activity_id, a.base_currency, a.multi_currency_enabled
    into v_activity_id, v_base_currency, v_multi_currency_enabled
  from public.ledger_units as lu
  join public.activities as a on a.id = lu.activity_id
  where lu.id = p_ledger_unit_id and not lu.is_deleted and not a.is_deleted;
  if not found then
    raise exception using errcode = '42501', message = 'ledger unit is not available';
  end if;
  if not exists (
    select 1 from public.activity_members as am
    where am.activity_id = v_activity_id and am.user_id = (select auth.uid())
  ) then
    raise exception using errcode = '42501', message = 'caller is not an activity member';
  end if;
  if v_currency is null or v_currency !~ '^[A-Z]{3}$' then
    raise exception using errcode = '22023', message = 'original currency must be three uppercase letters';
  end if;

  -- FX snapshot resolution takes row locks and participates in the same
  -- Activity serialization order as the expense write that follows it.
  perform private.lock_debt_projection_activity(v_activity_id);

  if p_existing_expense_id is not null then
    select lu.activity_id into v_existing_activity_id
    from public.expenses e
    join public.ledger_units lu on lu.id=e.ledger_unit_id
    where e.id=p_existing_expense_id and not e.is_deleted and not lu.is_deleted;
    if not found or v_existing_activity_id is distinct from v_activity_id then
      raise exception using errcode = '22023', message = 'expense is not active in this activity';
    end if;
  end if;

  -- A linked refund inherits the complete immutable snapshot of its original.
  if p_original_expense_id is not null then
    select e.original_currency, e.fx_rate, e.fx_rate_source, e.fx_rate_observed_at
      into v_existing_currency, v_rate, v_source, v_observed_at
    from public.expenses as e
    join public.ledger_units as lu on lu.id = e.ledger_unit_id
    join public.activities as a on a.id = lu.activity_id
    where e.id = p_original_expense_id
      and lu.activity_id = v_activity_id
      and not e.is_deleted and not lu.is_deleted and not a.is_deleted
    for share;
    if not found then
      raise exception using errcode = '22023', message = 'refund reference is not an active expense in this activity';
    end if;
    if v_existing_currency <> v_currency then
      raise exception using errcode = '22023', message = 'linked refund currency must match original expense';
    end if;
    return query select v_rate, v_source, v_observed_at;
    return;
  end if;

  -- Editing without changing currency keeps the original snapshot, including
  -- a legacy manual snapshot and an already observed ECB date.
  if p_existing_expense_id is not null then
    select e.original_currency, e.fx_rate, e.fx_rate_source, e.fx_rate_observed_at
      into v_existing_currency, v_rate, v_source, v_observed_at
    from public.expenses as e
    where e.id = p_existing_expense_id and not e.is_deleted
    for share;
    if not found then
      raise exception using errcode = '22023', message = 'expense is not active';
    end if;
    if v_existing_currency = v_currency then
      return query select v_rate, v_source, v_observed_at;
      return;
    end if;
  end if;

  if v_currency = v_base_currency then
    return query select 1::numeric(20,10), 'same_currency'::text, null::timestamptz;
    return;
  end if;
  if not v_multi_currency_enabled then
    raise exception using errcode = '22023', message = 'foreign currency is disabled for this activity';
  end if;
  select c.rate, c.source, c.observed_at
    into v_rate, v_source, v_observed_at
  from public.exchange_rate_cache as c
  where c.base_currency = v_base_currency and c.quote_currency = v_currency
    and c.source = 'ECB_REFERENCE';
  if not found then
    raise exception using errcode = '22023', message = 'no exchange rate cache available';
  end if;
  -- An old successful cache is still a usable server snapshot.  The observed
  -- date is returned so Android can warn and offer a refresh; only a missing
  -- cache blocks an external-currency write.
  return query select v_rate, v_source, v_observed_at;
end;
$function$;


-- Keep the foreign-currency switch focused on new exposure. A linked refund
-- against an existing foreign Expense is historical settlement activity: it
-- may pass the switch only after the source is locked and its currency/FX
-- snapshot are verified. The sibling migration adds the authoritative
-- linked-refund history, amount-cap, and complete snapshot triggers.
create or replace function private.create_expense_impl(
  p_ledger_unit_id uuid,
  p_title text,
  p_original_amount numeric(20,4),
  p_original_currency character(3),
  p_fx_rate numeric(20,10),
  p_split_method public.expense_split_method,
  p_payments jsonb,
  p_manual_splits jsonb,
  p_aa_participant_ids uuid[],
  p_occurred_at timestamptz,
  p_note text,
  p_original_expense_id uuid
)
returns table(expense_id uuid, base_amount numeric(20,1), version bigint)
language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_user_id uuid := (select auth.uid());
  v_activity_id uuid;
  v_base_currency character(3);
  v_multi_currency_enabled boolean;
  v_title text;
  v_original_currency character(3);
  v_parent_currency character(3);
  v_parent_amount numeric(20,4);
  v_parent_fx_rate numeric(20,10);
  v_base_amount numeric(20,1);
  v_expense_id uuid;
  v_version bigint;
begin
  if v_user_id is null then
    raise exception using errcode='28000',message='authentication is required';
  end if;
  v_title:=pg_catalog.btrim(p_title);
  if v_title is null or pg_catalog.length(v_title)=0 then
    raise exception using errcode='22023',message='expense title is required';
  end if;
  if p_original_amount is null or p_original_amount=0 then
    raise exception using errcode='22023',message='original amount must be non-zero';
  end if;
  if p_original_currency is null then
    raise exception using errcode='22023',message='original currency is required';
  end if;
  v_original_currency:=pg_catalog.upper(pg_catalog.btrim(p_original_currency));
  if v_original_currency is null or v_original_currency !~ '^[A-Z]{3}$' then
    raise exception using errcode='22023',message='original currency must be three uppercase letters';
  end if;
  if p_fx_rate is null or p_fx_rate<=0 then
    raise exception using errcode='22023',message='FX rate must be positive';
  end if;
  if p_split_method is null or p_occurred_at is null then
    raise exception using errcode='22023',message='split method and occurred_at are required';
  end if;

  select lu.activity_id,a.base_currency,a.multi_currency_enabled
    into v_activity_id,v_base_currency,v_multi_currency_enabled
  from public.ledger_units lu join public.activities a on a.id=lu.activity_id
  where lu.id=p_ledger_unit_id and not lu.is_deleted and not a.is_deleted;
  if not found then
    raise exception using errcode='42501',message='ledger unit is not available';
  end if;
  if not exists(select 1 from public.activity_members am
      where am.activity_id=v_activity_id and am.user_id=v_user_id) then
    raise exception using errcode='42501',message='caller is not an activity member';
  end if;

  if v_original_currency=v_base_currency then
    if p_fx_rate<>1 then
      raise exception using errcode='22023',message='base-currency expenses must use FX rate 1';
    end if;
  elsif not v_multi_currency_enabled and p_original_expense_id is null then
    raise exception using errcode='22023',message='foreign currency is disabled for this activity';
  end if;

  if p_original_expense_id is not null then
    select e.original_currency,e.original_amount,e.fx_rate
      into v_parent_currency,v_parent_amount,v_parent_fx_rate
    from public.expenses e
    join public.ledger_units lu on lu.id=e.ledger_unit_id
    join public.activities a on a.id=lu.activity_id
    where e.id=p_original_expense_id and lu.activity_id=v_activity_id
      and not e.is_deleted and not lu.is_deleted and not a.is_deleted
    for key share of e;
    if not found or v_parent_amount is null or v_parent_amount<=0 then
      raise exception using errcode='22023',message='refund reference must be an active positive expense in this activity';
    end if;
    if v_parent_currency is distinct from v_original_currency then
      raise exception using errcode='22023',message='linked refund currency must match original expense';
    end if;
    if v_parent_fx_rate is distinct from p_fx_rate then
      raise exception using errcode='22023',message='linked refund must inherit the original expense FX rate';
    end if;
  end if;

  v_base_amount:=pg_catalog.round(p_original_amount*p_fx_rate,1);
  insert into public.expenses(
    ledger_unit_id,title,original_amount,original_currency,fx_rate,base_amount,
    split_method,occurred_at,note,original_expense_id,created_by,updated_by
  ) values (
    p_ledger_unit_id,v_title,p_original_amount,v_original_currency,p_fx_rate,v_base_amount,
    p_split_method,p_occurred_at,p_note,p_original_expense_id,v_user_id,v_user_id
  ) returning public.expenses.id,public.expenses.base_amount,public.expenses.version
    into v_expense_id,v_base_amount,v_version;

  perform private.replace_expense_children(
    v_expense_id,v_activity_id,p_original_amount,p_split_method,
    p_payments,p_manual_splits,p_aa_participant_ids
  );
  return query select v_expense_id,v_base_amount,v_version;
end;
$function$;


-- Replaced definition: private.rebuild_expense_debts_locked.
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

-- Normalize legacy base-derived rows while preserving legitimate micro-currency
-- rows whose base valuation rounds to zero. Linked refunds use the absolute
-- Expense amount when distributing the original-unit total.
create or replace function private.normalize_expense_debt_currency(p_expense_id uuid)
returns void language sql volatile security definer set search_path = ''
as $function$
  with ranked as (
    select ed.id,e.fx_rate,
      row_number() over(order by debtor.participant_order,debtor.id,creditor.participant_order,creditor.id,ed.id) rn,
      count(*) over() cnt,
      coalesce(sum(coalesce(ed.original_amount,pg_catalog.round(ed.amount/nullif(e.fx_rate,0),4)))
        over(partition by ed.expense_id),0)::numeric(20,4) original_total,
      coalesce(sum(case when ed.amount=0 then coalesce(ed.original_amount,0)
        else pg_catalog.round(ed.amount/nullif(e.fx_rate,0),4) end) over(
          order by debtor.participant_order,debtor.id,creditor.participant_order,creditor.id,ed.id
          rows between unbounded preceding and 1 preceding),0)::numeric(20,4) prior_original
    from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
    join public.participants debtor on debtor.activity_id=ed.activity_id and debtor.id=ed.debtor_participant_id
    join public.participants creditor on creditor.activity_id=ed.activity_id and creditor.id=ed.creditor_participant_id
    where ed.expense_id=p_expense_id
  )
  update public.expense_debts ed set
    original_amount=case when r.rn=r.cnt then (r.original_total-r.prior_original)::numeric(20,4)
      when ed.amount=0 then ed.original_amount
      else pg_catalog.round(ed.amount/nullif(r.fx_rate,0),4)::numeric(20,4) end,
    original_currency=e.original_currency,fx_rate=e.fx_rate
  from ranked r join public.expenses e on e.id=p_expense_id where ed.id=r.id;
$function$;


-- Replaced definition: private.rebuild_transfer_allocations_locked.
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
  v_base_currency character(3);
  v_remaining numeric(20,4);
  v_allocate_original numeric(20,4);
  v_allocate_base numeric(20,1);
  v_durable_total numeric(20,4);
begin
  select a.base_currency into v_base_currency
  from public.activities a where a.id = p_activity_id;

  delete from public.transfer_allocations
  where activity_id = p_activity_id;

  for v_transfer in
    select t.id, t.from_participant_id, t.to_participant_id, t.currency, t.occurred_at,t.created_at,
           c.id component_id, c.amount component_amount
    from public.transfers t
    join public.transfer_components c
      on c.transfer_id = t.id and c.activity_id = t.activity_id
    where t.activity_id = p_activity_id
      and not t.is_voided
      and t.type <> 'final_settlement'::public.transfer_type
      and c.component_type = 'settlement'
    order by t.occurred_at, t.created_at, t.id
  loop
    if exists (
      select 1 from public.transfer_expense_allocations x
      where x.activity_id = p_activity_id
        and x.transfer_id = v_transfer.id
        and x.allocation_mode in ('FIFO', 'TARGETED')
    ) then
      v_durable_total := 0;
      for v_debt in
        select x.*, ed.id as current_expense_debt_id
        from public.transfer_expense_allocations x
        join public.expense_debts ed
          on ed.activity_id = x.activity_id
         and ed.expense_id = x.expense_id
         and ed.debtor_participant_id = x.debtor_participant_id
         and ed.creditor_participant_id = x.creditor_participant_id
        where x.activity_id = p_activity_id
          and x.transfer_id = v_transfer.id
          and x.allocation_mode in ('FIFO', 'TARGETED')
        order by x.created_at, x.id
      loop
        if v_debt.payment_currency <> v_transfer.currency then
          raise exception using errcode = '23514',
            message = 'durable allocation currency does not match transfer';
        end if;
        insert into public.transfer_allocations(
          activity_id, transfer_id, settlement_component_id, expense_debt_id,
          amount, original_amount, base_amount
        ) values (
          p_activity_id, v_transfer.id, v_transfer.component_id,
          v_debt.current_expense_debt_id, v_debt.base_amount,
          v_debt.original_amount, v_debt.base_amount
        );
        v_durable_total := v_durable_total + v_debt.payment_amount;
      end loop;
      v_remaining := v_transfer.component_amount - v_durable_total;
    else
      v_remaining := v_transfer.component_amount;
      for v_debt in
        with raw as (
          select ed.id, ed.amount debt_base,
                 coalesce(ed.original_amount, ed.amount)::numeric(20,4) debt_original,
                 coalesce(ed.original_currency, v_base_currency)::character(3) debt_currency,
                 coalesce(ed.fx_rate,1)::numeric(20,10) debt_fx,
                 e.occurred_at, e.created_at, e.id expense_id,
                 coalesce(sum(coalesce(ed.original_amount,ed.amount)) over (
                   partition by ed.debtor_participant_id,ed.creditor_participant_id,
                     coalesce(ed.original_currency,v_base_currency)
                   order by e.occurred_at,e.created_at,e.id,ed.id
                   rows between unbounded preceding and 1 preceding),0) prior_original,
                 coalesce((select sum(coalesce(x.original_amount,x.amount))
                   from public.expense_debts x
                   join public.expenses xe on xe.id=x.expense_id
                   where x.activity_id=p_activity_id
                     and xe.occurred_at <= v_transfer.occurred_at
                     and xe.created_at <= v_transfer.created_at
                     and x.debtor_participant_id=v_transfer.to_participant_id
                     and x.creditor_participant_id=v_transfer.from_participant_id
                     and coalesce(x.original_currency,v_base_currency)=
                         coalesce(ed.original_currency,v_base_currency)),0) reverse_original
          from public.expense_debts ed
          join public.expenses e on e.id=ed.expense_id
          where ed.activity_id=p_activity_id
            and ed.debtor_participant_id=v_transfer.from_participant_id
            and ed.creditor_participant_id=v_transfer.to_participant_id
            and e.occurred_at <= v_transfer.occurred_at
            and e.created_at <= v_transfer.created_at
            and not e.is_deleted
        ), residual as (
          select r.*, least(r.debt_original,
            greatest(r.reverse_original-r.prior_original,0)) cancelled_original
          from raw r
        )
        select r.*,
          greatest(r.debt_original-r.cancelled_original
            - coalesce((select sum(coalesce(ta.original_amount,ta.amount))
                from public.transfer_allocations ta where ta.expense_debt_id=r.id),0)
            - coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu
                where pu.expense_debt_id=r.id),0),0)::numeric(20,4) available_original,
          greatest(r.debt_base-pg_catalog.round(r.cancelled_original*r.debt_fx,1)
            - coalesce((select sum(coalesce(ta.base_amount,ta.amount))
                from public.transfer_allocations ta where ta.expense_debt_id=r.id),0)
            - coalesce((select sum(pu.base_amount) from public.prepayment_usages pu
                where pu.expense_debt_id=r.id),0),0)::numeric(20,1) available_base
        from residual r
        where v_transfer.currency=v_base_currency or r.debt_currency=v_transfer.currency
        order by r.occurred_at,r.created_at,r.expense_id,r.id
      loop
        exit when v_remaining <= 0;
        if v_transfer.currency = v_base_currency then
          if v_debt.available_base <= 0 then continue; end if;
          v_allocate_base := least(v_remaining,v_debt.available_base)::numeric(20,1);
          v_allocate_original := least(v_debt.available_original,
            pg_catalog.round(v_allocate_base/nullif(v_debt.debt_fx,0),4))::numeric(20,4);
          if v_allocate_original <= 0 then continue; end if;
        else
          if v_debt.available_original <= 0 then continue; end if;
          v_allocate_original := least(v_remaining,v_debt.available_original)::numeric(20,4);
          v_allocate_base := pg_catalog.round(v_allocate_original*v_debt.debt_fx,1)::numeric(20,1);
        end if;
        insert into public.transfer_allocations(
          activity_id,transfer_id,settlement_component_id,expense_debt_id,
          amount,original_amount,base_amount
        ) values (
          p_activity_id,v_transfer.id,v_transfer.component_id,v_debt.id,
          v_allocate_base,v_allocate_original,v_allocate_base
        );
        v_remaining := v_remaining - case when v_transfer.currency=v_base_currency
          then v_allocate_base else v_allocate_original end;
      end loop;
    end if;

    if v_remaining > 0.00005 then
      raise exception using errcode='23514', message=pg_catalog.format(
        'settlement transfer %s has %s unallocated %s',
        v_transfer.id,v_remaining,v_transfer.currency);
    end if;
  end loop;
end;
$function$;


-- Replaced definition: private.rebuild_prepayment_projections_locked.
create or replace function private.rebuild_prepayment_projections_locked(p_activity_id uuid)
returns void language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_base_currency character(3);
  v_account record;
  v_debt record;
  v_account_id uuid;
  v_left numeric(20,4);
  v_take_original numeric(20,4);
  v_take_base numeric(20,1);
  v_funded numeric(20,4);
  v_take numeric(20,4);
  v_pre_take numeric(20,4);
  v_base_take numeric(20,1);
begin
  select a.base_currency into v_base_currency from public.activities a where a.id=p_activity_id;
  delete from public.prepayment_usages where activity_id=p_activity_id;
  delete from public.prepayment_accounts where activity_id=p_activity_id;

  for v_account in
    with facts as (
      select t.from_participant_id owner_participant_id,t.to_participant_id custodian_participant_id,
             t.currency, c.amount delta
      from public.transfers t join public.transfer_components c on c.transfer_id=t.id
      where t.activity_id=p_activity_id and not t.is_voided and c.component_type='prepayment'
      union all
      select t.to_participant_id,t.from_participant_id,t.currency,-c.amount
      from public.transfers t join public.transfer_components c on c.transfer_id=t.id
      where t.activity_id=p_activity_id and not t.is_voided and c.component_type='prepayment_return'
    )
    select owner_participant_id,custodian_participant_id,currency,
           sum(delta)::numeric(20,4) funded
    from facts group by owner_participant_id,custodian_participant_id,currency
    having sum(delta) >= 0
    order by owner_participant_id,custodian_participant_id,
      (currency=v_base_currency),currency
  loop
    v_funded := v_account.funded;
    insert into public.prepayment_accounts(
      activity_id,owner_participant_id,custodian_participant_id,currency,balance
    ) values (
      p_activity_id,v_account.owner_participant_id,v_account.custodian_participant_id,
      v_account.currency,v_funded
    ) returning id into v_account_id;
    v_left := v_funded;
    for v_debt in
      with raw as (
        select ed.id,ed.expense_id,ed.activity_id,ed.debtor_participant_id,ed.creditor_participant_id,
          ed.amount::numeric(20,1) gross_base,
          coalesce(ed.original_amount,ed.amount)::numeric(20,4) gross_original,
          coalesce(ed.original_currency,v_base_currency)::character(3) debt_currency,
          coalesce(ed.fx_rate,1)::numeric(20,10) debt_fx,
          e.occurred_at,e.created_at,e.id expense_id_order,
          greatest(coalesce(ed.original_amount,ed.amount)
            -coalesce((select sum(coalesce(ta.original_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=ed.id),0)
            -coalesce((select sum(coalesce(f.original_amount,f.amount)) from public.final_settlement_paths f join public.transfers ft on ft.id=f.transfer_id
              where f.activity_id=p_activity_id and f.component_type='settlement' and not ft.is_voided
                and f.from_participant_id=ed.debtor_participant_id and f.to_participant_id=ed.creditor_participant_id
                and (f.source_expense_debt_id=ed.id or (f.source_expense_debt_id is null and f.source_expense_id=ed.expense_id))),0),0)::numeric(20,4) unpaid_original,
          greatest(ed.amount
            -coalesce((select sum(coalesce(ta.base_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=ed.id),0)
            -coalesce((select sum(coalesce(f.base_amount,f.amount)) from public.final_settlement_paths f join public.transfers ft on ft.id=f.transfer_id
              where f.activity_id=p_activity_id and f.component_type='settlement' and not ft.is_voided
                and f.from_participant_id=ed.debtor_participant_id and f.to_participant_id=ed.creditor_participant_id
                and (f.source_expense_debt_id=ed.id or (f.source_expense_debt_id is null and f.source_expense_id=ed.expense_id))),0),0)::numeric(20,1) unpaid_base
        from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
        where ed.activity_id=p_activity_id and not e.is_deleted
      ), net as (
        select r.*,
          coalesce(sum(r.unpaid_original) over(partition by r.debtor_participant_id,r.creditor_participant_id,r.debt_currency
            order by r.occurred_at,r.created_at,r.expense_id_order,r.id rows between unbounded preceding and 1 preceding),0) prior_original,
          coalesce((select sum(x.unpaid_original) from raw x where x.debtor_participant_id=r.creditor_participant_id
            and x.creditor_participant_id=r.debtor_participant_id and x.debt_currency=r.debt_currency
            -- A linked refund is processed by the explicit Usage-release pass
            -- below. Excluding that matching refund here prevents its reverse
            -- debt from both reducing eligible Usage and releasing the same
            -- Usage a second time.
            and not exists(select 1 from public.expenses linked_refund
              where linked_refund.id=x.expense_id
                and linked_refund.original_expense_id=r.expense_id
                and linked_refund.original_amount<0 and not linked_refund.is_deleted)),0) reverse_original
        from raw r
      ), available as (
        select n.*,
          greatest(n.unpaid_original-least(n.unpaid_original,greatest(n.reverse_original-n.prior_original,0)),0)::numeric(20,4) net_original,
          greatest(n.unpaid_base-pg_catalog.round(least(n.unpaid_original,greatest(n.reverse_original-n.prior_original,0))*n.debt_fx,1),0)::numeric(20,1) net_base
        from net n
      )
      select av.id,av.gross_base debt_base,av.gross_original debt_original,av.debt_currency,av.debt_fx,
        av.occurred_at,av.created_at,av.expense_id_order expense_id,
        greatest(av.net_original-coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu where pu.expense_debt_id=av.id),0),0)::numeric(20,4) available_original,
        greatest(av.net_base-coalesce((select sum(pu.base_amount) from public.prepayment_usages pu where pu.expense_debt_id=av.id),0),0)::numeric(20,1) available_base
      from available av
      where av.debtor_participant_id=v_account.owner_participant_id
        and av.creditor_participant_id=v_account.custodian_participant_id
        and (v_account.currency=v_base_currency or av.debt_currency=v_account.currency)
      order by av.occurred_at,av.created_at,av.expense_id_order,av.id
    loop
      exit when v_left <= 0;
      if v_account.currency=v_base_currency then
        if v_debt.available_base <= 0 then continue; end if;
        v_take_base := least(v_left,v_debt.available_base)::numeric(20,1);
        v_take_original := case when v_debt.debt_currency=v_base_currency
          then v_take_base
          else pg_catalog.round(v_take_base/nullif(v_debt.debt_fx,0),4) end;
        if v_take_original <= 0 then continue; end if;
      else
        if v_debt.debt_currency<>v_account.currency or v_debt.available_original<=0 then continue; end if;
        v_take_original := least(v_left,v_debt.available_original)::numeric(20,4);
        v_take_base := pg_catalog.round(v_take_original*v_debt.debt_fx,1)::numeric(20,1);
      end if;
      insert into public.prepayment_usages(
        activity_id,account_id,expense_debt_id,gross_amount,amount,
        prepayment_currency,prepayment_amount,debt_currency,debt_amount,
        base_amount,bill_fx_rate,bill_occurred_at
      ) values (
        p_activity_id,v_account_id,v_debt.id,v_take_original,v_take_original,
        v_account.currency,case when v_account.currency=v_base_currency then v_take_base else v_take_original end,
        v_debt.debt_currency,v_take_original,
        v_take_base,v_debt.debt_fx,v_debt.occurred_at
      );
      v_left := v_left - case when v_account.currency=v_base_currency then v_take_base else v_take_original end;
    end loop;
    update public.prepayment_accounts set balance = greatest(
      v_funded - coalesce((select sum(pu.prepayment_amount) from public.prepayment_usages pu
        where pu.account_id=v_account_id),0),0), updated_at=pg_catalog.now()
    where id=v_account_id;
  end loop;
  -- Linked refunds cancel only usage tied to their original expense.  Excess
  -- refund value remains an ordinary reverse debt after this projection.
  for v_debt in
    select rf.original_expense_id,s.participant_id owner_participant_id,abs(s.amount)::numeric(20,4) benefit
    from public.expenses rf join public.splits s on s.expense_id=rf.id
    where rf.original_expense_id is not null and rf.original_amount<0 and not rf.is_deleted and s.amount<0
    order by rf.occurred_at,rf.created_at,rf.id,s.participant_id
  loop
    v_left:=v_debt.benefit;
    for v_account in
      select pu.id usage_id,pu.amount,pu.prepayment_amount,pu.debt_amount,pu.base_amount,pu.bill_fx_rate,pu.prepayment_currency
      from public.prepayment_usages pu join public.prepayment_accounts pa on pa.id=pu.account_id
      join public.expense_debts ed on ed.id=pu.expense_debt_id
      where pa.activity_id=p_activity_id and pa.owner_participant_id=v_debt.owner_participant_id and ed.expense_id=v_debt.original_expense_id
      order by pu.bill_occurred_at,pu.expense_debt_id,pu.id
    loop
      exit when v_left<=0;
      v_take:=least(v_left,v_account.debt_amount)::numeric(20,4);
      v_base_take:=pg_catalog.round(v_take*v_account.bill_fx_rate,1)::numeric(20,1);
      v_pre_take:=case when v_account.prepayment_currency=v_base_currency then v_base_take else v_take end;
      if v_take>=v_account.debt_amount then
        delete from public.prepayment_usages where id=v_account.usage_id;
      else
        update public.prepayment_usages set
          amount=amount-v_take,
          prepayment_amount=prepayment_amount-v_pre_take,
          debt_amount=debt_amount-v_take,
          base_amount=base_amount-v_base_take
        where id=v_account.usage_id;
      end if;
      v_left:=v_left-v_take;
    end loop;
  end loop;
  update public.prepayment_accounts pa set balance=greatest(
    coalesce((select sum(c.amount) from (
      select t.from_participant_id owner,t.to_participant_id cust,t.currency,tc.amount
      from public.transfers t join public.transfer_components tc on tc.transfer_id=t.id
      where t.activity_id=p_activity_id and not t.is_voided and tc.component_type='prepayment'
      union all select t.to_participant_id,t.from_participant_id,t.currency,-tc.amount
      from public.transfers t join public.transfer_components tc on tc.transfer_id=t.id
      where t.activity_id=p_activity_id and not t.is_voided and tc.component_type='prepayment_return'
    ) c where c.owner=pa.owner_participant_id and c.cust=pa.custodian_participant_id and c.currency=pa.currency),0)
    -coalesce((select sum(pu.prepayment_amount) from public.prepayment_usages pu where pu.account_id=pa.id),0),0), updated_at=pg_catalog.now()
  where pa.activity_id=p_activity_id;
end;
$function$;


-- Replaced definition: private.list_repayment_candidates.
-- Real settlement allocations are applied before reverse-debt netting. This
-- keeps a linked refund payable after its source debt has been partly or fully
-- settled, while still netting only the source debt's remaining balance.
create or replace function private.list_repayment_candidates(
  p_activity_id uuid,
  p_from_participant_id uuid,
  p_to_participant_id uuid,
  p_currency character(3)
)
returns table(
  expense_id uuid,
  ledger_unit_id uuid,
  ledger_unit_name text,
  title text,
  occurred_at timestamptz,
  debt_id uuid,
  debtor_participant_id uuid,
  creditor_participant_id uuid,
  debt_currency character(3),
  debt_original_amount numeric(20,4),
  debt_base_amount numeric(20,1),
  offset_original_amount numeric(20,4),
  offset_base_amount numeric(20,1),
  settled_original_amount numeric(20,4),
  settled_base_amount numeric(20,1),
  prepayment_original_amount numeric(20,4),
  prepayment_base_amount numeric(20,1),
  remaining_original_amount numeric(20,4),
  remaining_base_amount numeric(20,1),
  payment_currency_amount numeric(20,4),
  debt_fx numeric(20,10),
  financial_version bigint
)
language plpgsql stable security definer set search_path = ''
as $function$
declare
  v_currency character(3) := pg_catalog.upper(pg_catalog.btrim(p_currency));
  v_base_currency character(3);
begin
  if not exists (
    select 1 from public.activity_members m
    where m.activity_id=p_activity_id and m.user_id=(select auth.uid())
  ) then
    raise exception using errcode='42501',message='caller is not an activity member';
  end if;
  select a.base_currency into v_base_currency
  from public.activities a where a.id=p_activity_id and not a.is_deleted;
  if not found then
    raise exception using errcode='P0002',message='activity was not found';
  end if;
  if v_currency is null or v_currency !~ '^[A-Z]{3}$' then
    raise exception using errcode='22023',message='invalid settlement currency';
  end if;

  return query
  with raw as (
    select ed.id debt_id,ed.expense_id,ed.activity_id,ed.ledger_unit_id,
      ed.debtor_participant_id,ed.creditor_participant_id,
      coalesce(ed.original_currency,v_base_currency)::character(3) debt_currency,
      coalesce(ed.original_amount,ed.amount)::numeric(20,4) debt_original_amount,
      ed.amount::numeric(20,1) debt_base_amount,
      coalesce(ed.fx_rate,1)::numeric(20,10) debt_fx,
      e.title,e.occurred_at,e.created_at,lu.name ledger_unit_name,
      coalesce((select sum(coalesce(ta.original_amount,ta.amount))
        from public.transfer_allocations ta
        join public.transfers tx on tx.id=ta.transfer_id and tx.activity_id=ta.activity_id
        where ta.activity_id=p_activity_id and ta.expense_debt_id=ed.id and not tx.is_voided),0)::numeric(20,4) ordinary_settled_original,
      coalesce((select sum(coalesce(ta.base_amount,ta.amount))
        from public.transfer_allocations ta
        join public.transfers tx on tx.id=ta.transfer_id and tx.activity_id=ta.activity_id
        where ta.activity_id=p_activity_id and ta.expense_debt_id=ed.id and not tx.is_voided),0)::numeric(20,1) ordinary_settled_base,
      coalesce((select sum(coalesce(f.original_amount,f.amount))
        from public.final_settlement_paths f
        join public.transfers ft on ft.id=f.transfer_id and ft.activity_id=f.activity_id
        where f.activity_id=p_activity_id and f.component_type='settlement' and not ft.is_voided
          and f.from_participant_id=ed.debtor_participant_id
          and f.to_participant_id=ed.creditor_participant_id
          and f.source_expense_id=ed.expense_id),0)::numeric(20,4) final_settled_original,
      coalesce((select sum(coalesce(f.base_amount,f.amount))
        from public.final_settlement_paths f
        join public.transfers ft on ft.id=f.transfer_id and ft.activity_id=f.activity_id
        where f.activity_id=p_activity_id and f.component_type='settlement' and not ft.is_voided
          and f.from_participant_id=ed.debtor_participant_id
          and f.to_participant_id=ed.creditor_participant_id
          and f.source_expense_id=ed.expense_id),0)::numeric(20,1) final_settled_base,
      coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu
        where pu.activity_id=p_activity_id and pu.expense_debt_id=ed.id),0)::numeric(20,4) prepayment_original,
      coalesce((select sum(pu.base_amount) from public.prepayment_usages pu
        where pu.activity_id=p_activity_id and pu.expense_debt_id=ed.id),0)::numeric(20,1) prepayment_base,
      a.financial_version
    from public.expense_debts ed
    join public.expenses e on e.id=ed.expense_id
    join public.ledger_units lu on lu.id=e.ledger_unit_id
    join public.activities a on a.id=ed.activity_id
    where ed.activity_id=p_activity_id
      and not e.is_deleted and not lu.is_deleted and not a.is_deleted
  ), after_real as (
    select r.*,
      greatest(r.debt_original_amount-r.ordinary_settled_original-r.final_settled_original,0)::numeric(20,4) unpaid_original,
      greatest(r.debt_base_amount-r.ordinary_settled_base-r.final_settled_base,0)::numeric(20,1) unpaid_base
    from raw r
  ), net as (
    select r.*,
      coalesce(sum(r.unpaid_original) over(
        partition by r.debtor_participant_id,r.creditor_participant_id,r.debt_currency
        order by r.occurred_at,r.created_at,r.expense_id,r.debt_id
        rows between unbounded preceding and 1 preceding),0)::numeric(20,4) prior_original,
      coalesce((select sum(x.unpaid_original) from after_real x
        where x.debtor_participant_id=r.creditor_participant_id
          and x.creditor_participant_id=r.debtor_participant_id
          and x.debt_currency=r.debt_currency),0)::numeric(20,4) reverse_original
    from after_real r
  ), residual as (
    select n.*,
      least(n.unpaid_original,greatest(n.reverse_original-n.prior_original,0))::numeric(20,4) offset_original
    from net n
  ), totals as (
    select r.*,
      pg_catalog.round(r.offset_original*r.debt_fx,1)::numeric(20,1) offset_base,
      greatest(r.debt_original_amount-r.ordinary_settled_original-r.final_settled_original,0)::numeric(20,4) settled_residual_original,
      greatest(r.debt_base_amount-r.ordinary_settled_base-r.final_settled_base,0)::numeric(20,1) settled_residual_base
    from residual r
  )
  select t.expense_id,t.ledger_unit_id,t.ledger_unit_name,t.title,t.occurred_at,
    t.debt_id,t.debtor_participant_id,t.creditor_participant_id,t.debt_currency,
    t.debt_original_amount,t.debt_base_amount,t.offset_original,t.offset_base,
    (t.ordinary_settled_original+t.final_settled_original)::numeric(20,4),
    (t.ordinary_settled_base+t.final_settled_base)::numeric(20,1),
    t.prepayment_original,t.prepayment_base,
    greatest(t.settled_residual_original-t.offset_original-t.prepayment_original,0)::numeric(20,4),
    greatest(t.settled_residual_base-t.offset_base-t.prepayment_base,0)::numeric(20,1),
    case when v_currency=v_base_currency
      then greatest(t.settled_residual_base-t.offset_base-t.prepayment_base,0)::numeric(20,4)
      else greatest(t.settled_residual_original-t.offset_original-t.prepayment_original,0)::numeric(20,4)
    end,
    t.debt_fx,t.financial_version
  from totals t
  where t.debtor_participant_id=p_from_participant_id
    and t.creditor_participant_id=p_to_participant_id
    and (v_currency=v_base_currency or t.debt_currency=v_currency)
    and greatest(t.settled_residual_original-t.offset_original-t.prepayment_original,0)>0
  order by t.occurred_at,t.created_at,t.expense_id,t.debt_id;
end;
$function$;


-- Replaced definition: private.rebuild_bilateral_debts_locked.
create or replace function private.rebuild_bilateral_debts_locked(p_activity_id uuid)
returns void language plpgsql volatile security definer set search_path = ''
as $function$
begin
  delete from public.bilateral_debts where activity_id=p_activity_id;
  insert into public.bilateral_debts(
    activity_id,debtor_participant_id,creditor_participant_id,amount,
    original_amount,currency,base_amount
  )
  with raw as (
    select ed.id expense_debt_id,ed.expense_id,ed.activity_id,
      ed.debtor_participant_id,ed.creditor_participant_id,
      coalesce(ed.original_currency,a.base_currency)::character(3) currency,
      coalesce(ed.original_amount,ed.amount)::numeric(20,4) gross_original,
      ed.amount::numeric(20,1) gross_base,
      coalesce(ed.fx_rate,1)::numeric(20,10) fx_rate,
      e.occurred_at,e.created_at,e.id expense_order
    from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
    join public.ledger_units lu on lu.id=e.ledger_unit_id
    join public.activities a on a.id=lu.activity_id
    where ed.activity_id=p_activity_id and not e.is_deleted and not lu.is_deleted
  ), paid as (
    select r.*,
      greatest(r.gross_original
        -coalesce((select sum(coalesce(ta.original_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=r.expense_debt_id),0)
        -coalesce((select sum(coalesce(f.original_amount,f.amount)) from public.final_settlement_paths f join public.transfers t on t.id=f.transfer_id
          where f.activity_id=p_activity_id and f.component_type='settlement' and not t.is_voided
            and f.from_participant_id=r.debtor_participant_id and f.to_participant_id=r.creditor_participant_id
            and (f.source_expense_debt_id=r.expense_debt_id or (f.source_expense_debt_id is null and f.source_expense_id=r.expense_id))),0),0)::numeric(20,4) unpaid_original,
      greatest(r.gross_base
        -coalesce((select sum(coalesce(ta.base_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=r.expense_debt_id),0)
        -coalesce((select sum(coalesce(f.base_amount,f.amount)) from public.final_settlement_paths f join public.transfers t on t.id=f.transfer_id
          where f.activity_id=p_activity_id and f.component_type='settlement' and not t.is_voided
            and f.from_participant_id=r.debtor_participant_id and f.to_participant_id=r.creditor_participant_id
            and (f.source_expense_debt_id=r.expense_debt_id or (f.source_expense_debt_id is null and f.source_expense_id=r.expense_id))),0),0)::numeric(20,1) unpaid_base
    from raw r
  ), dir as (
    select r.*,coalesce(sum(r.unpaid_original) over (
      partition by r.debtor_participant_id,r.creditor_participant_id,r.currency
      order by r.occurred_at,r.created_at,r.expense_order,r.expense_debt_id
      rows between unbounded preceding and 1 preceding),0) prior_original,
      coalesce((select sum(x.unpaid_original) from paid x where
        x.debtor_participant_id=r.creditor_participant_id and x.creditor_participant_id=r.debtor_participant_id
        and x.currency=r.currency),0) reverse_original
    from paid r
  ), debt_rows as (
    select d.*,
      greatest(d.unpaid_original-least(d.unpaid_original,greatest(d.reverse_original-d.prior_original,0))
        -coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu where pu.expense_debt_id=d.expense_debt_id),0)
        ,0)::numeric(20,4) original_residual,
      greatest(d.unpaid_base-pg_catalog.round(least(d.unpaid_original,greatest(d.reverse_original-d.prior_original,0))*d.fx_rate,1)
        -coalesce((select sum(pu.base_amount) from public.prepayment_usages pu where pu.expense_debt_id=d.expense_debt_id),0)
        ,0)::numeric(20,1) base_residual
    from dir d
  ), grouped as (
    select activity_id,least(debtor_participant_id,creditor_participant_id) low_id,
      greatest(debtor_participant_id,creditor_participant_id) high_id,currency,
      sum(case when debtor_participant_id<creditor_participant_id then original_residual else -original_residual end) signed_original,
      sum(case when debtor_participant_id<creditor_participant_id then base_residual else -base_residual end) signed_base
    from debt_rows group by activity_id,least(debtor_participant_id,creditor_participant_id),greatest(debtor_participant_id,creditor_participant_id),currency
  )
  select g.activity_id,
    case when g.signed_original>0 then g.low_id else g.high_id end,
    case when g.signed_original>0 then g.high_id else g.low_id end,
    greatest(abs(g.signed_base),0)::numeric(20,1),abs(g.signed_original)::numeric(20,4),g.currency,
    greatest(abs(g.signed_base),0)::numeric(20,1)
  from grouped g where g.signed_original>0 or g.signed_original<0;
end;
$function$;


-- Replaced definition: private.create_expense_repayment_v2_impl.
create or replace function private.create_expense_repayment_v2_impl(
  p_activity_id uuid,
  p_from_participant_id uuid,
  p_to_participant_id uuid,
  p_amount numeric(20,4),
  p_currency character(3),
  p_mode text,
  p_target_expense_ids uuid[],
  p_occurred_at timestamptz,
  p_on_behalf_of_participant_id uuid,
  p_expected_version bigint,
  p_request_id uuid
)
returns table(
  transfer_id uuid,
  amount numeric(20,4),
  currency character(3),
  mode text,
  financial_version bigint
)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_user uuid := (select auth.uid());
  v_mode text := pg_catalog.upper(pg_catalog.btrim(coalesce(p_mode,'FIFO')));
  v_currency character(3) := pg_catalog.upper(pg_catalog.btrim(p_currency));
  v_base_currency character(3);
  v_archived_at timestamptz;
  v_is_deleted boolean;
  v_version bigint;
  v_transfer_id uuid;
  v_component_id uuid;
  v_existing record;
  v_result jsonb;
  v_payload jsonb;
  v_targets uuid[] := '{}'::uuid[];
  v_preview record;
begin
  if v_user is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if p_request_id is null or p_expected_version is null then
    raise exception using errcode='22023',message='expected_financial_version and request_id are required';
  end if;
  if p_amount is null or p_amount<=0 or p_from_participant_id is null
     or p_to_participant_id is null or p_from_participant_id=p_to_participant_id
     or p_occurred_at is null then
    raise exception using errcode='22023',message='invalid repayment';
  end if;
  if v_mode not in ('FIFO','TARGETED') then
    raise exception using errcode='22023',message='repayment mode must be FIFO or TARGETED';
  end if;
  if v_mode='TARGETED' then
    v_targets:=coalesce(p_target_expense_ids,'{}'::uuid[]);
    if coalesce(array_length(v_targets,1),0)=0
       or exists(select 1 from unnest(v_targets) as u(x) where x is null) then
      raise exception using errcode='22023',message='targeted repayment requires expense ids';
    end if;
    select coalesce(array_agg(x order by x),'{}'::uuid[]) into v_targets
    from (select distinct x from unnest(v_targets) as u(x)) d;
  end if;

  perform private.lock_debt_projection_activity(p_activity_id);
  select a.base_currency,a.archived_at,a.financial_version,a.is_deleted
    into v_base_currency,v_archived_at,v_version,v_is_deleted
  from public.activities a
  where a.id=p_activity_id
  for update;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;

  v_payload:=jsonb_build_object(
    'operation','create_expense_repayment_v2',
    'activity_id',p_activity_id,
    'from_participant_id',p_from_participant_id,
    'to_participant_id',p_to_participant_id,
    'amount',p_amount,
    'currency',v_currency,
    'mode',v_mode,
    'target_expense_ids',to_jsonb(v_targets),
    'occurred_at',p_occurred_at,
    'on_behalf_of_participant_id',p_on_behalf_of_participant_id,
    'expected_financial_version',p_expected_version
  );
  select t.* into v_existing
  from public.transfers t
  where t.activity_id=p_activity_id and t.request_id=p_request_id
  for update;
  if found then
    if v_existing.request_payload is distinct from v_payload
       or v_existing.type<>'settlement'::public.transfer_type
       or v_existing.recorded_by is distinct from v_user then
      raise exception using errcode='23505',message='repayment request id was already used with a different payload';
    end if;
    v_result:=v_existing.request_result;
    if v_result is null then raise exception using errcode='55000',message='idempotent result is unavailable'; end if;
    return query select (v_result->>'transfer_id')::uuid,(v_result->>'amount')::numeric,
      (v_result->>'currency')::character(3),(v_result->>'mode')::text,
      (v_result->>'financial_version')::bigint;
    return;
  end if;

  if v_is_deleted then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived_at is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if;
  perform private.assert_financial_version(p_activity_id,p_expected_version);
  if v_currency is null or v_currency !~ '^[A-Z]{3}$' then
    raise exception using errcode='22023',message='invalid settlement currency';
  end if;
  if v_currency=v_base_currency and p_amount<>pg_catalog.round(p_amount,1) then
    raise exception using errcode='22023',message='base-currency amount must have one decimal place';
  end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=v_user) then
    raise exception using errcode='42501',message='caller is not an activity member';
  end if;
  perform 1 from public.participants p where p.activity_id=p_activity_id
    and p.id in(p_from_participant_id,p_to_participant_id) and not p.is_deleted
    order by p.id for update;
  if (select count(*) from public.participants p where p.activity_id=p_activity_id
      and p.id in(p_from_participant_id,p_to_participant_id) and not p.is_deleted)<>2 then
    raise exception using errcode='P0002',message='transfer participant was not found';
  end if;
  perform private.authorize_phase5_actor(p_activity_id,p_from_participant_id,p_to_participant_id,p_on_behalf_of_participant_id);

  -- The preview is evaluated while the Activity lock is held, so the durable
  -- allocations below and the subsequent projection rebuild see one version.
  for v_preview in
    select * from private.build_expense_repayment_preview(
      p_activity_id,p_from_participant_id,p_to_participant_id,p_amount,v_currency,
      v_mode,v_targets,p_expected_version
    )
  loop
    null;
  end loop;

  insert into public.transfers(
    activity_id,from_participant_id,to_participant_id,type,amount,currency,
    occurred_at,recorded_by,on_behalf_of_participant_id,request_id,request_payload,
    settlement_mode,target_expense_ids
  ) values (
    p_activity_id,p_from_participant_id,p_to_participant_id,'settlement'::public.transfer_type,
    p_amount,v_currency,p_occurred_at,v_user,p_on_behalf_of_participant_id,p_request_id,
    v_payload,v_mode,v_targets
  ) returning id into v_transfer_id;
  insert into public.transfer_components(activity_id,transfer_id,component_type,amount)
    values(p_activity_id,v_transfer_id,'settlement',p_amount)
    returning id into v_component_id;
  perform private.assert_component_total(v_transfer_id);

  for v_preview in
    select * from private.build_expense_repayment_preview(
      p_activity_id,p_from_participant_id,p_to_participant_id,p_amount,v_currency,
      v_mode,v_targets,p_expected_version
    )
  loop
    insert into public.transfer_expense_allocations(
      activity_id,transfer_id,settlement_component_id,expense_id,ledger_unit_id,
      debtor_participant_id,creditor_participant_id,allocation_mode,
      payment_currency,payment_amount,original_currency,original_amount,
      base_amount,fx_rate,source_expense_debt_id
    )
    select p_activity_id,v_transfer_id,v_component_id,v_preview.expense_id,
      v_preview.ledger_unit_id,p_from_participant_id,p_to_participant_id,
      v_mode,v_preview.payment_currency,v_preview.payment_amount,
      v_preview.original_currency,v_preview.original_amount,v_preview.base_amount,
      v_preview.fx_rate,ed.id
    from public.expense_debts ed
    where ed.activity_id=p_activity_id and ed.expense_id=v_preview.expense_id
      and ed.debtor_participant_id=p_from_participant_id
      and ed.creditor_participant_id=p_to_participant_id;
    if not found then
      raise exception using errcode='40001',message='repayment debt changed while committing; refresh the plan';
    end if;
  end loop;

  if v_mode='FIFO' then
    perform private.phase5_rebuild_after_transfer(p_activity_id);
  else
    -- A targeted payment is computed from the currently available residual.
    -- Keep existing prepayment usages attached to their bills during this
    -- commit; void/rebuild paths may explicitly recompute the dynamic usage
    -- projection later.
    perform private.rebuild_transfer_allocations_locked(p_activity_id);
    perform private.rebuild_bilateral_debts_locked(p_activity_id);
  end if;
  update public.activities a set financial_version=a.financial_version+1
    where a.id=p_activity_id returning a.financial_version into v_version;
  v_result:=jsonb_build_object('transfer_id',v_transfer_id,'amount',p_amount,
    'currency',v_currency,'mode',v_mode,'financial_version',v_version);
  update public.transfers set request_result=v_result where id=v_transfer_id;
  return query select v_transfer_id,p_amount,v_currency,v_mode,v_version;
end;
$function$;


-- Replaced definition: private.execute_final_settlement_v2_impl.
create or replace function private.execute_final_settlement_v2_impl(
  p_activity_id uuid, p_from uuid, p_to uuid, p_amount numeric(20,4), p_currency character(3),
  p_mode text, p_expected_version bigint, p_request_id uuid, p_occurred_at timestamptz, p_behalf uuid
)
returns table(transfer_id uuid, amount numeric(20,4), currency character(3), mode text, financial_version bigint)
language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_user uuid:=(select auth.uid()); v_mode text:=coalesce(p_mode,'base_unified'); v_currency character(3);
  v_base character(3); v_archived timestamptz; v_version bigint; v_is_deleted boolean; v_plan record; v_transfer uuid;
  v_existing record; v_payload jsonb; v_result jsonb; v_flow record; v_hop record; v_debt record; v_path_order integer:=0; v_path_no integer; v_hop_seq integer; v_source_expense uuid; v_source_debt uuid; v_debt_currency character(3); v_fx numeric(20,10); v_original numeric(20,4); v_base_amount numeric(20,1); v_hop_remaining numeric(20,4); v_take numeric(20,4);
begin
  if v_user is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if p_expected_version is null or p_request_id is null then raise exception using errcode='22023',message='expected_financial_version and request_id are required'; end if;
  if p_amount is null or p_amount<=0 or p_from is null or p_to is null or p_from=p_to or p_occurred_at is null then raise exception using errcode='22023',message='invalid final settlement'; end if;
  if v_mode not in ('base_unified','original_currency') then raise exception using errcode='22023',message='invalid final settlement mode'; end if;
  v_payload:=jsonb_build_object('operation','execute_final_settlement','activity_id',p_activity_id,'from_participant_id',p_from,'to_participant_id',p_to,'amount',p_amount,'currency',pg_catalog.upper(pg_catalog.btrim(p_currency)),'mode',v_mode,'expected_financial_version',p_expected_version,'occurred_at',p_occurred_at,'on_behalf_of_participant_id',p_behalf);
  perform private.lock_debt_projection_activity(p_activity_id);
  select a.base_currency,a.archived_at,a.financial_version,a.is_deleted into v_base,v_archived,v_version,v_is_deleted from public.activities a where a.id=p_activity_id for update;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  v_currency:=pg_catalog.upper(pg_catalog.btrim(p_currency));
  if v_currency is null or v_currency !~ '^[A-Z]{3}$' then raise exception using errcode='22023',message='invalid settlement currency'; end if;

  -- Check the idempotency key before the optimistic-version assertion.  A
  -- retry after a committed request necessarily carries the now-stale
  -- original version, but must still return the committed result.
  select t.* into v_existing from public.transfers t where t.activity_id=p_activity_id and t.request_id=p_request_id for update;
  if found then
    if v_existing.request_payload is distinct from v_payload or v_existing.type<>'final_settlement'::public.transfer_type
       or v_existing.recorded_by is distinct from v_user then raise exception using errcode='23505',message='final settlement request id was already used with a different payload or actor'; end if;
    v_result:=v_existing.request_result; if v_result is null then raise exception using errcode='55000',message='idempotent result is unavailable'; end if;
    return query select (v_result->>'transfer_id')::uuid,(v_result->>'amount')::numeric,(v_result->>'currency')::character(3),(v_result->>'mode')::text,(v_result->>'financial_version')::bigint; return;
  end if;
  if v_is_deleted then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if;
  if v_currency=v_base and p_amount<>pg_catalog.round(p_amount,1) then raise exception using errcode='22023',message='base-currency amount must have one decimal place'; end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=v_user) then raise exception using errcode='42501',message='caller is not an activity member'; end if;
  if p_behalf is not null and p_behalf not in (p_from,p_to) then raise exception using errcode='22023',message='on-behalf participant must be a transfer party'; end if;
  perform private.assert_financial_version(p_activity_id,p_expected_version);
  select p.* into v_plan from private.build_final_settlement_plan_v2(p_activity_id,v_mode) p
    where p.from_participant_id=p_from and p.to_participant_id=p_to and p.amount=p_amount and p.currency=v_currency;
  if not found then raise exception using errcode='23514',message='final settlement does not match current plan'; end if;
  -- base_unified ordinary debt is always settled in the activity base
  -- currency.  A pure prepayment return is different: its currency is the
  -- prepayment account's own currency and must not be converted implicitly.
  if v_mode='base_unified' and v_plan.ordinary_amount>0 and v_currency<>v_base then
    raise exception using errcode='22023',message='base_unified ordinary settlement must use base currency';
  end if;
  insert into public.transfers(activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,recorded_by,on_behalf_of_participant_id,request_id,request_payload,settlement_mode)
    values(p_activity_id,p_from,p_to,'final_settlement',p_amount,v_currency,p_occurred_at,v_user,p_behalf,p_request_id,v_payload,'FINAL_SETTLEMENT') returning id into v_transfer;
  if v_plan.ordinary_amount>0 then insert into public.transfer_components(activity_id,transfer_id,component_type,amount) values(p_activity_id,v_transfer,'settlement',v_plan.ordinary_amount); end if;
  if v_plan.prepayment_return_amount>0 then insert into public.transfer_components(activity_id,transfer_id,component_type,amount) values(p_activity_id,v_transfer,'prepayment_return',v_plan.prepayment_return_amount); end if;
  perform private.assert_component_total(v_transfer);
  if v_plan.ordinary_amount>0 then
    if v_mode='base_unified' then
      for v_flow in select f.* from private.build_final_settlement_flow(p_activity_id) f where f.from_participant_id=p_from and f.to_participant_id=p_to order by f.path_no loop
        v_hop_seq:=0;
        for v_hop in select * from jsonb_to_recordset(v_flow.hops) as h(hop_no integer,from_participant_id uuid,to_participant_id uuid,amount numeric) loop
          v_hop_remaining:=v_hop.amount;
          for v_debt in
            select ed.id source_debt,ed.expense_id,coalesce(ed.original_currency,v_base)::character(3) debt_currency,coalesce(ed.fx_rate,1)::numeric(20,10) fx_rate,e.occurred_at,e.created_at,
              greatest(ed.amount-coalesce((select sum(coalesce(ta.base_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=ed.id),0)-coalesce((select sum(pu.base_amount) from public.prepayment_usages pu where pu.expense_debt_id=ed.id),0)-coalesce((select sum(f.base_amount) from public.final_settlement_paths f join public.transfers ft on ft.id=f.transfer_id and not ft.is_voided where f.activity_id=p_activity_id and f.source_expense_debt_id=ed.id),0),0)::numeric(20,1) available_base
            from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
            where ed.activity_id=p_activity_id and ed.debtor_participant_id=v_hop.from_participant_id and ed.creditor_participant_id=v_hop.to_participant_id
            order by e.occurred_at,e.created_at,e.id,ed.id
          loop
            exit when v_hop_remaining<=0; if v_debt.available_base<=0 then continue; end if;
            v_take:=least(v_hop_remaining,v_debt.available_base); v_hop_seq:=v_hop_seq+1; v_path_order:=v_path_order+1; v_base_amount:=v_take::numeric(20,1); v_fx:=v_debt.fx_rate; v_original:=case when v_debt.debt_currency=v_base then v_take else pg_catalog.round(v_take/nullif(v_fx,0),4) end;
            insert into public.final_settlement_paths(activity_id,transfer_id,path_order,path_no,hop_no,from_participant_id,to_participant_id,amount,component_type,source_expense_id,source_expense_debt_id,mode,path_currency,original_amount,base_amount,fx_rate)
              values(p_activity_id,v_transfer,v_path_order,v_flow.path_no,v_hop_seq,v_hop.from_participant_id,v_hop.to_participant_id,v_take,'settlement',v_debt.expense_id,v_debt.source_debt,v_mode,v_debt.debt_currency,v_original,v_base_amount,v_fx);
            v_hop_remaining:=v_hop_remaining-v_take;
          end loop;
          if v_hop_remaining>0 then raise exception using errcode='23514',message='final settlement path has no remaining expense debt capacity'; end if;
        end loop;
      end loop;
    else
      for v_flow in select f.* from private.build_final_settlement_flow_original(p_activity_id,v_currency) f where f.from_participant_id=p_from and f.to_participant_id=p_to order by f.path_no loop
        v_hop_seq:=0;
        for v_hop in select * from jsonb_to_recordset(v_flow.hops) as h(hop_no integer,from_participant_id uuid,to_participant_id uuid,amount numeric) loop
          v_hop_remaining:=v_hop.amount;
          for v_debt in
            select ed.id source_debt,ed.expense_id,coalesce(ed.fx_rate,1)::numeric(20,10) fx_rate,e.occurred_at,e.created_at,
              greatest(coalesce(ed.original_amount,ed.amount)-coalesce((select sum(coalesce(ta.original_amount,ta.amount)) from public.transfer_allocations ta where ta.expense_debt_id=ed.id),0)-coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu where pu.expense_debt_id=ed.id),0)-coalesce((select sum(f.original_amount) from public.final_settlement_paths f join public.transfers ft on ft.id=f.transfer_id and not ft.is_voided where f.activity_id=p_activity_id and f.source_expense_debt_id=ed.id),0),0)::numeric(20,4) available_original
            from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
            where ed.activity_id=p_activity_id and ed.debtor_participant_id=v_hop.from_participant_id and ed.creditor_participant_id=v_hop.to_participant_id and coalesce(ed.original_currency,v_base)=v_currency
            order by e.occurred_at,e.created_at,e.id,ed.id
          loop
            exit when v_hop_remaining<=0; if v_debt.available_original<=0 then continue; end if;
            v_take:=least(v_hop_remaining,v_debt.available_original); v_hop_seq:=v_hop_seq+1; v_path_order:=v_path_order+1; v_original:=v_take; v_fx:=v_debt.fx_rate; v_base_amount:=pg_catalog.round(v_take*v_fx,1);
            insert into public.final_settlement_paths(activity_id,transfer_id,path_order,path_no,hop_no,from_participant_id,to_participant_id,amount,component_type,source_expense_id,source_expense_debt_id,mode,path_currency,original_amount,base_amount,fx_rate)
              values(p_activity_id,v_transfer,v_path_order,v_flow.path_no,v_hop_seq,v_hop.from_participant_id,v_hop.to_participant_id,v_take,'settlement',v_debt.expense_id,v_debt.source_debt,v_mode,v_currency,v_original,v_base_amount,v_fx);
            v_hop_remaining:=v_hop_remaining-v_take;
          end loop;
          if v_hop_remaining>0 then raise exception using errcode='23514',message='original-currency path has no remaining expense debt capacity'; end if;
        end loop;
      end loop;
    end if;
  end if;
  if v_plan.prepayment_return_amount>0 then
    v_path_order:=v_path_order+1; select coalesce(max(fsp.path_no),0)+1 into v_path_no from public.final_settlement_paths as fsp where fsp.transfer_id=v_transfer;
    insert into public.final_settlement_paths(activity_id,transfer_id,path_order,path_no,hop_no,from_participant_id,to_participant_id,amount,component_type,mode,path_currency,original_amount,base_amount,fx_rate)
      values(p_activity_id,v_transfer,v_path_order,v_path_no,1,p_from,p_to,v_plan.prepayment_return_amount,'prepayment_return',v_mode,v_currency,v_plan.prepayment_return_amount,null,null);
  end if;
  perform private.phase5_rebuild_after_transfer(p_activity_id);
  update public.activities as act set financial_version=act.financial_version+1 where act.id=p_activity_id returning act.financial_version into v_version;
  v_result:=jsonb_build_object('transfer_id',v_transfer,'amount',p_amount,'currency',v_currency,'mode',v_mode,'financial_version',v_version);
  update public.transfers set request_result=v_result where id=v_transfer;
  return query select v_transfer,p_amount,v_currency,v_mode,v_version;
end;
$function$;


-- Replaced definition: private.create_prepayment_v2_impl.
create or replace function private.create_prepayment_v2_impl(
  p_activity_id uuid, p_owner uuid, p_custodian uuid, p_amount numeric(20,4),
  p_currency character(3), p_occurred_at timestamptz, p_behalf uuid,
  p_expected_version bigint, p_request_id uuid
)
returns table(
  transfer_id uuid, settlement_amount numeric(20,4), prepayment_amount numeric(20,4),
  new_balance numeric(20,4), currency character(3), financial_version bigint
)
language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_user uuid := (select auth.uid()); v_currency character(3); v_base character(3); v_archived timestamptz; v_is_deleted boolean;
  v_cap numeric(20,4); v_settlement numeric(20,4); v_prepayment numeric(20,4); v_balance numeric(20,4);
  v_version bigint; v_transfer uuid; v_existing record; v_payload jsonb; v_result jsonb;
  v_participant_count integer;
  v_settlement_component_id uuid;
  v_preview record;
begin
  if v_user is null then
    raise exception using errcode='28000',message='authentication is required';
  end if;
  if p_expected_version is null or p_request_id is null then
    raise exception using errcode='22023',message='expected_financial_version and request_id are required';
  end if;
  if p_amount is null or p_amount<=0 or p_owner is null or p_custodian is null
     or p_owner=p_custodian or p_occurred_at is null then
    raise exception using errcode='22023',message='invalid prepayment';
  end if;
  if p_behalf is not null then
    raise exception using errcode='42501',message='on-behalf prepayment is not supported';
  end if;
  v_payload:=jsonb_build_object('operation','create_prepayment','activity_id',p_activity_id,
    'owner_participant_id',p_owner,'custodian_participant_id',p_custodian,'amount',p_amount,
    'currency',pg_catalog.upper(pg_catalog.btrim(p_currency)),'occurred_at',p_occurred_at,
    'on_behalf_of_participant_id',p_behalf,'expected_financial_version',p_expected_version);
  perform private.lock_debt_projection_activity(p_activity_id);
  select a.base_currency,a.archived_at,a.financial_version,a.is_deleted into v_base,v_archived,v_version,v_is_deleted
    from public.activities a where a.id=p_activity_id for update;
  if not found then
    raise exception using errcode='P0002',message='activity was not found';
  end if;
  select t.* into v_existing
    from public.transfers t where t.activity_id=p_activity_id and t.request_id=p_request_id for update;
  if found then
    if v_existing.request_payload is distinct from v_payload
       or v_existing.type<>'prepayment'::public.transfer_type
       or v_existing.recorded_by is distinct from v_user then
      raise exception using errcode='23505',message='prepayment request id was already used with a different payload or actor';
    end if;
    v_result:=v_existing.request_result;
    if v_result is null then raise exception using errcode='55000',message='idempotent result is unavailable'; end if;
    return query select (v_result->>'transfer_id')::uuid,(v_result->>'settlement_amount')::numeric,
      (v_result->>'prepayment_amount')::numeric,(v_result->>'new_balance')::numeric,
      (v_result->>'currency')::character(3),(v_result->>'financial_version')::bigint;
    return;
  end if;
  if v_is_deleted then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived is not null then
    raise exception using errcode='55000',message='archived activity is read-only';
  end if;
  perform private.assert_financial_version(p_activity_id,p_expected_version);
  v_currency:=private.validate_financial_currency(p_activity_id,p_currency);
  if v_currency=v_base and p_amount<>pg_catalog.round(p_amount,1) then
    raise exception using errcode='22023',message='base-currency amount must have one decimal place';
  end if;
  if not exists(
    select 1 from public.activity_members m
    where m.activity_id=p_activity_id and m.user_id=v_user
  ) then
    raise exception using errcode='42501',message='caller is not an activity member';
  end if;
  select count(*) into v_participant_count
    from public.participants p
    where p.activity_id=p_activity_id
      and p.id in (p_owner,p_custodian)
      and not p.is_deleted;
  if v_participant_count<>2 then
    raise exception using errcode='P0002',message='prepayment participant was not found';
  end if;
  -- Deliberately do not call the phase-5 actor gate here.  New prepayments
  -- are allowed for any two distinct activity participants.
  select coalesce(sum(case when v_currency=v_base then coalesce(b.base_amount,b.amount)
                           else coalesce(b.original_amount,b.amount) end),0)
    into v_cap
    from public.bilateral_debts b
    where b.activity_id=p_activity_id
      and b.debtor_participant_id=p_owner
      and b.creditor_participant_id=p_custodian
      and (v_currency=v_base or b.currency=v_currency);
  v_settlement:=least(p_amount,coalesce(v_cap,0));
  v_prepayment:=greatest(p_amount-v_settlement,0);
  insert into public.transfers(
    activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,
    recorded_by,on_behalf_of_participant_id,request_id,request_payload
  ) values(
    p_activity_id,p_owner,p_custodian,'prepayment',p_amount,v_currency,p_occurred_at,
    v_user,p_behalf,p_request_id,v_payload
  ) returning id into v_transfer;
  if v_settlement>0 then
    insert into public.transfer_components(activity_id,transfer_id,component_type,amount)
      values(p_activity_id,v_transfer,'settlement',v_settlement)
      returning id into v_settlement_component_id;
    -- The settlement portion is a real cash payment, so persist the FIFO
    -- source amounts just like an ordinary FIFO repayment. Without these
    -- durable rows a later full projection rebuild can move this payment to
    -- a different Expense when debts are recreated.
    for v_preview in
      select * from private.build_expense_repayment_preview(
        p_activity_id,p_owner,p_custodian,v_settlement,v_currency,'FIFO',null,p_expected_version
      )
    loop
      if v_preview.payment_amount<=0 then
        continue;
      end if;
      insert into public.transfer_expense_allocations(
        activity_id,transfer_id,settlement_component_id,expense_id,ledger_unit_id,
        debtor_participant_id,creditor_participant_id,allocation_mode,
        payment_currency,payment_amount,original_currency,original_amount,
        base_amount,fx_rate,source_expense_debt_id
      )
      select p_activity_id,v_transfer,v_settlement_component_id,v_preview.expense_id,
        v_preview.ledger_unit_id,p_owner,p_custodian,'FIFO',
        v_preview.payment_currency,v_preview.payment_amount,
        v_preview.original_currency,v_preview.original_amount,v_preview.base_amount,
        v_preview.fx_rate,ed.id
      from public.expense_debts ed
      where ed.activity_id=p_activity_id and ed.expense_id=v_preview.expense_id
        and ed.debtor_participant_id=p_owner and ed.creditor_participant_id=p_custodian;
      if not found then
        raise exception using errcode='40001',message='prepayment settlement source changed while committing; refresh the plan';
      end if;
    end loop;
  end if;
  if v_prepayment>0 then
    insert into public.transfer_components(activity_id,transfer_id,component_type,amount)
      values(p_activity_id,v_transfer,'prepayment',v_prepayment);
  end if;
  perform private.assert_component_total(v_transfer);
  perform private.phase5_rebuild_after_transfer(p_activity_id);
  update public.activities as act
    set financial_version=act.financial_version+1
    where act.id=p_activity_id
    returning act.financial_version into v_version;
  select coalesce(pa.balance,0) into v_balance
    from public.prepayment_accounts pa
    where pa.activity_id=p_activity_id
      and pa.owner_participant_id=p_owner
      and pa.custodian_participant_id=p_custodian
      and pa.currency=v_currency;
  v_result:=jsonb_build_object('transfer_id',v_transfer,'settlement_amount',v_settlement,
    'prepayment_amount',v_prepayment,'new_balance',coalesce(v_balance,0),
    'currency',v_currency,'financial_version',v_version);
  update public.transfers set request_result=v_result where id=v_transfer;
  return query select v_transfer,v_settlement,v_prepayment,coalesce(v_balance,0),v_currency,v_version;
end;
$function$;


-- Replaced definition: private.create_prepayment_return_v2_impl.
create or replace function private.create_prepayment_return_v2_impl(
  p_activity_id uuid, p_owner uuid, p_custodian uuid, p_amount numeric(20,4),
  p_currency character(3), p_occurred_at timestamptz, p_behalf uuid,
  p_expected_version bigint, p_request_id uuid
)
returns table(
  transfer_id uuid, amount numeric(20,4), currency character(3),
  remaining_balance numeric(20,4), financial_version bigint
)
language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_user uuid := (select auth.uid()); v_currency character(3); v_base character(3);
  v_archived timestamptz; v_version bigint; v_is_deleted boolean; v_balance numeric(20,4); v_transfer uuid;
  v_existing record; v_payload jsonb; v_result jsonb;
begin
  if v_user is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if p_expected_version is null or p_request_id is null then
    raise exception using errcode='22023',message='expected_financial_version and request_id are required';
  end if;
  if p_amount is null or p_amount<=0 or p_owner is null or p_custodian is null or p_owner=p_custodian
     or p_occurred_at is null then raise exception using errcode='22023',message='invalid prepayment return'; end if;
  v_payload:=jsonb_build_object('operation','create_prepayment_return','activity_id',p_activity_id,
    'owner_participant_id',p_owner,'custodian_participant_id',p_custodian,'amount',p_amount,
    'currency',pg_catalog.upper(pg_catalog.btrim(p_currency)),'occurred_at',p_occurred_at,
    'on_behalf_of_participant_id',p_behalf,'expected_financial_version',p_expected_version);
  perform private.lock_debt_projection_activity(p_activity_id);
  select a.base_currency,a.archived_at,a.financial_version,a.is_deleted into v_base,v_archived,v_version,v_is_deleted
    from public.activities a where a.id=p_activity_id for update;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  select t.* into v_existing from public.transfers t where t.activity_id=p_activity_id and t.request_id=p_request_id for update;
  if found then
    if v_existing.request_payload is distinct from v_payload or v_existing.type<>'prepayment_return'::public.transfer_type
       or v_existing.recorded_by is distinct from v_user then
      raise exception using errcode='23505',message='prepayment return request id was already used with a different payload or actor'; end if;
    v_result:=v_existing.request_result;
    if v_result is null then raise exception using errcode='55000',message='idempotent result is unavailable'; end if;
    return query select (v_result->>'transfer_id')::uuid,(v_result->>'amount')::numeric,
      (v_result->>'currency')::character(3),(v_result->>'remaining_balance')::numeric,
      (v_result->>'financial_version')::bigint; return;
  end if;
  if v_is_deleted then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if;
  perform private.assert_financial_version(p_activity_id,p_expected_version);
  v_currency:=pg_catalog.upper(pg_catalog.btrim(p_currency));
  if v_currency is null or v_currency !~ '^[A-Z]{3}$' then raise exception using errcode='22023',message='invalid prepayment return currency'; end if;
  if v_currency=v_base and p_amount<>pg_catalog.round(p_amount,1) then
    raise exception using errcode='22023',message='base-currency amount must have one decimal place';
  end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=v_user) then
    raise exception using errcode='42501',message='caller is not an activity member'; end if;
  perform private.authorize_phase5_actor(p_activity_id,p_custodian,p_owner,p_behalf);
  select pa.balance into v_balance from public.prepayment_accounts pa where pa.activity_id=p_activity_id
    and pa.owner_participant_id=p_owner and pa.custodian_participant_id=p_custodian and pa.currency=v_currency;
  if v_balance is null or p_amount>v_balance then
    raise exception using errcode='23514',message='prepayment return exceeds available balance'; end if;
  insert into public.transfers(activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,recorded_by,on_behalf_of_participant_id,request_id,request_payload)
  values(p_activity_id,p_custodian,p_owner,'prepayment_return',p_amount,v_currency,p_occurred_at,v_user,p_behalf,p_request_id,v_payload)
  returning id into v_transfer;
  insert into public.transfer_components(activity_id,transfer_id,component_type,amount)
    values(p_activity_id,v_transfer,'prepayment_return',p_amount);
  perform private.assert_component_total(v_transfer);
  perform private.phase5_rebuild_after_transfer(p_activity_id);
  update public.activities as act set financial_version=act.financial_version+1 where act.id=p_activity_id returning act.financial_version into v_version;
  select coalesce(pa.balance,0) into v_balance from public.prepayment_accounts pa where pa.activity_id=p_activity_id
    and pa.owner_participant_id=p_owner and pa.custodian_participant_id=p_custodian and pa.currency=v_currency;
  v_result:=jsonb_build_object('transfer_id',v_transfer,'amount',p_amount,'currency',v_currency,
    'remaining_balance',coalesce(v_balance,0),'financial_version',v_version);
  update public.transfers set request_result=v_result where id=v_transfer;
  return query select v_transfer,p_amount,v_currency,coalesce(v_balance,0),v_version;
end;
$function$;


-- Replaced definition: private.void_prepayment_transfer_impl.
create or replace function private.void_prepayment_transfer_impl(tid uuid, reason text)
returns table(transfer_id uuid, voided boolean, financial_version bigint)
language plpgsql volatile security definer set search_path = ''
as $function$
declare aid uuid; rec uuid; v boolean; cr boolean; ar timestamptz; ver bigint; u uuid := (select auth.uid());
  v_type public.transfer_type; v_owner uuid; v_custodian uuid; v_currency character(3);
  v_source numeric(20,4); v_returned numeric(20,4); v_funded_after numeric(20,4);
begin
  if u is null then raise exception using errcode = '28000', message = 'authentication is required'; end if;
  if reason is null or length(btrim(reason)) = 0 then raise exception using errcode = '22023', message = 'void reason is required'; end if;
  select activity_id into aid from public.transfers where id = tid;
  if not found then raise exception using errcode = 'P0002', message = 'transfer was not found'; end if;
  perform private.lock_debt_projection_activity(aid);
  select t.recorded_by, t.is_voided, a.created_by = u, a.archived_at,
         t.type,t.from_participant_id,t.to_participant_id,t.currency
    into rec, v, cr, ar,v_type,v_owner,v_custodian,v_currency
  from public.transfers t join public.activities a on a.id = t.activity_id
  where t.id = tid and t.type in ('settlement','prepayment','prepayment_return','final_settlement')
    and not a.is_deleted for update of t,a;
  if not found then raise exception using errcode = 'P0002', message = 'financial transfer was not found'; end if;
  if ar is not null then raise exception using errcode = '55000', message = 'archived activity is read-only'; end if;
  if not exists(select 1 from public.activity_members where activity_id = aid and user_id = u) then raise exception using errcode = '42501', message = 'caller is not an activity member'; end if;
  if v then raise exception using errcode = '55000', message = 'transfer is already voided'; end if;
  if not cr and rec <> u then raise exception using errcode = '42501', message = 'member may void only a transfer they recorded'; end if;
  if v_type='prepayment'::public.transfer_type then
    select coalesce(sum(tc.amount),0)::numeric(20,4) into v_source
    from public.transfer_components tc where tc.transfer_id=tid and tc.component_type='prepayment';
    if v_source>0 then
      select coalesce(sum(tc.amount),0)::numeric(20,4) into v_returned
      from public.transfers rt join public.transfer_components tc on tc.transfer_id=rt.id
      where rt.activity_id=aid and not rt.is_voided and rt.type='prepayment_return'::public.transfer_type
        and rt.from_participant_id=v_custodian and rt.to_participant_id=v_owner
        and rt.currency=v_currency and tc.component_type='prepayment_return';
      select coalesce(sum(tc.amount),0)::numeric(20,4) into v_funded_after
      from public.transfers ft join public.transfer_components tc on tc.transfer_id=ft.id
      where ft.activity_id=aid and ft.id<>tid and not ft.is_voided and ft.type='prepayment'::public.transfer_type
        and ft.from_participant_id=v_owner and ft.to_participant_id=v_custodian
        and ft.currency=v_currency and tc.component_type='prepayment';
      if v_returned>v_funded_after then
        raise exception using errcode='23514',message='void active prepayment returns before voiding the source transfer';
      end if;
    end if;
  end if;
  update public.transfers set is_voided=true, voided_at=pg_catalog.now(), voided_by=u, void_reason=btrim(reason) where id=tid;
  perform private.phase5_rebuild_after_transfer(aid);
  update public.activities a set financial_version=a.financial_version+1 where a.id=aid returning a.financial_version into ver;
  return query select tid, true, ver;
end;
$function$;


-- Replaced definition: private.archive_activity_impl.
create or replace function private.archive_activity_impl(p_activity_id uuid)
returns table(activity_id uuid, archived boolean, changed boolean, archived_at timestamptz,
  total_debt numeric(20,1), total_prepayment numeric(20,1), completed boolean, has_unsettled boolean, warning text)
language plpgsql volatile security definer set search_path = ''
as $function$
declare u uuid := (select auth.uid()); creator uuid; deleted boolean; old_archived timestamptz; v_changed boolean; debt numeric; prepay numeric;
  base character(3); has_debt boolean; has_prepayment boolean; unsettled boolean;
begin
  if u is null then raise exception using errcode='28000', message='authentication is required'; end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  select a.created_by, a.is_deleted, a.archived_at into creator, deleted, old_archived
    from public.activities a where a.id=p_activity_id for update;
  if not found or deleted then raise exception using errcode='P0002', message='activity was not found'; end if;
  if not exists (select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=u) then
    raise exception using errcode='42501', message='caller is not an activity member';
  end if;
  if creator <> u then raise exception using errcode='42501', message='only the creator may archive an activity'; end if;
  select a.base_currency into base from public.activities a where a.id=p_activity_id;
  select coalesce(sum(b.amount),0)::numeric(20,1),coalesce(bool_or(coalesce(b.original_amount,b.amount)<>0),false)
    into debt,has_debt from public.bilateral_debts b where b.activity_id=p_activity_id;
  select coalesce(sum(pa.balance) filter(where pa.currency=base),0)::numeric(20,1),coalesce(bool_or(pa.balance<>0),false)
    into prepay,has_prepayment from public.prepayment_accounts pa where pa.activity_id=p_activity_id;
  unsettled:=has_debt or has_prepayment;
  v_changed := old_archived is null;
  if v_changed then update public.activities a set archived_at=pg_catalog.now() where a.id=p_activity_id returning a.archived_at into old_archived; end if;
  return query select p_activity_id, true, v_changed, old_archived, debt, prepay,
    not unsettled, unsettled,
    case when unsettled then 'activity has unsettled debt or prepayment balance' else null end;
end;
$function$;


-- Replaced definition: private.unarchive_activity_impl.
create or replace function private.unarchive_activity_impl(p_activity_id uuid)
returns table(activity_id uuid, archived boolean, changed boolean, archived_at timestamptz,
  total_debt numeric(20,1), total_prepayment numeric(20,1), completed boolean, has_unsettled boolean, warning text)
language plpgsql volatile security definer set search_path = ''
as $function$
declare u uuid := (select auth.uid()); creator uuid; deleted boolean; old_archived timestamptz; debt numeric; prepay numeric;
  base character(3); has_debt boolean; has_prepayment boolean; unsettled boolean;
begin
  if u is null then raise exception using errcode='28000', message='authentication is required'; end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  select a.created_by, a.is_deleted into creator, deleted from public.activities a where a.id=p_activity_id for update;
  if not found or deleted then raise exception using errcode='P0002', message='activity was not found'; end if;
  if not exists (select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=u) then
    raise exception using errcode='42501', message='caller is not an activity member';
  end if;
  if creator <> u then raise exception using errcode='42501', message='only the creator may unarchive an activity'; end if;
  select a.archived_at into old_archived from public.activities a where a.id=p_activity_id;
  update public.activities set archived_at=null where id=p_activity_id;
  select a.base_currency into base from public.activities a where a.id=p_activity_id;
  select coalesce(sum(b.amount),0)::numeric(20,1),coalesce(bool_or(coalesce(b.original_amount,b.amount)<>0),false)
    into debt,has_debt from public.bilateral_debts b where b.activity_id=p_activity_id;
  select coalesce(sum(pa.balance) filter(where pa.currency=base),0)::numeric(20,1),coalesce(bool_or(pa.balance<>0),false)
    into prepay,has_prepayment from public.prepayment_accounts pa where pa.activity_id=p_activity_id;
  unsettled:=has_debt or has_prepayment;
  return query select p_activity_id, false, (old_archived is not null), null::timestamptz, debt, prepay,
    not unsettled, unsettled,
    case when unsettled then 'activity has unsettled debt or prepayment balance' else null end;
end;
$function$;

-- Multi-currency completion is based on original-unit debt and positive
-- currency-specific prepayment balances. Base valuation remains a display
-- compatibility subtotal only.
create or replace view public.activity_financial_status
with (security_invoker = true) as
select a.id as activity_id,a.type,a.financial_version,a.archived_at,
  case when not coalesce(d.has_unsettled_debt,false) and not coalesce(p.has_balance,false) then 'completed' else 'active' end financial_status,
  (not coalesce(d.has_unsettled_debt,false) and not coalesce(p.has_balance,false)) completed,
  coalesce(d.total_debt,0)::numeric(20,1) total_debt,
  coalesce(p.total_prepayment,0)::numeric(20,4) total_prepayment,
  coalesce(d.has_unsettled_debt,false) has_unsettled_debt,
  coalesce(p.prepayment_by_currency,'[]'::jsonb) prepayment_by_currency
from public.activities a
left join (
  select b.activity_id,sum(b.amount)::numeric(20,1) total_debt,
    bool_or(coalesce(b.original_amount,b.amount)<>0) has_unsettled_debt
  from public.bilateral_debts b group by b.activity_id
) d on d.activity_id=a.id
left join (
  select pa.activity_id,
    sum(pa.balance) filter(where pa.currency=a.base_currency)::numeric(20,4) total_prepayment,
    bool_or(pa.balance<>0) has_balance,
    coalesce(jsonb_agg(jsonb_build_object('currency',pa.currency,'balance',pa.balance) order by pa.currency)
      filter(where pa.balance>0),'[]'::jsonb) prepayment_by_currency
  from public.prepayment_accounts pa join public.activities a on a.id=pa.activity_id
  group by pa.activity_id,a.base_currency
) p on p.activity_id=a.id
where not a.is_deleted;

create or replace view public.participant_financial_status
with (security_invoker = true) as
with base_debt as (
  select p.activity_id,p.id participant_id,
    coalesce(sum(b.amount) filter(where b.creditor_participant_id=p.id),0)::numeric(20,4) receivable,
    coalesce(sum(b.amount) filter(where b.debtor_participant_id=p.id),0)::numeric(20,4) payable
  from public.participants p left join public.bilateral_debts b
    on b.activity_id=p.activity_id and (b.creditor_participant_id=p.id or b.debtor_participant_id=p.id)
  where not p.is_deleted group by p.activity_id,p.id
), base_prepayment as (
  select p.activity_id,p.id participant_id,
    coalesce(sum(pa.balance) filter(where pa.owner_participant_id=p.id and pa.currency=a.base_currency),0)::numeric(20,4) receivable,
    coalesce(sum(pa.balance) filter(where pa.custodian_participant_id=p.id and pa.currency=a.base_currency),0)::numeric(20,4) payable
  from public.participants p join public.activities a on a.id=p.activity_id
  left join public.prepayment_accounts pa on pa.activity_id=p.activity_id
    and (pa.owner_participant_id=p.id or pa.custodian_participant_id=p.id)
  where not p.is_deleted group by p.activity_id,p.id
), base_totals as (
  select d.activity_id,d.participant_id,(d.receivable+pp.receivable)::numeric(20,4) receivable,
    (d.payable+pp.payable)::numeric(20,4) payable
  from base_debt d join base_prepayment pp using(activity_id,participant_id)
), currency_facts as (
  select b.activity_id,b.creditor_participant_id participant_id,b.currency,
    coalesce(b.original_amount,b.amount)::numeric(20,4) receivable,0::numeric(20,4) payable
  from public.bilateral_debts b
  union all
  select b.activity_id,b.debtor_participant_id,b.currency,0::numeric(20,4),
    coalesce(b.original_amount,b.amount)::numeric(20,4)
  from public.bilateral_debts b
  union all
  select pa.activity_id,pa.owner_participant_id,pa.currency,pa.balance::numeric(20,4),0::numeric(20,4)
  from public.prepayment_accounts pa where pa.balance<>0
  union all
  select pa.activity_id,pa.custodian_participant_id,pa.currency,0::numeric(20,4),pa.balance::numeric(20,4)
  from public.prepayment_accounts pa where pa.balance<>0
), currency_totals as (
  select f.activity_id,f.participant_id,f.currency,sum(f.receivable)::numeric(20,4) receivable,
    sum(f.payable)::numeric(20,4) payable
  from currency_facts f group by f.activity_id,f.participant_id,f.currency
), currency_json as (
  select c.activity_id,c.participant_id,
    coalesce(jsonb_agg(jsonb_build_object('currency',c.currency,'receivable',c.receivable,
      'payable',c.payable,'net_balance',(c.receivable-c.payable)::numeric(20,4)) order by c.currency)
      filter(where c.receivable<>0 or c.payable<>0),'[]'::jsonb) balance_by_currency
  from currency_totals c group by c.activity_id,c.participant_id
), unsettled as (
  select p.activity_id,p.id participant_id,
    exists(select 1 from public.bilateral_debts b where b.activity_id=p.activity_id
      and (b.creditor_participant_id=p.id or b.debtor_participant_id=p.id)
      and coalesce(b.original_amount,b.amount)<>0)
    or exists(select 1 from public.prepayment_accounts pa where pa.activity_id=p.activity_id
      and (pa.owner_participant_id=p.id or pa.custodian_participant_id=p.id) and pa.balance<>0) has_unsettled
  from public.participants p where not p.is_deleted
)
select p.activity_id,p.id participant_id,p.participant_order,
  coalesce(t.receivable,0)::numeric(20,4) receivable,coalesce(t.payable,0)::numeric(20,4) payable,
  (coalesce(t.receivable,0)-coalesce(t.payable,0))::numeric(20,4) net_balance,
  case when coalesce(u.has_unsettled,false) then 'active' else 'completed' end financial_status,
  not coalesce(u.has_unsettled,false) completed,
  coalesce(cj.balance_by_currency,'[]'::jsonb) balance_by_currency
from public.participants p
left join base_totals t on t.activity_id=p.activity_id and t.participant_id=p.id
left join currency_json cj on cj.activity_id=p.activity_id and cj.participant_id=p.id
left join unsettled u on u.activity_id=p.activity_id and u.participant_id=p.id
where not p.is_deleted;

revoke all on public.activity_financial_status,public.participant_financial_status from public,anon,authenticated;
grant select on public.activity_financial_status,public.participant_financial_status to authenticated;

-- Base valuation may round to zero for a nonzero foreign-currency amount.
alter table public.prepayment_usages drop constraint if exists prepayment_usages_audit_amounts_positive;
alter table public.prepayment_usages add constraint prepayment_usages_audit_amounts_positive
  check (prepayment_amount>0 and debt_amount>0 and base_amount>=0 and bill_fx_rate>0);
alter table public.final_settlement_paths drop constraint if exists final_settlement_paths_currency_valid;
alter table public.final_settlement_paths add constraint final_settlement_paths_currency_valid
  check (path_currency ~ '^[A-Z]{3}$' and original_amount>0 and
    ((component_type='settlement' and fx_rate>0 and base_amount>=0) or
     (component_type='prepayment_return' and
       ((fx_rate is null and base_amount is null) or (fx_rate=1 and base_amount=original_amount)))));

comment on column public.final_settlement_paths.fx_rate is
  'Expense-debt snapshot for settlement paths; NULL on new prepayment returns. Legacy prepayment-return rows may contain a structural 1 placeholder that is not a currency conversion.';
comment on column public.final_settlement_paths.base_amount is
  'Base-unit settlement valuation; NULL on new prepayment-return paths because prepayments have no FX valuation.';

alter table public.expense_debts drop constraint if exists expense_debts_amount_check;
alter table public.expense_debts add constraint expense_debts_amount_micro_residual_valid
  check (amount>0 or (amount=0 and original_amount is not null and original_amount>0));
alter table public.bilateral_debts drop constraint if exists bilateral_debts_amount_nonnegative;
alter table public.bilateral_debts add constraint bilateral_debts_amount_micro_residual_valid
  check (amount>0 or (amount=0 and original_amount is not null and original_amount>0));
alter table public.transfer_allocations drop constraint if exists transfer_allocations_amount_nonnegative;
alter table public.transfer_allocations add constraint transfer_allocations_amount_micro_residual_valid
  check (amount>0 or (amount=0 and original_amount is not null and original_amount>0));

commit;
