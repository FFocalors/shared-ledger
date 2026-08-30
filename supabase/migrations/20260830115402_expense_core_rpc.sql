create or replace function private.can_read_expense(p_expense_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select (select auth.uid()) is not null
    and exists (
      select 1
      from public.expenses as e
      join public.ledger_units as lu on lu.id = e.ledger_unit_id
      join public.activities as a on a.id = lu.activity_id
      join public.activity_members as am on am.activity_id = a.id
      where e.id = $1
        and not e.is_deleted
        and not lu.is_deleted
        and not a.is_deleted
        and am.user_id = (select auth.uid())
    );
$function$;

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
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_user_id uuid;
  v_activity_id uuid;
  v_base_currency character(3);
  v_multi_currency_enabled boolean;
  v_title text;
  v_original_currency character(3);
  v_base_amount numeric(20,1);
  v_expense_id uuid;
  v_version bigint;
begin
  v_user_id := (select auth.uid());
  if v_user_id is null then
    raise exception using errcode = '28000', message = 'authentication is required';
  end if;

  v_title := pg_catalog.btrim(p_title);
  if v_title is null or pg_catalog.length(v_title) = 0 then
    raise exception using errcode = '22023', message = 'expense title is required';
  end if;
  if p_original_amount is null or p_original_amount = 0 then
    raise exception using errcode = '22023', message = 'original amount must be non-zero';
  end if;
  if p_original_currency is null then
    raise exception using errcode = '22023', message = 'original currency is required';
  end if;
  v_original_currency := pg_catalog.upper(pg_catalog.btrim(p_original_currency));
  if v_original_currency is null or v_original_currency !~ '^[A-Z]{3}$' then
    raise exception using errcode = '22023', message = 'original currency must be three uppercase letters';
  end if;
  if p_fx_rate is null or p_fx_rate <= 0 then
    raise exception using errcode = '22023', message = 'FX rate must be positive';
  end if;
  if p_split_method is null or p_occurred_at is null then
    raise exception using errcode = '22023', message = 'split method and occurred_at are required';
  end if;

  select lu.activity_id, a.base_currency, a.multi_currency_enabled
    into v_activity_id, v_base_currency, v_multi_currency_enabled
  from public.ledger_units as lu
  join public.activities as a on a.id = lu.activity_id
  where lu.id = p_ledger_unit_id
    and not lu.is_deleted
    and not a.is_deleted;
  if not found then
    raise exception using errcode = '42501', message = 'ledger unit is not available';
  end if;
  if not exists (
    select 1
    from public.activity_members as am
    where am.activity_id = v_activity_id
      and am.user_id = v_user_id
  ) then
    raise exception using errcode = '42501', message = 'caller is not an activity member';
  end if;

  if v_original_currency = v_base_currency then
    if p_fx_rate <> 1 then
      raise exception using errcode = '22023', message = 'base-currency expenses must use FX rate 1';
    end if;
  elsif not v_multi_currency_enabled then
    raise exception using errcode = '22023', message = 'foreign currency is disabled for this activity';
  end if;

  if p_original_expense_id is not null then
    perform 1
    from public.expenses as original_expense
    join public.ledger_units as original_unit
      on original_unit.id = original_expense.ledger_unit_id
    join public.activities as original_activity
      on original_activity.id = original_unit.activity_id
    where original_expense.id = p_original_expense_id
      and original_unit.activity_id = v_activity_id
      and not original_expense.is_deleted
      and not original_unit.is_deleted
      and not original_activity.is_deleted
    for key share of original_expense;
    if not found then
      raise exception using errcode = '22023', message = 'refund reference is not an active expense in this activity';
    end if;
  end if;

  v_base_amount := pg_catalog.round(p_original_amount * p_fx_rate, 1);
  insert into public.expenses (
    ledger_unit_id,
    title,
    original_amount,
    original_currency,
    fx_rate,
    base_amount,
    split_method,
    occurred_at,
    note,
    original_expense_id,
    created_by,
    updated_by
  )
  values (
    p_ledger_unit_id,
    v_title,
    p_original_amount,
    v_original_currency,
    p_fx_rate,
    v_base_amount,
    p_split_method,
    p_occurred_at,
    p_note,
    p_original_expense_id,
    v_user_id,
    v_user_id
  )
  returning public.expenses.id, public.expenses.base_amount, public.expenses.version
    into v_expense_id, v_base_amount, v_version;

  perform private.replace_expense_children(
    v_expense_id,
    v_activity_id,
    p_original_amount,
    p_split_method,
    p_payments,
    p_manual_splits,
    p_aa_participant_ids
  );

  return query select v_expense_id, v_base_amount, v_version;
end;
$function$;

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
  v_db_split_method public.expense_split_method;
  v_item jsonb;
  v_participant_id uuid;
  v_amount numeric(20,4);
  v_seen_participants uuid[];
  v_payment_total numeric;
  v_split_total numeric;
  v_extra_keys integer;
  v_participant_count integer;
  v_index integer;
  v_total_units numeric;
  v_base_units numeric;
  v_remainder numeric;
  v_extra_count integer;
  v_units numeric;
  v_split_amount numeric(20,4);
begin
  v_user_id := (select auth.uid());
  if v_user_id is null then
    raise exception using errcode = '28000', message = 'authentication is required';
  end if;

  select e.original_amount, e.split_method, lu.activity_id
    into v_db_amount, v_db_split_method, v_db_activity_id
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
    insert into public.payments (expense_id, participant_id, amount)
    values (p_expense_id, v_participant_id, v_amount);
  end loop;

  if v_payment_total <> p_original_amount then
    raise exception using errcode = '22023', message = 'payment total must equal original amount';
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
      insert into public.splits (expense_id, participant_id, amount)
      values (p_expense_id, v_participant_id, v_amount);
    end loop;

    if v_split_total <> p_original_amount then
      raise exception using errcode = '22023', message = 'manual split total must equal original amount';
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
    v_split_total := 0;
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
      v_split_total := v_split_total + v_split_amount;
      insert into public.splits (expense_id, participant_id, amount)
      values (p_expense_id, v_participant_id, v_split_amount);
    end loop;

    if v_index <> v_participant_count or v_split_total <> p_original_amount then
      raise exception using errcode = '22023', message = 'AA split total must equal original amount';
    end if;
  else
    raise exception using errcode = '22023', message = 'unsupported split method';
  end if;
end;
$function$;

create or replace function private.update_expense_impl(
  p_expense_id uuid,
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
returns table(updated_expense_id uuid, base_amount numeric(20,1), version bigint)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_user_id uuid;
  v_activity_id uuid;
  v_existing_activity_id uuid;
  v_base_currency character(3);
  v_multi_currency_enabled boolean;
  v_title text;
  v_original_currency character(3);
  v_base_amount numeric(20,1);
  v_version bigint;
  v_existing_deleted boolean;
begin
  v_user_id := (select auth.uid());
  if v_user_id is null then
    raise exception using errcode = '28000', message = 'authentication is required';
  end if;

  v_title := pg_catalog.btrim(p_title);
  if v_title is null or pg_catalog.length(v_title) = 0 then
    raise exception using errcode = '22023', message = 'expense title is required';
  end if;
  if p_original_amount is null or p_original_amount = 0 then
    raise exception using errcode = '22023', message = 'original amount must be non-zero';
  end if;
  if p_original_currency is null then
    raise exception using errcode = '22023', message = 'original currency is required';
  end if;
  v_original_currency := pg_catalog.upper(pg_catalog.btrim(p_original_currency));
  if v_original_currency is null or v_original_currency !~ '^[A-Z]{3}$' then
    raise exception using errcode = '22023', message = 'original currency must be three uppercase letters';
  end if;
  if p_fx_rate is null or p_fx_rate <= 0 then
    raise exception using errcode = '22023', message = 'FX rate must be positive';
  end if;
  if p_split_method is null or p_occurred_at is null then
    raise exception using errcode = '22023', message = 'split method and occurred_at are required';
  end if;

  select e.is_deleted, lu.activity_id
    into v_existing_deleted, v_existing_activity_id
  from public.expenses as e
  join public.ledger_units as lu on lu.id = e.ledger_unit_id
  join public.activities as a on a.id = lu.activity_id
  where e.id = p_expense_id
    and not lu.is_deleted
    and not a.is_deleted
  for update of e;
  if not found then
    raise exception using errcode = 'P0002', message = 'expense was not found';
  end if;
  if v_existing_deleted then
    raise exception using errcode = '22023', message = 'deleted expenses cannot be updated';
  end if;
  if not exists (
    select 1
    from public.activity_members as am
    where am.activity_id = v_existing_activity_id
      and am.user_id = v_user_id
  ) then
    raise exception using errcode = '42501', message = 'caller is not an activity member';
  end if;

  select lu.activity_id, a.base_currency, a.multi_currency_enabled
    into v_activity_id, v_base_currency, v_multi_currency_enabled
  from public.ledger_units as lu
  join public.activities as a on a.id = lu.activity_id
  where lu.id = p_ledger_unit_id
    and not lu.is_deleted
    and not a.is_deleted;
  if not found or v_activity_id is distinct from v_existing_activity_id then
    raise exception using errcode = '22023', message = 'expense must stay in its activity';
  end if;

  if v_original_currency = v_base_currency then
    if p_fx_rate <> 1 then
      raise exception using errcode = '22023', message = 'base-currency expenses must use FX rate 1';
    end if;
  elsif not v_multi_currency_enabled then
    raise exception using errcode = '22023', message = 'foreign currency is disabled for this activity';
  end if;

  if p_original_expense_id is not null then
    perform 1
    from public.expenses as original_expense
    join public.ledger_units as original_unit
      on original_unit.id = original_expense.ledger_unit_id
    join public.activities as original_activity
      on original_activity.id = original_unit.activity_id
    where original_expense.id = p_original_expense_id
      and original_unit.activity_id = v_existing_activity_id
      and p_original_expense_id <> p_expense_id
      and not original_expense.is_deleted
      and not original_unit.is_deleted
      and not original_activity.is_deleted
    for key share of original_expense;
    if not found then
      raise exception using errcode = '22023', message = 'refund reference is not an active expense in this activity';
    end if;
  end if;

  v_base_amount := pg_catalog.round(p_original_amount * p_fx_rate, 1);
  update public.expenses as e
  set ledger_unit_id = p_ledger_unit_id,
      title = v_title,
      original_amount = p_original_amount,
      original_currency = v_original_currency,
      fx_rate = p_fx_rate,
      base_amount = v_base_amount,
      split_method = p_split_method,
      occurred_at = p_occurred_at,
      note = p_note,
      original_expense_id = p_original_expense_id,
      updated_by = v_user_id,
      version = e.version + 1
  where e.id = p_expense_id
  returning e.base_amount, e.version into v_base_amount, v_version;

  delete from public.payments where expense_id = p_expense_id;
  delete from public.splits where expense_id = p_expense_id;
  perform private.replace_expense_children(
    p_expense_id,
    v_existing_activity_id,
    p_original_amount,
    p_split_method,
    p_payments,
    p_manual_splits,
    p_aa_participant_ids
  );

  return query select p_expense_id, v_base_amount, v_version;
end;
$function$;

create or replace function private.delete_expense_impl(p_expense_id uuid)
returns table(deleted_expense_id uuid, deleted boolean, version bigint)
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_user_id uuid;
  v_activity_id uuid;
  v_is_deleted boolean;
  v_version bigint;
begin
  v_user_id := (select auth.uid());
  if v_user_id is null then
    raise exception using errcode = '28000', message = 'authentication is required';
  end if;

  select e.is_deleted, e.version, lu.activity_id
    into v_is_deleted, v_version, v_activity_id
  from public.expenses as e
  join public.ledger_units as lu on lu.id = e.ledger_unit_id
  join public.activities as a on a.id = lu.activity_id
  where e.id = p_expense_id
    and not lu.is_deleted
    and not a.is_deleted
  for update of e;
  if not found then
    raise exception using errcode = 'P0002', message = 'expense was not found';
  end if;
  if not exists (
    select 1
    from public.activity_members as am
    where am.activity_id = v_activity_id
      and am.user_id = v_user_id
  ) then
    raise exception using errcode = '42501', message = 'caller is not an activity member';
  end if;
  if v_is_deleted then
    return query select p_expense_id, false, v_version;
    return;
  end if;

  if exists (
    select 1
    from public.expenses as active_refund
    where active_refund.original_expense_id = p_expense_id
      and not active_refund.is_deleted
  ) then
    raise exception using errcode = '23514', message = 'cannot delete expense while active refunds reference it';
  end if;

  update public.expenses as e
  set is_deleted = true,
      deleted_at = pg_catalog.now(),
      deleted_by = v_user_id,
      updated_by = v_user_id,
      version = e.version + 1
  where e.id = p_expense_id
  returning e.version into v_version;
  return query select p_expense_id, true, v_version;
end;
$function$;

create or replace function public.create_expense(
  ledger_unit_id uuid,
  title text,
  original_amount numeric(20,4),
  original_currency character(3),
  fx_rate numeric(20,10),
  split_method public.expense_split_method,
  payments jsonb default '[]'::jsonb,
  manual_splits jsonb default '[]'::jsonb,
  aa_participant_ids uuid[] default '{}'::uuid[],
  occurred_at timestamptz default pg_catalog.now(),
  note text default null,
  original_expense_id uuid default null
)
returns table(expense_id uuid, base_amount numeric(20,1), version bigint)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select created.expense_id, created.base_amount, created.version
  from private.create_expense_impl(
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
  ) as created;
$function$;

create or replace function public.update_expense(
  expense_id uuid,
  ledger_unit_id uuid,
  title text,
  original_amount numeric(20,4),
  original_currency character(3),
  fx_rate numeric(20,10),
  split_method public.expense_split_method,
  payments jsonb default '[]'::jsonb,
  manual_splits jsonb default '[]'::jsonb,
  aa_participant_ids uuid[] default '{}'::uuid[],
  occurred_at timestamptz default pg_catalog.now(),
  note text default null,
  original_expense_id uuid default null
)
returns table(updated_expense_id uuid, base_amount numeric(20,1), version bigint)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select updated.updated_expense_id, updated.base_amount, updated.version
  from private.update_expense_impl(
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
  ) as updated;
$function$;

create or replace function public.delete_expense(expense_id uuid)
returns table(deleted_expense_id uuid, deleted boolean, version bigint)
language sql
volatile
security invoker
set search_path = ''
as $function$
  select deleted.deleted_expense_id, deleted.deleted, deleted.version
  from private.delete_expense_impl($1) as deleted;
$function$;

revoke all on schema private from public, anon;
grant usage on schema private to authenticated;

revoke all on function private.can_read_expense(uuid) from public, anon, authenticated;
revoke all on function private.replace_expense_children(
  uuid, uuid, numeric(20,4), public.expense_split_method, jsonb, jsonb, uuid[]
) from public, anon, authenticated;
revoke all on function private.create_expense_impl(
  uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) from public, anon, authenticated;
revoke all on function private.update_expense_impl(
  uuid, uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) from public, anon, authenticated;
revoke all on function private.delete_expense_impl(uuid) from public, anon, authenticated;
grant execute on function private.can_read_expense(uuid) to authenticated;
grant execute on function private.create_expense_impl(
  uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) to authenticated;
grant execute on function private.update_expense_impl(
  uuid, uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) to authenticated;
grant execute on function private.delete_expense_impl(uuid) to authenticated;

revoke all on function public.create_expense(
  uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) from public, anon, authenticated;
revoke all on function public.update_expense(
  uuid, uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) from public, anon, authenticated;
revoke all on function public.delete_expense(uuid) from public, anon, authenticated;
grant execute on function public.create_expense(
  uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) to authenticated;
grant execute on function public.update_expense(
  uuid, uuid, text, numeric(20,4), character(3), numeric(20,10), public.expense_split_method,
  jsonb, jsonb, uuid[], timestamptz, text, uuid
) to authenticated;
grant execute on function public.delete_expense(uuid) to authenticated;
