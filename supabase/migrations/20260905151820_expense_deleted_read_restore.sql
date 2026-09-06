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
        and not lu.is_deleted
        and not a.is_deleted
        and am.user_id = (select auth.uid())
    );
$function$;
