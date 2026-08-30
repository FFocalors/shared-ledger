create policy expenses_select_member
on public.expenses
for select
to authenticated
using ((select private.can_read_expense(id)));

create policy payments_select_member
on public.payments
for select
to authenticated
using ((select private.can_read_expense(expense_id)));

create policy splits_select_member
on public.splits
for select
to authenticated
using ((select private.can_read_expense(expense_id)));

revoke all on table public.expenses, public.payments, public.splits
  from public, anon, authenticated;
grant select on table public.expenses, public.payments, public.splits to authenticated;
