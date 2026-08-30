-- Phase 2C: normalize payment and split rows into the activity base currency.
-- Lock the parent first because every supported write path locks/writes the
-- expense before replacing children. This prevents old RPC calls from racing
-- the backfill or deadlocking while the child tables are altered.
begin;

lock table public.expenses in share row exclusive mode;
lock table public.payments, public.splits in access exclusive mode;

alter table public.payments
  add column base_amount numeric(20,1);

alter table public.splits
  add column base_amount numeric(20,1);

-- Payments and manual splits round each row independently. The complete
-- rounding delta is assigned to the deterministic last participant so the
-- normalized children conserve the already-persisted expense base_amount.
with ranked_payments as (
  select
    pay.id,
    pay.expense_id,
    e.base_amount as expense_base_amount,
    pg_catalog.round(pay.amount * e.fx_rate, 1) as rounded_base_amount,
    pg_catalog.row_number() over (
      partition by pay.expense_id
      order by p.participant_order, pay.participant_id
    ) as allocation_index,
    pg_catalog.count(*) over (
      partition by pay.expense_id
    ) as allocation_count
  from public.payments as pay
  join public.expenses as e on e.id = pay.expense_id
  join public.participants as p on p.id = pay.participant_id
), payment_allocations as (
  select
    id,
    case
      when allocation_index = allocation_count then
        expense_base_amount - coalesce(
          pg_catalog.sum(rounded_base_amount) over (
            partition by expense_id
            order by allocation_index
            rows between unbounded preceding and 1 preceding
          ),
          0
        )
      else rounded_base_amount
    end as base_amount
  from ranked_payments
)
update public.payments as pay
set base_amount = allocation.base_amount
from payment_allocations as allocation
where allocation.id = pay.id;

-- AA retains its existing four-decimal original-currency algorithm. Its base
-- amounts are instead divided directly from expense.base_amount in 0.1 units:
-- truncate toward zero for all but the last row and place the tail last. The
-- same formula handles positive, negative, and zero normalized values.
with ranked_splits as (
  select
    s.id,
    s.expense_id,
    e.base_amount as expense_base_amount,
    case
      when e.split_method = 'aa'::public.expense_split_method then
        pg_catalog.round(
          pg_catalog.trunc(
            (e.base_amount * 10)
            / pg_catalog.count(*) over (partition by s.expense_id)
          ) / 10,
          1
        )
      else pg_catalog.round(s.amount * e.fx_rate, 1)
    end as rounded_base_amount,
    pg_catalog.row_number() over (
      partition by s.expense_id
      order by p.participant_order, s.participant_id
    ) as allocation_index,
    pg_catalog.count(*) over (
      partition by s.expense_id
    ) as allocation_count
  from public.splits as s
  join public.expenses as e on e.id = s.expense_id
  join public.participants as p on p.id = s.participant_id
), split_allocations as (
  select
    id,
    case
      when allocation_index = allocation_count then
        expense_base_amount - coalesce(
          pg_catalog.sum(rounded_base_amount) over (
            partition by expense_id
            order by allocation_index
            rows between unbounded preceding and 1 preceding
          ),
          0
        )
      else rounded_base_amount
    end as base_amount
  from ranked_splits
)
update public.splits as s
set base_amount = allocation.base_amount
from split_allocations as allocation
where allocation.id = s.id;

-- Fail atomically before SET NOT NULL if any legacy child could not be filled
-- or if a populated child group does not strictly conserve its parent. Empty
-- child groups contain no value to backfill and remain possible only for
-- privileged legacy writes; all supported RPC writes require both groups.
do $validation$
begin
  if exists (select 1 from public.payments where base_amount is null) then
    raise exception 'payment base_amount backfill left null rows'
      using errcode = '23502';
  end if;

  if exists (select 1 from public.splits where base_amount is null) then
    raise exception 'split base_amount backfill left null rows'
      using errcode = '23502';
  end if;

  if exists (
    select 1
    from public.payments as pay
    join public.expenses as e on e.id = pay.expense_id
    group by pay.expense_id, e.base_amount
    having pg_catalog.sum(pay.base_amount) is distinct from e.base_amount
  ) then
    raise exception 'payment base_amount backfill does not conserve expense base_amount'
      using errcode = '23514';
  end if;

  if exists (
    select 1
    from public.splits as s
    join public.expenses as e on e.id = s.expense_id
    group by s.expense_id, e.base_amount
    having pg_catalog.sum(s.base_amount) is distinct from e.base_amount
  ) then
    raise exception 'split base_amount backfill does not conserve expense base_amount'
      using errcode = '23514';
  end if;
end;
$validation$;

alter table public.payments
  alter column base_amount set not null;

alter table public.splits
  alter column base_amount set not null;

create or replace function private.replace_expense_children(
  p_expense_id uuid,
  p_activity_id uuid,
  p_original_amount numeric(20,4),
  p_split_method public.expense_split_method,
  p_payments jsonb,
  p_manual_splits jsonb,
  p_aa_participant_ids uuid[]
)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_user_id uuid;
  v_db_activity_id uuid;
  v_db_amount numeric(20,4);
  v_db_fx_rate numeric(20,10);
  v_db_base_amount numeric(20,1);
  v_db_split_method public.expense_split_method;
  v_item jsonb;
  v_participant_id uuid;
  v_last_participant_id uuid;
  v_amount numeric(20,4);
  v_child_base_amount numeric(20,1);
  v_seen_participants uuid[];
  v_payment_total numeric;
  v_split_total numeric;
  v_base_total numeric;
  v_extra_keys integer;
  v_participant_count integer;
  v_index integer;
  v_total_units numeric;
  v_base_units numeric;
  v_remainder numeric;
  v_extra_count integer;
  v_units numeric;
  v_split_amount numeric(20,4);
  v_aa_base_units numeric;
  v_aa_base_amount numeric(20,1);
begin
  v_user_id := (select auth.uid());
  if v_user_id is null then
    raise exception using errcode = '28000', message = 'authentication is required';
  end if;

  select e.original_amount, e.fx_rate, e.base_amount, e.split_method, lu.activity_id
    into v_db_amount, v_db_fx_rate, v_db_base_amount, v_db_split_method, v_db_activity_id
  from public.expenses as e
  join public.ledger_units as lu on lu.id = e.ledger_unit_id
  join public.activities as a on a.id = lu.activity_id
  where e.id = p_expense_id
    and not e.is_deleted
    and not lu.is_deleted
    and not a.is_deleted
  for update of e;

  if not found
     or v_db_activity_id is distinct from p_activity_id
     or v_db_amount is distinct from p_original_amount
     or v_db_split_method is distinct from p_split_method then
    raise exception using errcode = '22023', message = 'expense payload does not match its activity';
  end if;

  if not exists (
    select 1
    from public.activity_members as am
    where am.activity_id = p_activity_id
      and am.user_id = v_user_id
  ) then
    raise exception using errcode = '42501', message = 'caller is not an activity member';
  end if;

  if p_payments is null or pg_catalog.jsonb_typeof(p_payments) <> 'array' then
    raise exception using errcode = '22023', message = 'payments must be a JSON array';
  end if;

  v_payment_total := 0;
  v_seen_participants := '{}'::uuid[];
  for v_item in
    select value from pg_catalog.jsonb_array_elements(p_payments) as elements(value)
  loop
    if pg_catalog.jsonb_typeof(v_item) <> 'object'
       or not pg_catalog.jsonb_exists(v_item, 'participant_id')
       or not pg_catalog.jsonb_exists(v_item, 'amount') then
      raise exception using errcode = '22023', message = 'each payment must contain participant_id and amount';
    end if;

    select count(*) into v_extra_keys
    from pg_catalog.jsonb_object_keys(v_item) as object_keys(key)
    where object_keys.key not in ('participant_id', 'amount');
    if v_extra_keys <> 0 then
      raise exception using errcode = '22023', message = 'payment contains an unsupported field';
    end if;

    if pg_catalog.jsonb_typeof(v_item -> 'participant_id') <> 'string'
       or pg_catalog.jsonb_typeof(v_item -> 'amount') not in ('number', 'string') then
      raise exception using errcode = '22023', message = 'payment fields have invalid types';
    end if;

    v_participant_id := (v_item ->> 'participant_id')::uuid;
    v_amount := (v_item ->> 'amount')::numeric(20,4);
    if v_amount is null or v_amount = 0 then
      raise exception using errcode = '22023', message = 'payment amount must be non-zero';
    end if;
    if (v_amount > 0) is distinct from (p_original_amount > 0) then
      raise exception using errcode = '22023', message = 'payment sign must match expense sign';
    end if;
    if pg_catalog.array_position(v_seen_participants, v_participant_id) is not null then
      raise exception using errcode = '23505', message = 'a participant may pay only once';
    end if;
    if not exists (
      select 1
      from public.participants as p
      where p.id = v_participant_id
        and p.activity_id = p_activity_id
        and not p.is_deleted
    ) then
      raise exception using errcode = '22023', message = 'payment participant is not active in this activity';
    end if;

    v_seen_participants := pg_catalog.array_append(v_seen_participants, v_participant_id);
    v_payment_total := v_payment_total + v_amount;
    v_child_base_amount := pg_catalog.round(v_amount * v_db_fx_rate, 1);
    insert into public.payments (expense_id, participant_id, amount, base_amount)
    values (p_expense_id, v_participant_id, v_amount, v_child_base_amount);
  end loop;

  if v_payment_total <> p_original_amount then
    raise exception using errcode = '22023', message = 'payment total must equal original amount';
  end if;

  select pay.participant_id
    into v_last_participant_id
  from public.payments as pay
  join public.participants as p on p.id = pay.participant_id
  where pay.expense_id = p_expense_id
  order by p.participant_order desc, pay.participant_id desc
  limit 1;

  select pg_catalog.sum(pay.base_amount)
    into v_base_total
  from public.payments as pay
  where pay.expense_id = p_expense_id;

  update public.payments as pay
  set base_amount = pay.base_amount + (v_db_base_amount - v_base_total)
  where pay.expense_id = p_expense_id
    and pay.participant_id = v_last_participant_id;

  select pg_catalog.sum(pay.base_amount)
    into v_base_total
  from public.payments as pay
  where pay.expense_id = p_expense_id;
  if v_base_total is distinct from v_db_base_amount then
    raise exception using errcode = '23514', message = 'payment base total must equal expense base amount';
  end if;

  if p_split_method = 'manual' then
    if p_manual_splits is null or pg_catalog.jsonb_typeof(p_manual_splits) <> 'array' then
      raise exception using errcode = '22023', message = 'manual_splits must be a JSON array';
    end if;
    if p_aa_participant_ids is not null
       and pg_catalog.array_length(p_aa_participant_ids, 1) is not null then
      raise exception using errcode = '22023', message = 'AA participants are not valid for manual splits';
    end if;

    v_split_total := 0;
    v_seen_participants := '{}'::uuid[];
    for v_item in
      select value from pg_catalog.jsonb_array_elements(p_manual_splits) as elements(value)
    loop
      if pg_catalog.jsonb_typeof(v_item) <> 'object'
         or not pg_catalog.jsonb_exists(v_item, 'participant_id')
         or not pg_catalog.jsonb_exists(v_item, 'amount') then
        raise exception using errcode = '22023', message = 'each split must contain participant_id and amount';
      end if;

      select count(*) into v_extra_keys
      from pg_catalog.jsonb_object_keys(v_item) as object_keys(key)
      where object_keys.key not in ('participant_id', 'amount');
      if v_extra_keys <> 0 then
        raise exception using errcode = '22023', message = 'split contains an unsupported field';
      end if;

      if pg_catalog.jsonb_typeof(v_item -> 'participant_id') <> 'string'
         or pg_catalog.jsonb_typeof(v_item -> 'amount') not in ('number', 'string') then
        raise exception using errcode = '22023', message = 'split fields have invalid types';
      end if;

      v_participant_id := (v_item ->> 'participant_id')::uuid;
      v_amount := (v_item ->> 'amount')::numeric(20,4);
      if v_amount is null or v_amount = 0 then
        raise exception using errcode = '22023', message = 'split amount must be non-zero';
      end if;
      if (v_amount > 0) is distinct from (p_original_amount > 0) then
        raise exception using errcode = '22023', message = 'split sign must match expense sign';
      end if;
      if pg_catalog.array_position(v_seen_participants, v_participant_id) is not null then
        raise exception using errcode = '23505', message = 'a participant may be split only once';
      end if;
      if not exists (
        select 1
        from public.participants as p
        where p.id = v_participant_id
          and p.activity_id = p_activity_id
          and not p.is_deleted
      ) then
        raise exception using errcode = '22023', message = 'split participant is not active in this activity';
      end if;

      v_seen_participants := pg_catalog.array_append(v_seen_participants, v_participant_id);
      v_split_total := v_split_total + v_amount;
      v_child_base_amount := pg_catalog.round(v_amount * v_db_fx_rate, 1);
      insert into public.splits (expense_id, participant_id, amount, base_amount)
      values (p_expense_id, v_participant_id, v_amount, v_child_base_amount);
    end loop;

    if v_split_total <> p_original_amount then
      raise exception using errcode = '22023', message = 'manual split total must equal original amount';
    end if;

    select s.participant_id
      into v_last_participant_id
    from public.splits as s
    join public.participants as p on p.id = s.participant_id
    where s.expense_id = p_expense_id
    order by p.participant_order desc, s.participant_id desc
    limit 1;

    select pg_catalog.sum(s.base_amount)
      into v_base_total
    from public.splits as s
    where s.expense_id = p_expense_id;

    update public.splits as s
    set base_amount = s.base_amount + (v_db_base_amount - v_base_total)
    where s.expense_id = p_expense_id
      and s.participant_id = v_last_participant_id;

    select pg_catalog.sum(s.base_amount)
      into v_base_total
    from public.splits as s
    where s.expense_id = p_expense_id;
    if v_base_total is distinct from v_db_base_amount then
      raise exception using errcode = '23514', message = 'manual split base total must equal expense base amount';
    end if;
  elsif p_split_method = 'aa' then
    if p_aa_participant_ids is null
       or pg_catalog.array_length(p_aa_participant_ids, 1) is null
       or pg_catalog.array_length(p_aa_participant_ids, 1) = 0 then
      raise exception using errcode = '22023', message = 'AA requires at least one participant';
    end if;
    if p_manual_splits is null
       or pg_catalog.jsonb_typeof(p_manual_splits) <> 'array'
       or pg_catalog.jsonb_array_length(p_manual_splits) <> 0 then
      raise exception using errcode = '22023', message = 'manual_splits must be empty for AA';
    end if;

    v_participant_count := pg_catalog.array_length(p_aa_participant_ids, 1);
    v_seen_participants := '{}'::uuid[];
    v_index := 1;
    while v_index <= v_participant_count loop
      v_participant_id := p_aa_participant_ids[v_index];
      if v_participant_id is null then
        raise exception using errcode = '22023', message = 'AA participant cannot be null';
      end if;
      if pg_catalog.array_position(v_seen_participants, v_participant_id) is not null then
        raise exception using errcode = '23505', message = 'AA participant list contains duplicates';
      end if;
      if not exists (
        select 1
        from public.participants as p
        where p.id = v_participant_id
          and p.activity_id = p_activity_id
          and not p.is_deleted
      ) then
        raise exception using errcode = '22023', message = 'AA participant is not active in this activity';
      end if;
      v_seen_participants := pg_catalog.array_append(v_seen_participants, v_participant_id);
      v_index := v_index + 1;
    end loop;

    v_total_units := p_original_amount * 10000;
    v_base_units := pg_catalog.trunc(v_total_units / v_participant_count);
    v_remainder := v_total_units - (v_base_units * v_participant_count);
    v_extra_count := pg_catalog.abs(v_remainder)::integer;
    v_aa_base_units := pg_catalog.trunc((v_db_base_amount * 10) / v_participant_count);
    v_aa_base_amount := pg_catalog.round(v_aa_base_units / 10, 1);
    v_split_total := 0;
    v_base_total := 0;
    v_index := 0;

    for v_participant_id in
      select p.id
      from public.participants as p
      where p.activity_id = p_activity_id
        and p.id = any(p_aa_participant_ids)
        and not p.is_deleted
      order by p.participant_order, p.id
    loop
      v_index := v_index + 1;
      v_units := v_base_units;
      if v_index <= v_extra_count then
        if v_remainder > 0 then
          v_units := v_units + 1;
        else
          v_units := v_units - 1;
        end if;
      end if;
      v_split_amount := pg_catalog.round(v_units / 10000, 4);
      if v_index < v_participant_count then
        v_child_base_amount := v_aa_base_amount;
      else
        v_child_base_amount := v_db_base_amount - (v_aa_base_amount * (v_participant_count - 1));
      end if;
      v_split_total := v_split_total + v_split_amount;
      v_base_total := v_base_total + v_child_base_amount;
      insert into public.splits (expense_id, participant_id, amount, base_amount)
      values (p_expense_id, v_participant_id, v_split_amount, v_child_base_amount);
    end loop;

    if v_index <> v_participant_count or v_split_total <> p_original_amount then
      raise exception using errcode = '22023', message = 'AA split total must equal original amount';
    end if;
    if v_base_total is distinct from v_db_base_amount then
      raise exception using errcode = '23514', message = 'AA split base total must equal expense base amount';
    end if;
  else
    raise exception using errcode = '22023', message = 'unsupported split method';
  end if;
end;
$function$;

-- CREATE OR REPLACE retains existing ownership and grants. Reassert the
-- established private-helper boundary explicitly without widening it.
revoke all on function private.replace_expense_children(
  uuid, uuid, numeric(20,4), public.expense_split_method, jsonb, jsonb, uuid[]
) from public, anon, authenticated;
grant execute on function private.replace_expense_children(
  uuid, uuid, numeric(20,4), public.expense_split_method, jsonb, jsonb, uuid[]
) to authenticated;

commit;
