-- Sub-activity creation is a normal activity-member action.  The activity
-- creator still owns lifecycle and member-management actions, but membership
-- is sufficient to add a ledger unit while the large activity is writable.
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
  v_user_id uuid := (select auth.uid());
  v_activity_type public.activity_type;
  v_ledger_unit_id uuid;
  v_name text;
begin
  if v_user_id is null then
    raise exception 'authenticated user is required' using errcode = '28000';
  end if;
  if p_activity_id is null then
    raise exception 'activity_id is required' using errcode = '22023';
  end if;
  if p_name is null or pg_catalog.length(pg_catalog.btrim(p_name)) = 0 then
    raise exception 'sub-activity name must not be blank' using errcode = '22023';
  end if;

  v_name := pg_catalog.btrim(p_name);
  select a.type
    into v_activity_type
  from public.activities as a
  join public.activity_members as member
    on member.activity_id = a.id
   and member.user_id = v_user_id
  where a.id = p_activity_id
    and not a.is_deleted
    and a.archived_at is null
  for update of a;

  if not found then
    raise exception 'activity not found, archived, or caller is not a member' using errcode = '42501';
  end if;
  if v_activity_type <> 'large'::public.activity_type then
    raise exception 'sub-activities require a large activity' using errcode = '22023';
  end if;

  perform 1
  from public.ledger_units as unit
  where unit.activity_id = p_activity_id
    and unit.type = 'root'::public.ledger_unit_type
    and not unit.is_deleted
  for update;
  if not found then
    raise exception 'large activity root ledger unit is missing' using errcode = 'P0001';
  end if;

  insert into public.ledger_units (activity_id, name, type)
  values (p_activity_id, v_name, 'sub_activity'::public.ledger_unit_type)
  returning id into v_ledger_unit_id;

  return query
  select p_activity_id, v_ledger_unit_id, v_name, 'sub_activity'::public.ledger_unit_type;
end;
$function$;

revoke all on function private.create_sub_activity_impl(uuid, text) from public, anon, authenticated;
grant execute on function private.create_sub_activity_impl(uuid, text) to authenticated;
