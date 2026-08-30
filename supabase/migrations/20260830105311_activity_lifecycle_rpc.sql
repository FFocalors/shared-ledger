-- Phase 2A: keep activity lifecycle writes behind authenticated RPCs.
-- Public functions are SECURITY INVOKER entry points.  They delegate the
-- multi-table work to audited helpers in the non-exposed private schema.

create or replace function private.create_activity_impl(
  p_name text,
  p_type public.activity_type,
  p_base_currency character(3),
  p_multi_currency_enabled boolean
)
returns table (
  activity_id uuid,
  created_join_code text,
  activity_name text,
  activity_type public.activity_type,
  activity_base_currency character(3),
  activity_multi_currency_enabled boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_user_id uuid;
  v_activity_id uuid;
  v_join_code text;
  v_random_bytes bytea;
  v_activity_name text;
  v_attempts integer := 0;
begin
  v_user_id := (select auth.uid());
  if v_user_id is null then
    raise exception 'authenticated user is required'
      using errcode = '28000';
  end if;

  if p_name is null or pg_catalog.length(pg_catalog.btrim(p_name)) = 0 then
    raise exception 'activity name must not be blank'
      using errcode = '22023';
  end if;

  if p_type is null then
    raise exception 'activity type is required'
      using errcode = '22023';
  end if;

  if p_base_currency is null or p_base_currency !~ '^[A-Z]{3}$' then
    raise exception 'base_currency must be three uppercase letters'
      using errcode = '22023';
  end if;

  if p_multi_currency_enabled is null then
    raise exception 'multi_currency_enabled is required'
      using errcode = '22023';
  end if;

  v_activity_name := pg_catalog.btrim(p_name);

  -- Eight cryptographically random bytes provide the digits; the unique
  -- constraint on activities.join_code arbitrates concurrent creators.
  -- ON CONFLICT retries only a join-code collision.
  loop
    v_attempts := v_attempts + 1;
    if v_attempts > 100 then
      raise exception 'could not allocate a unique join code'
        using errcode = 'P0001';
    end if;

    v_activity_id := extensions.gen_random_uuid();
    v_random_bytes := extensions.gen_random_bytes(8);
    v_join_code := '';
    for v_digit_index in 0..7 loop
      v_join_code := v_join_code || (
        pg_catalog.get_byte(v_random_bytes, v_digit_index) % 10
      )::text;
    end loop;

    insert into public.activities (
      id,
      join_code,
      name,
      type,
      base_currency,
      multi_currency_enabled,
      created_by
    )
    values (
      v_activity_id,
      v_join_code,
      v_activity_name,
      p_type,
      p_base_currency,
      p_multi_currency_enabled,
      v_user_id
    )
    on conflict (join_code) do nothing;

    if found then
      exit;
    end if;
  end loop;

  -- These statements are part of the same function call.  Any exception in
  -- membership or unit creation aborts the statement and rolls back the
  -- activity inserted above as well.
  insert into public.activity_members (activity_id, user_id)
  values (v_activity_id, v_user_id);

  if p_type = 'normal'::public.activity_type then
    insert into public.ledger_units (activity_id, name, type)
    values (v_activity_id, v_activity_name, 'default'::public.ledger_unit_type);
  else
    insert into public.ledger_units (activity_id, name, type)
    values (v_activity_id, v_activity_name, 'root'::public.ledger_unit_type);
  end if;

  return query
  select
    v_activity_id,
    v_join_code,
    a.name,
    a.type,
    a.base_currency,
    a.multi_currency_enabled
  from public.activities as a
  where a.id = v_activity_id;
end;
$function$;

create or replace function private.join_activity_by_code_impl(p_join_code text)
returns table (
  joined_activity_id uuid,
  is_new boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_user_id uuid;
  v_activity_id uuid;
  v_is_new boolean;
begin
  v_user_id := (select auth.uid());
  if v_user_id is null then
    raise exception 'authenticated user is required'
      using errcode = '28000';
  end if;

  if p_join_code is null or p_join_code !~ '^[0-9]{8}$' then
    raise exception 'join_code must be an 8 digit string'
      using errcode = '22023';
  end if;

  -- Lock the activity while checking its lifecycle state so a concurrent
  -- update cannot turn a valid lookup into a join of a deleted activity.
  select a.id
    into v_activity_id
  from public.activities as a
  where a.join_code = p_join_code
    and not a.is_deleted
  for update;

  if not found then
    raise exception 'activity not found'
      using errcode = 'P0002';
  end if;

  insert into public.activity_members (activity_id, user_id)
  values (v_activity_id, v_user_id)
  on conflict (activity_id, user_id) do nothing;

  v_is_new := found;

  return query select v_activity_id, v_is_new;
end;
$function$;

create or replace function private.create_sub_activity_impl(
  p_activity_id uuid,
  p_name text
)
returns table (
  parent_activity_id uuid,
  ledger_unit_id uuid,
  created_name text,
  created_type public.ledger_unit_type
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_user_id uuid;
  v_activity_type public.activity_type;
  v_ledger_unit_id uuid;
  v_name text;
begin
  v_user_id := (select auth.uid());
  if v_user_id is null then
    raise exception 'authenticated user is required'
      using errcode = '28000';
  end if;

  if p_activity_id is null then
    raise exception 'activity_id is required'
      using errcode = '22023';
  end if;

  if p_name is null or pg_catalog.length(pg_catalog.btrim(p_name)) = 0 then
    raise exception 'sub-activity name must not be blank'
      using errcode = '22023';
  end if;

  v_name := pg_catalog.btrim(p_name);

  -- Creator ownership is checked from the immutable activity creator column;
  -- membership alone is intentionally insufficient in Phase 2A.
  select a.type
    into v_activity_type
  from public.activities as a
  where a.id = p_activity_id
    and not a.is_deleted
    and a.created_by = v_user_id
  for update;

  if not found then
    raise exception 'activity not found or caller is not the creator'
      using errcode = '42501';
  end if;

  if v_activity_type <> 'large'::public.activity_type then
    raise exception 'sub-activities require a large activity'
      using errcode = '22023';
  end if;

  -- A large activity created through Phase 2A always has a root.  Requiring
  -- it here prevents a sub-activity from being created under a malformed or
  -- partially migrated activity.
  perform 1
  from public.ledger_units as u
  where u.activity_id = p_activity_id
    and u.type = 'root'::public.ledger_unit_type
    and not u.is_deleted
  for update;

  if not found then
    raise exception 'large activity root ledger unit is missing'
      using errcode = 'P0001';
  end if;

  insert into public.ledger_units (activity_id, name, type)
  values (p_activity_id, v_name, 'sub_activity'::public.ledger_unit_type)
  returning id into v_ledger_unit_id;

  return query
  select
    p_activity_id,
    v_ledger_unit_id,
    v_name,
    'sub_activity'::public.ledger_unit_type;
end;
$function$;

-- Exposed RPCs remain invoker functions so the Data API call itself does not
-- execute with owner privileges.  The private helpers are the only definer
-- boundary and are not in an exposed schema.
create function public.create_activity(
  name text,
  type public.activity_type,
  base_currency character(3) default 'CNY',
  multi_currency_enabled boolean default false
)
returns table (
  activity_id uuid,
  join_code text,
  activity_name text,
  activity_type public.activity_type,
  activity_base_currency character(3),
  activity_multi_currency_enabled boolean
)
language sql
security invoker
set search_path = ''
as $function$
  select *
  from private.create_activity_impl($1, $2, $3, $4);
$function$;

create function public.join_activity_by_code(join_code text)
returns table (
  activity_id uuid,
  is_new boolean
)
language sql
security invoker
set search_path = ''
as $function$
  select *
  from private.join_activity_by_code_impl($1);
$function$;

create function public.create_sub_activity(activity_id uuid, name text)
returns table (
  parent_activity_id uuid,
  ledger_unit_id uuid,
  created_name text,
  created_type public.ledger_unit_type
)
language sql
security invoker
set search_path = ''
as $function$
  select *
  from private.create_sub_activity_impl($1, $2);
$function$;

-- Keep direct lifecycle writes unavailable to API clients.  The definer
-- helpers perform these inserts after their own auth/ownership checks.
revoke insert on table public.activities, public.activity_members from public, anon, authenticated;
revoke insert on table public.ledger_units from public, anon, authenticated;

revoke usage on schema private from public, anon;
grant usage on schema private to authenticated;

revoke execute on function private.create_activity_impl(text, public.activity_type, character(3), boolean) from public, anon, authenticated;
revoke execute on function private.join_activity_by_code_impl(text) from public, anon, authenticated;
revoke execute on function private.create_sub_activity_impl(uuid, text) from public, anon, authenticated;
grant execute on function private.create_activity_impl(text, public.activity_type, character(3), boolean) to authenticated;
grant execute on function private.join_activity_by_code_impl(text) to authenticated;
grant execute on function private.create_sub_activity_impl(uuid, text) to authenticated;

revoke execute on function public.create_activity(text, public.activity_type, character(3), boolean) from public, anon;
revoke execute on function public.join_activity_by_code(text) from public, anon;
revoke execute on function public.create_sub_activity(uuid, text) from public, anon;
grant execute on function public.create_activity(text, public.activity_type, character(3), boolean) to authenticated;
grant execute on function public.join_activity_by_code(text) to authenticated;
grant execute on function public.create_sub_activity(uuid, text) to authenticated;
