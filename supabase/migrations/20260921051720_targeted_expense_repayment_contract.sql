begin;

-- A settlement request carries its user intent independently of the
-- rebuildable transfer_allocations projection.  These columns are also useful
-- to clients which need to display the historical mode after a rebuild.
alter table public.transfers
  add column if not exists settlement_mode text,
  add column if not exists target_expense_ids uuid[];

-- Existing voided transfers are immutable under the previous lifecycle
-- trigger.  Temporarily remove it while adding the historical mode snapshots;
-- the replacement trigger below is recreated before this migration commits.
drop trigger if exists transfers_immutable_lifecycle on public.transfers;

update public.transfers
set settlement_mode = case
  when type = 'final_settlement'::public.transfer_type then 'FINAL_SETTLEMENT'
  else 'FIFO'
end
where settlement_mode is null;

update public.transfers
set target_expense_ids = '{}'::uuid[]
where target_expense_ids is null;

alter table public.transfers
  alter column settlement_mode set default 'FIFO',
  alter column settlement_mode set not null,
  alter column target_expense_ids set default '{}'::uuid[],
  alter column target_expense_ids set not null;

alter table public.transfers
  add constraint transfers_settlement_mode_valid
    check (settlement_mode in ('FIFO', 'TARGETED', 'FINAL_SETTLEMENT')),
  add constraint transfers_settlement_mode_type_consistent
    check (
      (type = 'final_settlement'::public.transfer_type and settlement_mode = 'FINAL_SETTLEMENT')
      or (type <> 'final_settlement'::public.transfer_type and settlement_mode in ('FIFO', 'TARGETED'))
    );

-- Durable per-expense facts.  transfer_allocations remains a projection that
-- can point at a newly rebuilt ExpenseDebt row; this table keeps stable
-- Expense/endpoints/currency snapshots so a rebuild cannot move a targeted
-- payment to another bill.  A final-settlement path is identified by its
-- immutable path id; source_expense_debt_id is only a historical snapshot.
create table if not exists public.transfer_expense_allocations (
  id uuid primary key default extensions.gen_random_uuid(),
  activity_id uuid not null references public.activities(id) on delete restrict,
  transfer_id uuid not null,
  settlement_component_id uuid,
  expense_id uuid not null references public.expenses(id) on delete restrict,
  ledger_unit_id uuid not null references public.ledger_units(id) on delete restrict,
  debtor_participant_id uuid not null,
  creditor_participant_id uuid not null,
  allocation_mode text not null,
  payment_currency character(3) not null,
  payment_amount numeric(20,4) not null check (payment_amount > 0),
  original_currency character(3) not null,
  original_amount numeric(20,4) not null check (original_amount > 0),
  base_amount numeric(20,1) not null check (base_amount >= 0),
  fx_rate numeric(20,10) not null check (fx_rate > 0),
  source_expense_debt_id uuid,
  source_path_id uuid,
  created_at timestamptz not null default pg_catalog.now(),
  constraint transfer_expense_allocations_transfer_fk
    foreign key (transfer_id, activity_id)
    references public.transfers(id, activity_id) on delete restrict,
  constraint transfer_expense_allocations_component_fk
    foreign key (settlement_component_id, activity_id, transfer_id)
    references public.transfer_components(id, activity_id, transfer_id) on delete restrict,
  constraint transfer_expense_allocations_expense_unit_fk
    foreign key (expense_id, ledger_unit_id)
    references public.expenses(id, ledger_unit_id) on delete restrict,
  constraint transfer_expense_allocations_debtor_fk
    foreign key (activity_id, debtor_participant_id)
    references public.participants(activity_id, id) on delete restrict,
  constraint transfer_expense_allocations_creditor_fk
    foreign key (activity_id, creditor_participant_id)
    references public.participants(activity_id, id) on delete restrict,
  constraint transfer_expense_allocations_distinct_parties
    check (debtor_participant_id <> creditor_participant_id),
  constraint transfer_expense_allocations_mode_valid
    check (allocation_mode in ('FIFO', 'TARGETED', 'FINAL_SETTLEMENT')),
  constraint transfer_expense_allocations_payment_currency_valid
    check (payment_currency ~ '^[A-Z]{3}$'),
  constraint transfer_expense_allocations_original_currency_valid
    check (original_currency ~ '^[A-Z]{3}$'),
  constraint transfer_expense_allocations_final_path_identity
    check (allocation_mode <> 'FINAL_SETTLEMENT' or source_path_id is not null),
  constraint transfer_expense_allocations_ordinary_path_identity
    check (allocation_mode = 'FINAL_SETTLEMENT' or source_path_id is null)
);

create index if not exists transfer_expense_allocations_activity_expense_idx
  on public.transfer_expense_allocations(activity_id, expense_id);
create index if not exists transfer_expense_allocations_transfer_idx
  on public.transfer_expense_allocations(activity_id, transfer_id);
create index if not exists transfer_expense_allocations_debt_endpoint_idx
  on public.transfer_expense_allocations(activity_id, debtor_participant_id, creditor_participant_id);
create index if not exists transfer_expense_allocations_transfer_fk_idx
  on public.transfer_expense_allocations(transfer_id, activity_id);
create index if not exists transfer_expense_allocations_component_fk_idx
  on public.transfer_expense_allocations(settlement_component_id, activity_id, transfer_id);
create index if not exists transfer_expense_allocations_expense_unit_fk_idx
  on public.transfer_expense_allocations(expense_id, ledger_unit_id);
create index if not exists transfer_expense_allocations_ledger_unit_fk_idx
  on public.transfer_expense_allocations(ledger_unit_id);
create index if not exists transfer_expense_allocations_debtor_fk_idx
  on public.transfer_expense_allocations(activity_id, debtor_participant_id);
create index if not exists transfer_expense_allocations_creditor_fk_idx
  on public.transfer_expense_allocations(activity_id, creditor_participant_id);
create unique index if not exists transfer_expense_allocations_ordinary_identity_idx
  on public.transfer_expense_allocations(transfer_id, expense_id, debtor_participant_id, creditor_participant_id, allocation_mode)
  where allocation_mode <> 'FINAL_SETTLEMENT';
create unique index if not exists transfer_expense_allocations_final_path_identity_idx
  on public.transfer_expense_allocations(source_path_id)
  where allocation_mode = 'FINAL_SETTLEMENT' and source_path_id is not null;

alter table public.transfer_expense_allocations enable row level security;
drop policy if exists transfer_expense_allocations_select_member
  on public.transfer_expense_allocations;
create policy transfer_expense_allocations_select_member
on public.transfer_expense_allocations
for select to authenticated
using ((select private.is_activity_member(activity_id)));
revoke all on table public.transfer_expense_allocations from public, anon, authenticated;
grant select on table public.transfer_expense_allocations to authenticated;
grant all on table public.transfer_expense_allocations to service_role;

-- Existing allocations are the only historical amounts that can be recovered.
-- Void-only or already-rebuilt history is intentionally absent here rather than
-- being reconstructed from an identity-only source marker.
insert into public.transfer_expense_allocations(
  activity_id, transfer_id, settlement_component_id, expense_id, ledger_unit_id,
  debtor_participant_id, creditor_participant_id, allocation_mode,
  payment_currency, payment_amount, original_currency, original_amount,
  base_amount, fx_rate, source_expense_debt_id
)
select ta.activity_id, ta.transfer_id, ta.settlement_component_id,
       ed.expense_id, e.ledger_unit_id, ed.debtor_participant_id,
       ed.creditor_participant_id, 'FIFO', t.currency,
       case when t.currency = a.base_currency
            then coalesce(ta.base_amount, ta.amount)
            else coalesce(ta.original_amount, ta.amount) end,
       coalesce(ed.original_currency, a.base_currency),
       coalesce(ta.original_amount, ta.amount),
       coalesce(ta.base_amount, ta.amount), coalesce(ed.fx_rate, 1), ed.id
from public.transfer_allocations ta
join public.transfers t on t.id = ta.transfer_id and t.activity_id = ta.activity_id
join public.activities a on a.id = ta.activity_id
join public.expense_debts ed on ed.activity_id = ta.activity_id and ed.id = ta.expense_debt_id
join public.expenses e on e.id = ed.expense_id
where t.type <> 'final_settlement'::public.transfer_type
  and not exists (
    select 1 from public.transfer_expense_allocations x
    where x.transfer_id = ta.transfer_id and x.expense_id = ed.expense_id
      and x.debtor_participant_id = ed.debtor_participant_id
      and x.creditor_participant_id = ed.creditor_participant_id
      and x.allocation_mode = 'FIFO'
  );

-- Final path rows are already immutable source facts.  One durable row exists
-- per path row, so a multi-hop route cannot make the same path row count twice.
insert into public.transfer_expense_allocations(
  activity_id, transfer_id, settlement_component_id, expense_id, ledger_unit_id,
  debtor_participant_id, creditor_participant_id, allocation_mode,
  payment_currency, payment_amount, original_currency, original_amount,
  base_amount, fx_rate, source_expense_debt_id, source_path_id
)
select f.activity_id, f.transfer_id, tc.id, f.source_expense_id, e.ledger_unit_id,
       coalesce(ed.debtor_participant_id, f.from_participant_id),
       coalesce(ed.creditor_participant_id, f.to_participant_id),
       'FINAL_SETTLEMENT', coalesce(f.path_currency, t.currency),
       case when coalesce(f.path_currency, t.currency) = a.base_currency
            then coalesce(f.base_amount, f.amount)
            else coalesce(f.original_amount, f.amount) end,
       coalesce(ed.original_currency, e.original_currency, a.base_currency),
       coalesce(f.original_amount, f.amount), coalesce(f.base_amount, f.amount),
       coalesce(ed.fx_rate, f.fx_rate, e.fx_rate, 1),
       f.source_expense_debt_id, f.id
from public.final_settlement_paths f
join public.transfers t on t.id = f.transfer_id and t.activity_id = f.activity_id
join public.activities a on a.id = f.activity_id
join public.expenses e on e.id = f.source_expense_id
left join public.expense_debts ed on ed.id = f.source_expense_debt_id
left join public.transfer_components tc
  on tc.activity_id = f.activity_id and tc.transfer_id = f.transfer_id
 and tc.component_type = 'settlement'
where f.component_type = 'settlement'
  and f.source_expense_id is not null
on conflict do nothing;

create or replace function private.reject_transfer_expense_allocation_mutation()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  raise exception using errcode = '55000',
    message = 'transfer expense allocations are immutable facts';
end;
$function$;

-- A financial rebuild may refresh projections, but it must leave an expense's
-- historical debt rows attached once a real transfer has touched it.  This
-- also makes the stable durable allocation facts resolvable after a rebuild.
create or replace function private.rebuild_activity_debt_projection(p_activity_id uuid)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_expense_id uuid;
begin
  if not exists(select 1 from public.activities a where a.id=p_activity_id) then
    raise exception using errcode='P0002',message='activity was not found for debt rebuild';
  end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  delete from public.prepayment_usages where activity_id=p_activity_id;
  delete from public.prepayment_accounts where activity_id=p_activity_id;
  delete from public.transfer_allocations where activity_id=p_activity_id;
  delete from public.expense_debts ed
  where ed.activity_id=p_activity_id
    and not exists (
      select 1 from public.expenses e
      where e.id=ed.expense_id and e.financial_locked
    );
  for v_expense_id in
    select e.id from public.expenses e
    join public.ledger_units lu on lu.id=e.ledger_unit_id
    join public.activities a on a.id=lu.activity_id
    where lu.activity_id=p_activity_id and not e.is_deleted
      and not lu.is_deleted and not a.is_deleted and not e.financial_locked
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

drop trigger if exists transfer_expense_allocations_immutable
  on public.transfer_expense_allocations;
create trigger transfer_expense_allocations_immutable
before update or delete on public.transfer_expense_allocations
for each row execute function private.reject_transfer_expense_allocation_mutation();
revoke all on function private.reject_transfer_expense_allocation_mutation()
  from public, anon, authenticated;

create or replace function private.assert_transfer_immutable_lifecycle()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if tg_op = 'DELETE' then
    raise exception using errcode = '55000', message = 'transfers are immutable facts';
  end if;
  if old.is_voided then
    if new is distinct from old then
      raise exception using errcode = '55000', message = 'voided transfer is immutable';
    end if;
    return new;
  end if;
  if new.activity_id is distinct from old.activity_id
     or new.from_participant_id is distinct from old.from_participant_id
     or new.to_participant_id is distinct from old.to_participant_id
     or new.type is distinct from old.type
     or new.amount is distinct from old.amount
     or new.currency is distinct from old.currency
     or new.occurred_at is distinct from old.occurred_at
     or new.recorded_by is distinct from old.recorded_by
     or new.on_behalf_of_participant_id is distinct from old.on_behalf_of_participant_id
     or new.created_at is distinct from old.created_at
     or new.request_id is distinct from old.request_id
     or new.settlement_mode is distinct from old.settlement_mode
     or new.target_expense_ids is distinct from old.target_expense_ids
     or new.request_payload is distinct from old.request_payload then
    raise exception using errcode = '55000', message = 'transfer financial fields are immutable';
  end if;
  if not new.is_voided and (
       new.voided_at is distinct from old.voided_at
    or new.voided_by is distinct from old.voided_by
    or new.void_reason is distinct from old.void_reason
  ) then
    raise exception using errcode = '55000', message = 'void metadata requires void transition';
  end if;
  if new.is_voided is distinct from old.is_voided and not new.is_voided then
    raise exception using errcode = '55000', message = 'voided transfer cannot be restored';
  end if;
  return new;
end;
$function$;

drop trigger if exists transfers_immutable_lifecycle on public.transfers;
create trigger transfers_immutable_lifecycle
before update or delete on public.transfers
for each row execute function private.assert_transfer_immutable_lifecycle();
revoke all on function private.assert_transfer_immutable_lifecycle()
  from public, anon, authenticated;

-- Stable candidate projection shared by the list, preview, and commit RPCs.
-- The residual subtracts reverse debt, effective ordinary/final settlements,
-- and existing prepayment usage in that order.  It never reclaims prepayment
-- in order to make a targeted bill appear payable.
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
language plpgsql
stable
security definer
set search_path = ''
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
    select ed.id as debt_id, ed.expense_id, ed.ledger_unit_id,
      ed.debtor_participant_id, ed.creditor_participant_id,
      coalesce(ed.original_currency,v_base_currency)::character(3) as debt_currency,
      coalesce(ed.original_amount,ed.amount)::numeric(20,4) as debt_original_amount,
      ed.amount::numeric(20,1) as debt_base_amount,
      coalesce(ed.fx_rate,1)::numeric(20,10) as debt_fx,
      e.title, e.occurred_at, e.created_at, lu.name as ledger_unit_name,
      coalesce(sum(coalesce(ed.original_amount,ed.amount)) over (
        partition by ed.debtor_participant_id,ed.creditor_participant_id,
          coalesce(ed.original_currency,v_base_currency)
        order by e.occurred_at,e.created_at,e.id,ed.id
        rows between unbounded preceding and 1 preceding),0)::numeric(20,4) as prior_original,
      coalesce((select sum(coalesce(x.original_amount,x.amount))
        from public.expense_debts x
        where x.activity_id=p_activity_id
          and x.debtor_participant_id=p_to_participant_id
          and x.creditor_participant_id=p_from_participant_id
          and coalesce(x.original_currency,v_base_currency)=coalesce(ed.original_currency,v_base_currency)),0)::numeric(20,4) as reverse_original,
      coalesce((select sum(coalesce(ta.original_amount,ta.amount))
        from public.transfer_allocations ta
        join public.transfers tx on tx.id=ta.transfer_id and tx.activity_id=ta.activity_id
        where ta.activity_id=p_activity_id and ta.expense_debt_id=ed.id and not tx.is_voided),0)::numeric(20,4) as ordinary_settled_original,
      coalesce((select sum(coalesce(ta.base_amount,ta.amount))
        from public.transfer_allocations ta
        join public.transfers tx on tx.id=ta.transfer_id and tx.activity_id=ta.activity_id
        where ta.activity_id=p_activity_id and ta.expense_debt_id=ed.id and not tx.is_voided),0)::numeric(20,1) as ordinary_settled_base,
      coalesce((select sum(x.original_amount)
        from public.transfer_expense_allocations x
        join public.transfers tx on tx.id=x.transfer_id and tx.activity_id=x.activity_id
        where x.activity_id=p_activity_id and x.expense_id=ed.expense_id
          and x.debtor_participant_id=ed.debtor_participant_id
          and x.creditor_participant_id=ed.creditor_participant_id
          and x.allocation_mode='FINAL_SETTLEMENT' and not tx.is_voided),0)::numeric(20,4) as final_settled_original,
      coalesce((select sum(x.base_amount)
        from public.transfer_expense_allocations x
        join public.transfers tx on tx.id=x.transfer_id and tx.activity_id=x.activity_id
        where x.activity_id=p_activity_id and x.expense_id=ed.expense_id
          and x.debtor_participant_id=ed.debtor_participant_id
          and x.creditor_participant_id=ed.creditor_participant_id
          and x.allocation_mode='FINAL_SETTLEMENT' and not tx.is_voided),0)::numeric(20,1) as final_settled_base,
      coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu
        where pu.activity_id=p_activity_id and pu.expense_debt_id=ed.id),0)::numeric(20,4) as prepayment_original,
      coalesce((select sum(pu.base_amount) from public.prepayment_usages pu
        where pu.activity_id=p_activity_id and pu.expense_debt_id=ed.id),0)::numeric(20,1) as prepayment_base,
      a.financial_version
    from public.expense_debts ed
    join public.expenses e on e.id=ed.expense_id
    join public.ledger_units lu on lu.id=e.ledger_unit_id
    join public.activities a on a.id=ed.activity_id
    where ed.activity_id=p_activity_id
      and ed.debtor_participant_id=p_from_participant_id
      and ed.creditor_participant_id=p_to_participant_id
      and not e.is_deleted and not lu.is_deleted and not a.is_deleted
  ), residual as (
    select r.*,
      least(r.debt_original_amount,
        greatest(r.reverse_original-r.prior_original,0))::numeric(20,4) as offset_candidate_original
    from raw r
  ), final as (
    select r.*,
      (r.ordinary_settled_original+r.final_settled_original)::numeric(20,4) as settled_original_amount,
      (r.ordinary_settled_base+r.final_settled_base)::numeric(20,1) as settled_base_amount,
      least(greatest(r.debt_original_amount-r.ordinary_settled_original
        -r.final_settled_original-r.prepayment_original,0),
        r.offset_candidate_original)::numeric(20,4) as offset_original_amount
    from residual r
  ), totals as (
    select f.*,pg_catalog.round(f.offset_original_amount*f.debt_fx,1)::numeric(20,1) as offset_base_amount
    from final f
  )
  select f.expense_id,f.ledger_unit_id,f.ledger_unit_name,f.title,f.occurred_at,
    f.debt_id,f.debtor_participant_id,f.creditor_participant_id,f.debt_currency,
    f.debt_original_amount,f.debt_base_amount,f.offset_original_amount,f.offset_base_amount,
    f.settled_original_amount,f.settled_base_amount,f.prepayment_original,f.prepayment_base,
    greatest(f.debt_original_amount-f.offset_original_amount-f.settled_original_amount-f.prepayment_original,0)::numeric(20,4),
    greatest(f.debt_base_amount-f.offset_base_amount-f.settled_base_amount-f.prepayment_base,0)::numeric(20,1),
    case when v_currency=v_base_currency
      then greatest(f.debt_base_amount-f.offset_base_amount-f.settled_base_amount-f.prepayment_base,0)::numeric(20,4)
      else greatest(f.debt_original_amount-f.offset_original_amount-f.settled_original_amount-f.prepayment_original,0)::numeric(20,4)
    end,
    f.debt_fx,
    f.financial_version
  from totals f
  where (v_currency=v_base_currency or f.debt_currency=v_currency)
    and greatest(f.debt_original_amount-f.offset_original_amount-f.settled_original_amount-f.prepayment_original,0)>0
  order by f.occurred_at,f.created_at,f.expense_id,f.debt_id;
end;
$function$;

revoke all on function private.list_repayment_candidates(uuid,uuid,uuid,character)
  from public, anon, authenticated;
grant execute on function private.list_repayment_candidates(uuid,uuid,uuid,character)
  to authenticated;

create or replace function public.list_transfer_expense_candidates(
  activity_id uuid,
  from_participant_id uuid,
  to_participant_id uuid,
  currency character(3)
)
returns table(
  expense_id uuid, ledger_unit_id uuid, ledger_unit_name text, title text,
  occurred_at timestamptz, debtor_participant_id uuid, creditor_participant_id uuid,
  debt_currency character(3), debt_original_amount numeric(20,4), debt_base_amount numeric(20,1),
  offset_original_amount numeric(20,4), settled_original_amount numeric(20,4),
  prepayment_original_amount numeric(20,4), remaining_original_amount numeric(20,4),
  remaining_base_amount numeric(20,1), payment_currency_amount numeric(20,4),
  financial_version bigint
)
language sql stable security invoker set search_path = ''
as $function$
select c.expense_id,c.ledger_unit_id,c.ledger_unit_name,c.title,c.occurred_at,
  c.debtor_participant_id,c.creditor_participant_id,c.debt_currency,
  c.debt_original_amount,c.debt_base_amount,c.offset_original_amount,
  c.settled_original_amount,c.prepayment_original_amount,c.remaining_original_amount,
  c.remaining_base_amount,c.payment_currency_amount,c.financial_version
from private.list_repayment_candidates($1,$2,$3,$4) c;
$function$;

revoke all on function public.list_transfer_expense_candidates(uuid,uuid,uuid,character)
  from public, anon, authenticated;
grant execute on function public.list_transfer_expense_candidates(uuid,uuid,uuid,character)
  to authenticated;

create or replace function private.build_expense_repayment_preview(
  p_activity_id uuid,
  p_from_participant_id uuid,
  p_to_participant_id uuid,
  p_amount numeric(20,4),
  p_currency character(3),
  p_mode text,
  p_target_expense_ids uuid[],
  p_expected_version bigint
)
returns table(
  expense_id uuid,
  ledger_unit_id uuid,
  allocation_mode text,
  payment_currency character(3),
  payment_amount numeric(20,4),
  original_currency character(3),
  original_amount numeric(20,4),
  base_amount numeric(20,1),
  fx_rate numeric(20,10),
  remaining_original_amount numeric(20,4),
  remaining_base_amount numeric(20,1),
  source_financial_version bigint
)
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_mode text := pg_catalog.upper(pg_catalog.btrim(coalesce(p_mode,'FIFO')));
  v_currency character(3) := pg_catalog.upper(pg_catalog.btrim(p_currency));
  v_base_currency character(3);
  v_version bigint;
  v_cap numeric(20,4);
  v_selected_cap numeric(20,4);
  v_left numeric(20,4);
  v_take_payment numeric(20,4);
  v_take_original numeric(20,4);
  v_take_base numeric(20,1);
  v_candidate record;
  v_target_count integer;
begin
  if v_mode not in ('FIFO','TARGETED') then
    raise exception using errcode='22023',message='repayment mode must be FIFO or TARGETED';
  end if;
  if p_amount is null or p_amount<=0 or p_from_participant_id is null
     or p_to_participant_id is null or p_from_participant_id=p_to_participant_id then
    raise exception using errcode='22023',message='invalid repayment';
  end if;
  if p_expected_version is null then
    raise exception using errcode='22023',message='expected_financial_version is required';
  end if;
  select a.base_currency,a.financial_version into v_base_currency,v_version
  from public.activities a where a.id=p_activity_id and not a.is_deleted;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  perform private.assert_financial_version(p_activity_id,p_expected_version);
  if v_currency is null or v_currency !~ '^[A-Z]{3}$' then
    raise exception using errcode='22023',message='invalid settlement currency';
  end if;
  if v_currency=v_base_currency and p_amount<>pg_catalog.round(p_amount,1) then
    raise exception using errcode='22023',message='base-currency amount must have one decimal place';
  end if;
  if v_mode='TARGETED' and coalesce(array_length(p_target_expense_ids,1),0)=0 then
    raise exception using errcode='22023',message='targeted repayment requires expense ids';
  end if;
  if v_mode='FIFO' and coalesce(array_length(p_target_expense_ids,1),0)>0 then
    null;
  end if;

  select coalesce(sum(case when v_currency=v_base_currency
    then coalesce(b.base_amount,b.amount)
    else coalesce(b.original_amount,b.amount) end),0)::numeric(20,4)
    into v_cap
  from public.bilateral_debts b
  where b.activity_id=p_activity_id
    and b.debtor_participant_id=p_from_participant_id
    and b.creditor_participant_id=p_to_participant_id
    and (v_currency=v_base_currency or b.currency=v_currency);

  select coalesce(sum(c.payment_currency_amount),0)::numeric(20,4)
    into v_selected_cap
  from private.list_repayment_candidates(
    p_activity_id,p_from_participant_id,p_to_participant_id,v_currency
  ) c
  where v_mode='FIFO' or c.expense_id=any(p_target_expense_ids);

  if v_mode='TARGETED' then
    select count(*) into v_target_count
    from (
      select distinct x from unnest(p_target_expense_ids) as u(x)
    ) ids
    where exists (
      select 1 from private.list_repayment_candidates(
        p_activity_id,p_from_participant_id,p_to_participant_id,v_currency
      ) c where c.expense_id=ids.x
    );
    if v_target_count <> (select count(distinct x) from unnest(p_target_expense_ids) as u(x)) then
      raise exception using errcode='23514',message='target expense is not an eligible debt';
    end if;
  end if;
  if p_amount>v_cap or p_amount>v_selected_cap then
    raise exception using errcode='23514',message='repayment exceeds selected residual or bilateral debt';
  end if;

  v_left:=p_amount;
  for v_candidate in
    select * from private.list_repayment_candidates(
      p_activity_id,p_from_participant_id,p_to_participant_id,v_currency
    ) c
    where v_mode='FIFO' or c.expense_id=any(p_target_expense_ids)
    order by c.occurred_at,c.expense_id,c.debt_id
  loop
    exit when v_left<=0;
    v_take_payment:=least(v_left,v_candidate.payment_currency_amount)::numeric(20,4);
    if v_currency=v_base_currency then
      v_take_base:=v_take_payment::numeric(20,1);
      if v_take_payment>=v_candidate.payment_currency_amount then
        v_take_original:=v_candidate.remaining_original_amount;
      else
        v_take_original:=least(v_candidate.remaining_original_amount,
          pg_catalog.round(v_take_payment/nullif(v_candidate.debt_fx,0),4))::numeric(20,4);
      end if;
    else
      v_take_original:=v_take_payment;
      v_take_base:=pg_catalog.round(v_take_original*v_candidate.debt_fx,1)::numeric(20,1);
    end if;
    if v_take_original<=0 or v_take_base<0 then continue; end if;
    return query select
      v_candidate.expense_id,v_candidate.ledger_unit_id,v_mode,v_currency,
      case when v_currency=v_base_currency then v_take_base else v_take_original end,
      v_candidate.debt_currency,v_take_original,v_take_base,v_candidate.debt_fx,
      greatest(v_candidate.remaining_original_amount-v_take_original,0)::numeric(20,4),
      greatest(v_candidate.remaining_base_amount-v_take_base,0)::numeric(20,1),v_version;
    v_left:=v_left-case when v_currency=v_base_currency then v_take_base else v_take_original end;
  end loop;
  if v_left>0.00005 then
    raise exception using errcode='23514',message='repayment preview could not allocate full amount';
  end if;
end;
$function$;

revoke all on function private.build_expense_repayment_preview(uuid,uuid,uuid,numeric,character,text,uuid[],bigint)
  from public, anon, authenticated;
grant execute on function private.build_expense_repayment_preview(uuid,uuid,uuid,numeric,character,text,uuid[],bigint)
  to authenticated;

create or replace function public.preview_expense_repayment(
  activity_id uuid,
  from_participant_id uuid,
  to_participant_id uuid,
  amount numeric(20,4),
  currency character(3),
  mode text,
  target_expense_ids uuid[],
  expected_financial_version bigint
)
returns table(
  expense_id uuid, ledger_unit_id uuid, allocation_mode text,
  payment_currency character(3), payment_amount numeric(20,4),
  original_currency character(3), original_amount numeric(20,4),
  base_amount numeric(20,1), fx_rate numeric(20,10),
  remaining_original_amount numeric(20,4), remaining_base_amount numeric(20,1),
  source_financial_version bigint
)
language sql stable security invoker set search_path = ''
as $function$
select * from private.build_expense_repayment_preview(
  $1,$2,$3,$4,$5,$6,$7,$8
);
$function$;

revoke all on function public.preview_expense_repayment(uuid,uuid,uuid,numeric,character,text,uuid[],bigint)
  from public, anon, authenticated;
grant execute on function public.preview_expense_repayment(uuid,uuid,uuid,numeric,character,text,uuid[],bigint)
  to authenticated;

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
  select a.base_currency,a.archived_at,a.financial_version
    into v_base_currency,v_archived_at,v_version
  from public.activities a
  where a.id=p_activity_id and not a.is_deleted
  for update;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_archived_at is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if;

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
       or v_existing.type<>'settlement'::public.transfer_type then
      raise exception using errcode='23505',message='repayment request id was already used with a different payload';
    end if;
    v_result:=v_existing.request_result;
    if v_result is null then raise exception using errcode='55000',message='idempotent result is unavailable'; end if;
    return query select (v_result->>'transfer_id')::uuid,(v_result->>'amount')::numeric,
      (v_result->>'currency')::character(3),(v_result->>'mode')::text,
      (v_result->>'financial_version')::bigint;
    return;
  end if;

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

revoke all on function private.create_expense_repayment_v2_impl(uuid,uuid,uuid,numeric,character,text,uuid[],timestamptz,uuid,bigint,uuid)
  from public, anon, authenticated;
grant execute on function private.create_expense_repayment_v2_impl(uuid,uuid,uuid,numeric,character,text,uuid[],timestamptz,uuid,bigint,uuid)
  to authenticated;

create or replace function public.create_expense_repayment_v2(
  activity_id uuid,
  from_participant_id uuid,
  to_participant_id uuid,
  amount numeric(20,4),
  currency character(3),
  mode text default 'FIFO',
  target_expense_ids uuid[] default null,
  occurred_at timestamptz default pg_catalog.now(),
  on_behalf_of_participant_id uuid default null,
  expected_financial_version bigint default null,
  request_id uuid default null
)
returns table(transfer_id uuid, amount numeric(20,4), currency character(3), mode text, financial_version bigint)
language sql volatile security invoker set search_path = ''
as $function$
select * from private.create_expense_repayment_v2_impl(
  $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11
);
$function$;

revoke all on function public.create_expense_repayment_v2(uuid,uuid,uuid,numeric,character,text,uuid[],timestamptz,uuid,bigint,uuid)
  from public, anon, authenticated;
grant execute on function public.create_expense_repayment_v2(uuid,uuid,uuid,numeric,character,text,uuid[],timestamptz,uuid,bigint,uuid)
  to authenticated;

-- Keep final-settlement source allocations durable as paths are written.  The
-- path id is the deduplication key; route hops therefore cannot duplicate a
-- source allocation during later reads or rebuilds.
create or replace function private.capture_final_settlement_allocation_fact()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_transfer_currency character(3);
  v_base_currency character(3);
  v_expense_currency character(3);
  v_fx numeric(20,10);
  v_ledger_unit_id uuid;
  v_debtor uuid;
  v_creditor uuid;
  v_component_id uuid;
begin
  if new.component_type <> 'settlement' or new.source_expense_id is null then return new; end if;
  select t.currency,a.base_currency into v_transfer_currency,v_base_currency
  from public.transfers t join public.activities a on a.id=t.activity_id
  where t.id=new.transfer_id and t.activity_id=new.activity_id;
  select e.ledger_unit_id,e.original_currency,e.fx_rate,
         ed.debtor_participant_id,ed.creditor_participant_id
    into v_ledger_unit_id,v_expense_currency,v_fx,v_debtor,v_creditor
  from public.expenses e
  left join public.expense_debts ed on ed.id=new.source_expense_debt_id
  where e.id=new.source_expense_id;
  v_debtor:=coalesce(v_debtor,new.from_participant_id);
  v_creditor:=coalesce(v_creditor,new.to_participant_id);
  select tc.id into v_component_id
  from public.transfer_components tc
  where tc.activity_id=new.activity_id and tc.transfer_id=new.transfer_id
    and tc.component_type='settlement';
  insert into public.transfer_expense_allocations(
    activity_id,transfer_id,settlement_component_id,expense_id,ledger_unit_id,
    debtor_participant_id,creditor_participant_id,allocation_mode,
    payment_currency,payment_amount,original_currency,original_amount,
    base_amount,fx_rate,source_expense_debt_id,source_path_id
  ) values (
    new.activity_id,new.transfer_id,v_component_id,new.source_expense_id,v_ledger_unit_id,
    v_debtor,v_creditor,'FINAL_SETTLEMENT',coalesce(new.path_currency,v_transfer_currency),
    case when coalesce(new.path_currency,v_transfer_currency)=v_base_currency
      then coalesce(new.base_amount,new.amount) else coalesce(new.original_amount,new.amount) end,
    coalesce(v_expense_currency,new.path_currency,v_transfer_currency),
    coalesce(new.original_amount,new.amount),coalesce(new.base_amount,new.amount),
    coalesce(v_fx,new.fx_rate,1),new.source_expense_debt_id,new.id
  ) on conflict do nothing;
  return new;
end;
$function$;

drop trigger if exists final_settlement_paths_capture_allocation_fact
  on public.final_settlement_paths;
create trigger final_settlement_paths_capture_allocation_fact
after insert on public.final_settlement_paths
for each row execute function private.capture_final_settlement_allocation_fact();
revoke all on function private.capture_final_settlement_allocation_fact()
  from public, anon, authenticated;

create or replace function public.get_expense_repayment_progress(
  p_activity_id uuid,
  p_expense_id uuid
)
returns table(
  expense_id uuid,
  debtor_participant_id uuid,
  creditor_participant_id uuid,
  debt_currency character(3),
  debt_original_amount numeric(20,4),
  debt_base_amount numeric(20,1),
  settled_original_amount numeric(20,4),
  settled_base_amount numeric(20,1),
  prepayment_original_amount numeric(20,4),
  prepayment_base_amount numeric(20,1),
  offset_original_amount numeric(20,4),
  offset_base_amount numeric(20,1),
  remaining_original_amount numeric(20,4),
  remaining_base_amount numeric(20,1),
  financial_version bigint
)
language plpgsql
stable
security invoker
set search_path = ''
as $function$
declare
  v_activity_id uuid := p_activity_id;
  v_expense_id uuid := p_expense_id;
  v_base_currency character(3);
begin
  if not exists (
    select 1 from public.activity_members m
    where m.activity_id=v_activity_id and m.user_id=(select auth.uid())
  ) then
    raise exception using errcode='42501',message='caller is not an activity member';
  end if;
  select a.base_currency into v_base_currency
  from public.activities a where a.id=v_activity_id and not a.is_deleted;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  return query
  with raw as (
    select ed.id debt_id,ed.expense_id,ed.debtor_participant_id,ed.creditor_participant_id,
      coalesce(ed.original_currency,v_base_currency)::character(3) debt_currency,
      coalesce(ed.original_amount,ed.amount)::numeric(20,4) debt_original_amount,
      ed.amount::numeric(20,1) debt_base_amount,coalesce(ed.fx_rate,1)::numeric(20,10) debt_fx,
      coalesce(sum(coalesce(ed.original_amount,ed.amount)) over (
        partition by ed.debtor_participant_id,ed.creditor_participant_id,
          coalesce(ed.original_currency,v_base_currency)
        order by e.occurred_at,e.created_at,e.id,ed.id
        rows between unbounded preceding and 1 preceding),0)::numeric(20,4) prior_original,
      coalesce((select sum(coalesce(x.original_amount,x.amount)) from public.expense_debts x
        where x.activity_id=v_activity_id and x.debtor_participant_id=ed.creditor_participant_id
          and x.creditor_participant_id=ed.debtor_participant_id
          and coalesce(x.original_currency,v_base_currency)=coalesce(ed.original_currency,v_base_currency)),0)::numeric(20,4) reverse_original,
      coalesce((select sum(coalesce(ta.original_amount,ta.amount))
        from public.transfer_allocations ta join public.transfers t
          on t.id=ta.transfer_id and t.activity_id=ta.activity_id
        where ta.activity_id=v_activity_id and ta.expense_debt_id=ed.id and not t.is_voided),0)::numeric(20,4) ordinary_original,
      coalesce((select sum(coalesce(ta.base_amount,ta.amount))
        from public.transfer_allocations ta join public.transfers t
          on t.id=ta.transfer_id and t.activity_id=ta.activity_id
        where ta.activity_id=v_activity_id and ta.expense_debt_id=ed.id and not t.is_voided),0)::numeric(20,1) ordinary_base,
      coalesce((select sum(x.original_amount) from public.transfer_expense_allocations x
        join public.transfers t on t.id=x.transfer_id and t.activity_id=x.activity_id
        where x.activity_id=v_activity_id and x.expense_id=ed.expense_id
          and x.debtor_participant_id=ed.debtor_participant_id
          and x.creditor_participant_id=ed.creditor_participant_id
          and x.allocation_mode='FINAL_SETTLEMENT' and not t.is_voided),0)::numeric(20,4) final_original,
      coalesce((select sum(x.base_amount) from public.transfer_expense_allocations x
        join public.transfers t on t.id=x.transfer_id and t.activity_id=x.activity_id
        where x.activity_id=v_activity_id and x.expense_id=ed.expense_id
          and x.debtor_participant_id=ed.debtor_participant_id
          and x.creditor_participant_id=ed.creditor_participant_id
          and x.allocation_mode='FINAL_SETTLEMENT' and not t.is_voided),0)::numeric(20,1) final_base,
      coalesce((select sum(pu.debt_amount) from public.prepayment_usages pu
        where pu.activity_id=v_activity_id and pu.expense_debt_id=ed.id),0)::numeric(20,4) prepay_original,
      coalesce((select sum(pu.base_amount) from public.prepayment_usages pu
        where pu.activity_id=v_activity_id and pu.expense_debt_id=ed.id),0)::numeric(20,1) prepay_base,
      a.financial_version
    from public.expense_debts ed
    join public.expenses e on e.id=ed.expense_id
    join public.activities a on a.id=ed.activity_id
    where ed.activity_id=v_activity_id and not e.is_deleted
  ), offsets as (
    select r.*,least(r.debt_original_amount,
      greatest(r.reverse_original-r.prior_original,0))::numeric(20,4) offset_candidate_original
    from raw r
  ), totals as (
    select o.*,
      (o.ordinary_original+o.final_original)::numeric(20,4) settled_original,
      (o.ordinary_base+o.final_base)::numeric(20,1) settled_base,
      least(greatest(o.debt_original_amount-o.ordinary_original-o.final_original-o.prepay_original,0),
        o.offset_candidate_original)::numeric(20,4) offset_original
    from offsets o
  ), finalized as (
    select t.*,pg_catalog.round(t.offset_original*t.debt_fx,1)::numeric(20,1) offset_base
    from totals t
    where t.expense_id=v_expense_id
  )
  select t.expense_id,t.debtor_participant_id,t.creditor_participant_id,t.debt_currency,
    t.debt_original_amount,t.debt_base_amount,t.settled_original,t.settled_base,
    t.prepay_original,t.prepay_base,t.offset_original,t.offset_base,
    greatest(t.debt_original_amount-t.settled_original-t.prepay_original-t.offset_original,0)::numeric(20,4),
    greatest(t.debt_base_amount-t.settled_base-t.prepay_base-t.offset_base,0)::numeric(20,1),
    t.financial_version
  from finalized t;
end;
$function$;

revoke all on function public.get_expense_repayment_progress(uuid,uuid)
  from public, anon, authenticated;
grant execute on function public.get_expense_repayment_progress(uuid,uuid)
  to authenticated;

-- Rebuild ordinary allocations from durable facts whenever they exist.  This
-- keeps a targeted transfer attached to its selected bill while preserving
-- FIFO behavior for old transfers which have no recoverable allocation fact.
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
    select t.id, t.from_participant_id, t.to_participant_id, t.currency,
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
                   where x.activity_id=p_activity_id
                     and x.debtor_participant_id=v_transfer.to_participant_id
                     and x.creditor_participant_id=v_transfer.from_participant_id
                     and coalesce(x.original_currency,v_base_currency)=
                         coalesce(ed.original_currency,v_base_currency)),0) reverse_original
          from public.expense_debts ed
          join public.expenses e on e.id=ed.expense_id
          where ed.activity_id=p_activity_id
            and ed.debtor_participant_id=v_transfer.from_participant_id
            and ed.creditor_participant_id=v_transfer.to_participant_id
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
          if v_allocate_base <= 0 then continue; end if;
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

commit;
