begin;

-- Phase 6: final settlement is a temporary activity-wide suggestion.  Only
-- the executed Transfer and its immutable path rows are persisted.
create table public.final_settlement_paths (
  id uuid primary key default extensions.gen_random_uuid(),
  activity_id uuid not null references public.activities(id) on delete restrict,
  transfer_id uuid not null,
  path_order integer not null check (path_order > 0),
  path_no integer not null default 1 check (path_no > 0),
  hop_no integer not null check (hop_no > 0),
  from_participant_id uuid not null,
  to_participant_id uuid not null,
  amount numeric(20,1) not null check (amount > 0),
  component_type text not null check (component_type in ('settlement','prepayment_return')),
  -- Stable source identity is an Expense id, never an ExpenseDebt id: debt
  -- projection rows are rebuilt and receive new UUIDs.
  source_expense_id uuid references public.expenses(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  constraint final_settlement_paths_transfer_fk
    foreign key (transfer_id, activity_id)
    references public.transfers(id, activity_id) on delete cascade,
  constraint final_settlement_paths_from_fk
    foreign key (activity_id, from_participant_id)
    references public.participants(activity_id, id) on delete restrict,
  constraint final_settlement_paths_to_fk
    foreign key (activity_id, to_participant_id)
    references public.participants(activity_id, id) on delete restrict,
  constraint final_settlement_paths_distinct_participants
    check (from_participant_id <> to_participant_id),
  constraint final_settlement_paths_order_unique
    unique (transfer_id, path_order),
  constraint final_settlement_paths_hop_unique
    unique (transfer_id, path_no, hop_no)
);

create index final_settlement_paths_transfer_activity_idx
  on public.final_settlement_paths(transfer_id, activity_id);
create index final_settlement_paths_activity_from_to_idx
  on public.final_settlement_paths(activity_id, from_participant_id, to_participant_id);
create index final_settlement_paths_activity_to_idx
  on public.final_settlement_paths(activity_id, to_participant_id);
create index final_settlement_paths_source_expense_idx
  on public.final_settlement_paths(source_expense_id, activity_id);

alter table public.final_settlement_paths enable row level security;
create policy final_settlement_paths_select_member
on public.final_settlement_paths
for select to authenticated
using ((select private.is_activity_member(activity_id)));
revoke all on table public.final_settlement_paths from public, anon, authenticated;
grant select on table public.final_settlement_paths to authenticated;
grant all on table public.final_settlement_paths to service_role;

-- Final settlement has its own immutable path projection.  It must never be
-- consumed by the ordinary TransferAllocation FIFO, even when an endpoint
-- happens to be a direct ExpenseDebt edge.
create or replace function private.rebuild_transfer_allocations_locked(p_activity_id uuid)
returns void language plpgsql volatile security definer set search_path = ''
as $function$
declare t record; d record; r numeric; x numeric;
begin
  delete from public.transfer_allocations where activity_id = p_activity_id;
  for t in
    select tr.id, tr.from_participant_id, tr.to_participant_id,
           c.id component_id, c.amount
    from public.transfers tr
    join public.transfer_components c
      on c.transfer_id = tr.id and c.activity_id = tr.activity_id
    where tr.activity_id = p_activity_id
      and not tr.is_voided
      and tr.type <> 'final_settlement'::public.transfer_type
      and c.component_type = 'settlement'
    order by tr.occurred_at, tr.created_at, tr.id
  loop
    r := t.amount;
    for d in
      with q as (
        select ed.id, ed.amount, e.occurred_at, e.created_at, e.id eid,
          coalesce(sum(ed.amount) over (
            order by e.occurred_at, e.created_at, e.id
            rows between unbounded preceding and 1 preceding), 0) prior,
          coalesce((select sum(z.amount) from public.expense_debts z
            where z.activity_id = p_activity_id
              and z.debtor_participant_id = t.to_participant_id
              and z.creditor_participant_id = t.from_participant_id), 0) reverse_total
        from public.expense_debts ed
        join public.expenses e on e.id = ed.expense_id
        where ed.activity_id = p_activity_id
          and ed.debtor_participant_id = t.from_participant_id
          and ed.creditor_participant_id = t.to_participant_id
      )
      select id,
        amount - least(amount, greatest(reverse_total - prior, 0))
        - coalesce((select sum(amount) from public.transfer_allocations
          where expense_debt_id = q.id), 0) avail
      from q order by occurred_at, created_at, eid
    loop
      if d.avail > 0 then
        x := least(r, d.avail)::numeric(20,1);
        insert into public.transfer_allocations(
          activity_id, transfer_id, settlement_component_id,
          expense_debt_id, amount
        ) values (p_activity_id, t.id, t.component_id, d.id, x);
        r := r - x;
        exit when r = 0;
      end if;
    end loop;
  end loop;
end;
$function$;

-- Final settlement endpoints are not direct bilateral settlements.  Their
-- ordinary component is represented by final_settlement_paths hops; counting
-- the endpoint here would incorrectly consume prepayment usage a second time.
create or replace function private.rebuild_prepayment_projections_locked(p_activity_id uuid) returns void language plpgsql volatile security definer set search_path='' as $function$
declare a record; d record; u record; aid uuid; left_amt numeric; take numeric; refund_left numeric; settlement_total numeric; reverse_total numeric; begin
 delete from public.prepayment_usages where activity_id=p_activity_id; delete from public.prepayment_accounts where activity_id=p_activity_id;
 if exists (with f as (select t.from_participant_id owner,t.to_participant_id cust,c.amount delta from public.transfers t join public.transfer_components c on c.transfer_id=t.id where t.activity_id=p_activity_id and not t.is_voided and c.component_type='prepayment' union all select t.to_participant_id,t.from_participant_id,-c.amount from public.transfers t join public.transfer_components c on c.transfer_id=t.id where t.activity_id=p_activity_id and not t.is_voided and c.component_type='prepayment_return') select 1 from f group by owner,cust having sum(delta)<0) then raise exception using errcode='23514',message='prepayment returns exceed funding'; end if;
 for a in with f as (select t.from_participant_id owner,t.to_participant_id cust,c.amount delta from public.transfers t join public.transfer_components c on c.transfer_id=t.id where t.activity_id=p_activity_id and not t.is_voided and c.component_type='prepayment' union all select t.to_participant_id,t.from_participant_id,-c.amount from public.transfers t join public.transfer_components c on c.transfer_id=t.id where t.activity_id=p_activity_id and not t.is_voided and c.component_type='prepayment_return') select owner,cust,sum(delta)::numeric(20,1) funded from f group by owner,cust having sum(delta)>0 loop
  left_amt:=a.funded; insert into public.prepayment_accounts(activity_id,owner_participant_id,custodian_participant_id,balance) values(p_activity_id,a.owner,a.cust,left_amt) returning id into aid;
  select coalesce(sum(case when t.from_participant_id=a.owner and t.to_participant_id=a.cust then c.amount when t.from_participant_id=a.cust and t.to_participant_id=a.owner then -c.amount else 0 end),0)
    into settlement_total
   from public.transfers t join public.transfer_components c on c.transfer_id=t.id
   where t.activity_id=p_activity_id and not t.is_voided and t.type <> 'final_settlement'::public.transfer_type and c.component_type='settlement'
     and ((t.from_participant_id=a.owner and t.to_participant_id=a.cust)
       or (t.from_participant_id=a.cust and t.to_participant_id=a.owner));
  select coalesce(sum(x.amount),0) into reverse_total
    from public.expense_debts x join public.expenses rx on rx.id=x.expense_id
   where x.activity_id=p_activity_id and x.debtor_participant_id=a.cust and x.creditor_participant_id=a.owner
     and not (rx.base_amount<0 and rx.original_expense_id is not null and not rx.is_deleted);
  for d in with q as (
    select ed.id,ed.amount,e.occurred_at,e.created_at,e.id eid,
      coalesce(sum(ed.amount) over(order by e.occurred_at,e.created_at,e.id rows between unbounded preceding and 1 preceding),0) prior
    from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
    where ed.activity_id=p_activity_id and ed.debtor_participant_id=a.owner and ed.creditor_participant_id=a.cust
      and not (e.base_amount<0 and e.original_expense_id is not null and not e.is_deleted)
  ) select id,amount-least(amount,greatest((reverse_total+settlement_total)-prior,0)) avail
      from q order by occurred_at,created_at,eid loop
   exit when left_amt=0; if d.avail>0 then take:=least(left_amt,d.avail)::numeric(20,1); insert into public.prepayment_usages(activity_id,account_id,expense_debt_id,gross_amount,amount) values(p_activity_id,aid,d.id,take,take); left_amt:=left_amt-take; end if;
  end loop;
 end loop;
   for u in select rf.id refund_id,rf.original_expense_id,s.participant_id owner,abs(s.base_amount)::numeric(20,1) benefit
     from public.expenses rf
     join public.ledger_units rlu on rlu.id=rf.ledger_unit_id
     join public.activities ra on ra.id=rlu.activity_id
     join public.splits s on s.expense_id=rf.id
    where ra.id=p_activity_id and not ra.is_deleted and not rlu.is_deleted
      and rf.base_amount<0 and rf.original_expense_id is not null and not rf.is_deleted
      and s.base_amount<0
    order by rf.occurred_at,rf.created_at,rf.id,s.participant_id loop
  refund_left:=u.benefit;
   for d in select pu.id,pu.amount from public.prepayment_usages pu join public.expense_debts od on od.id=pu.expense_debt_id join public.prepayment_accounts pa on pa.id=pu.account_id join public.participants cp on cp.activity_id=pa.activity_id and cp.id=pa.custodian_participant_id join public.expenses oe on oe.id=od.expense_id where pa.activity_id=p_activity_id and pa.owner_participant_id=u.owner and od.expense_id=u.original_expense_id order by cp.participant_order,cp.id,oe.occurred_at,oe.created_at,oe.id,od.id,pu.id loop
   exit when refund_left=0; take:=least(refund_left,d.amount); if take=d.amount then delete from public.prepayment_usages where id=d.id; else update public.prepayment_usages set amount=amount-take where id=d.id; end if; refund_left:=refund_left-take;
  end loop;
 end loop;
 delete from public.prepayment_usages where activity_id=p_activity_id and amount=0;
 update public.prepayment_accounts pa set balance=(select coalesce(sum(c.amount),0) from (select t.from_participant_id owner,t.to_participant_id cust,tc.amount from public.transfers t join public.transfer_components tc on tc.transfer_id=t.id where t.activity_id=p_activity_id and not t.is_voided and tc.component_type='prepayment' union all select t.to_participant_id,t.from_participant_id,-tc.amount from public.transfers t join public.transfer_components tc on tc.transfer_id=t.id where t.activity_id=p_activity_id and not t.is_voided and tc.component_type='prepayment_return') c where c.owner=pa.owner_participant_id and c.cust=pa.custodian_participant_id)-coalesce((select sum(pu.amount) from public.prepayment_usages pu where pu.account_id=pa.id),0),updated_at=pg_catalog.now() where pa.activity_id=p_activity_id;
end;$function$;

-- Final path settlement consumes each underlying directed edge.  This keeps
-- the original ExpenseDebt rows immutable while making a recorded A -> C
-- payment settle an A -> B -> C path.  Prepayment-return paths deliberately
-- do not enter this projection: their balance effect is represented by the
-- prepayment account projection.
create or replace function private.rebuild_bilateral_debts_locked(p_activity_id uuid)
returns void language plpgsql volatile security definer set search_path = ''
as $function$
begin
  delete from public.bilateral_debts where activity_id = p_activity_id;
  insert into public.bilateral_debts(
    activity_id, debtor_participant_id, creditor_participant_id, amount
  )
  with facts as (
    select ed.activity_id,
           least(ed.debtor_participant_id, ed.creditor_participant_id) as lo,
           greatest(ed.debtor_participant_id, ed.creditor_participant_id) as hi,
           case when ed.debtor_participant_id < ed.creditor_participant_id
             then ed.amount else -ed.amount end as signed_amount
    from public.expense_debts ed
    where ed.activity_id = p_activity_id
    union all
    select t.activity_id,
           least(t.from_participant_id, t.to_participant_id),
           greatest(t.from_participant_id, t.to_participant_id),
           case when t.from_participant_id < t.to_participant_id
             then -tc.amount else tc.amount end
    from public.transfers t
    join public.transfer_components tc on tc.transfer_id = t.id
      and tc.activity_id = t.activity_id
    where t.activity_id = p_activity_id and not t.is_voided
      and tc.component_type = 'settlement'
      and t.type <> 'final_settlement'::public.transfer_type
    union all
    select p.activity_id,
           least(p.owner_participant_id, p.custodian_participant_id),
           greatest(p.owner_participant_id, p.custodian_participant_id),
           case when p.owner_participant_id < p.custodian_participant_id
             then -u.amount else u.amount end
    from public.prepayment_usages u
    join public.prepayment_accounts p on p.id = u.account_id
    where p.activity_id = p_activity_id
    union all
    select f.activity_id,
           least(f.from_participant_id, f.to_participant_id),
           greatest(f.from_participant_id, f.to_participant_id),
           case when f.from_participant_id < f.to_participant_id
             then -f.amount else f.amount end
    from public.final_settlement_paths f
    join public.transfers t on t.id = f.transfer_id
      and t.activity_id = f.activity_id
    where f.activity_id = p_activity_id and not t.is_voided
      and f.component_type = 'settlement'
  ), netted as (
    select activity_id, lo, hi, sum(signed_amount) as signed_amount
    from facts group by activity_id, lo, hi
  )
  select activity_id,
         case when signed_amount > 0 then lo else hi end,
         case when signed_amount > 0 then hi else lo end,
         abs(signed_amount)::numeric(20,1)
  from netted where signed_amount <> 0;
end;
$function$;

-- Keep the existing expense RPCs atomic when an Activity is archived.  The
-- fact implementation may have staged rows, but this check runs in the same
-- transaction and therefore rolls them back before commit.
create or replace function private.rebuild_expense_and_bilateral_debts(
  p_expense_id uuid, p_activity_id uuid
) returns void language plpgsql volatile security definer set search_path = ''
as $function$
declare v_archived_at timestamptz; v_deleted boolean;
begin
  perform private.lock_debt_projection_activity(p_activity_id);
  select archived_at, is_deleted into v_archived_at, v_deleted
  from public.activities where id = p_activity_id for update;
  if not found or v_deleted then
    raise exception using errcode = 'P0002', message = 'activity was not found';
  end if;
  if v_archived_at is not null then
    raise exception using errcode = '55000', message = 'archived activity is read-only';
  end if;
  perform private.rebuild_expense_debts_locked(p_expense_id, p_activity_id);
  perform private.rebuild_transfer_allocations_locked(p_activity_id);
  perform private.rebuild_prepayment_projections_locked(p_activity_id);
  perform private.rebuild_bilateral_debts_locked(p_activity_id);
  update public.activities set financial_version = financial_version + 1
  where id = p_activity_id;
end;
$function$;

-- Decompose ordinary net settlement on directed residual capacity.  Every
-- emitted path is real: BFS only traverses positive bilateral edges, and
-- each hop is reduced by the path bottleneck.  There is intentionally no
-- fabricated direct edge.
create or replace function private.build_final_settlement_flow(p_activity_id uuid)
returns table(path_no integer, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,1), hops jsonb)
language plpgsql stable security definer set search_path = ''
as $function$
declare
  v_edge_from uuid[] := '{}'::uuid[]; v_edge_to uuid[] := '{}'::uuid[];
  v_edge_remaining numeric[] := '{}'::numeric[]; v_edge_count integer := 0;
  v_sources uuid[] := '{}'::uuid[]; v_source_remaining numeric[] := '{}'::numeric[];
  v_creditors uuid[] := '{}'::uuid[]; v_creditor_remaining numeric[] := '{}'::numeric[];
  v_queue_i integer;
  v_source_left numeric; v_match numeric; v_hop_no integer; v_path_no integer := 0;
  v_node uuid; v_target uuid; v_current_path jsonb; v_found_path jsonb; v_hops jsonb;
  v_queue_nodes uuid[]; v_queue_paths jsonb[]; v_visited uuid[];
  v_rec record; v_edge_path_i integer; v_edge_path_text text;
  v_uid uuid := (select auth.uid()); v_activity_type public.activity_type;
begin
  if v_uid is null then raise exception using errcode='28000', message='authentication is required'; end if;
  if not exists (select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=v_uid) then
    raise exception using errcode='42501', message='caller is not an activity member';
  end if;
  select a.type into v_activity_type from public.activities a where a.id=p_activity_id and not a.is_deleted;
  if not found then raise exception using errcode='P0002', message='activity was not found'; end if;
  if v_activity_type <> 'large'::public.activity_type then
    raise exception using errcode='23514', message='final settlement requires a large activity';
  end if;

  for v_rec in
    select b.debtor_participant_id, b.creditor_participant_id, b.amount
    from public.bilateral_debts b
    join public.participants dp on dp.activity_id=b.activity_id and dp.id=b.debtor_participant_id
    join public.participants cp on cp.activity_id=b.activity_id and cp.id=b.creditor_participant_id
    where b.activity_id=p_activity_id and b.amount>0 and not dp.is_deleted and not cp.is_deleted
    order by dp.participant_order, dp.id, cp.participant_order, cp.id
  loop
    v_edge_count := v_edge_count + 1;
    v_edge_from := array_append(v_edge_from,v_rec.debtor_participant_id);
    v_edge_to := array_append(v_edge_to,v_rec.creditor_participant_id);
    v_edge_remaining := array_append(v_edge_remaining,v_rec.amount);
  end loop;

  for v_rec in
    select p.id, sum(case when b.creditor_participant_id=p.id then b.amount else -b.amount end)::numeric(20,1) net_amount
    from public.participants p join public.bilateral_debts b on b.activity_id=p_activity_id
      and (b.debtor_participant_id=p.id or b.creditor_participant_id=p.id)
    where p.activity_id=p_activity_id and not p.is_deleted
    group by p.id,p.participant_order
    having sum(case when b.creditor_participant_id=p.id then b.amount else -b.amount end) < 0
    order by p.participant_order,p.id
  loop
    v_sources := array_append(v_sources,v_rec.id);
    v_source_remaining := array_append(v_source_remaining,abs(v_rec.net_amount));
  end loop;
  for v_rec in
    select p.id, sum(case when b.creditor_participant_id=p.id then b.amount else -b.amount end)::numeric(20,1) net_amount
    from public.participants p join public.bilateral_debts b on b.activity_id=p_activity_id
      and (b.debtor_participant_id=p.id or b.creditor_participant_id=p.id)
    where p.activity_id=p_activity_id and not p.is_deleted
    group by p.id,p.participant_order
    having sum(case when b.creditor_participant_id=p.id then b.amount else -b.amount end) > 0
    order by p.participant_order,p.id
  loop
    v_creditors := array_append(v_creditors,v_rec.id);
    v_creditor_remaining := array_append(v_creditor_remaining,v_rec.net_amount);
  end loop;

  for v_source_i in 1..coalesce(array_length(v_sources,1),0) loop
    v_source_left := v_source_remaining[v_source_i];
    while v_source_left > 0 loop
      v_queue_nodes := array[v_sources[v_source_i]];
      v_queue_paths := array['[]'::jsonb];
      v_visited := array[v_sources[v_source_i]];
      v_queue_i := 1; v_target := null; v_found_path := null;
      while v_queue_i <= coalesce(array_length(v_queue_nodes,1),0) loop
        v_node := v_queue_nodes[v_queue_i];
        v_current_path := v_queue_paths[v_queue_i];
        v_queue_i := v_queue_i + 1;
        for v_creditor_i in 1..coalesce(array_length(v_creditors,1),0) loop
          if v_creditors[v_creditor_i]=v_node and v_creditor_remaining[v_creditor_i]>0 and jsonb_array_length(v_current_path)>0 then
            v_target := v_node; v_found_path := v_current_path; exit;
          end if;
        end loop;
        exit when v_target is not null;
        for v_edge_i in 1..v_edge_count loop
          if v_edge_from[v_edge_i]=v_node and v_edge_remaining[v_edge_i]>0
             and not (v_edge_to[v_edge_i]=any(v_visited)) then
            v_visited := array_append(v_visited,v_edge_to[v_edge_i]);
            v_queue_nodes := array_append(v_queue_nodes,v_edge_to[v_edge_i]);
            v_queue_paths := array_append(v_queue_paths,v_current_path || to_jsonb(v_edge_i));
          end if;
        end loop;
      end loop;
      if v_target is null then
        raise exception using errcode='P0001', message='final settlement flow cannot decompose directed debt graph';
      end if;
      v_match := v_source_left;
      for v_edge_path_text in select jsonb_array_elements_text(v_found_path) loop
        v_edge_path_i := v_edge_path_text::integer;
        v_match := least(v_match,v_edge_remaining[v_edge_path_i]);
      end loop;
      for v_creditor_i in 1..coalesce(array_length(v_creditors,1),0) loop
        if v_creditors[v_creditor_i]=v_target then
          v_match := least(v_match,v_creditor_remaining[v_creditor_i]); exit;
        end if;
      end loop;
      if v_match <= 0 then raise exception using errcode='P0001', message='final settlement flow has zero residual capacity'; end if;
      v_path_no := v_path_no + 1; v_hops := '[]'::jsonb; v_hop_no := 0;
      for v_edge_path_text in select jsonb_array_elements_text(v_found_path) loop
        v_edge_path_i := v_edge_path_text::integer; v_hop_no := v_hop_no + 1;
        v_hops := v_hops || jsonb_build_array(jsonb_build_object(
          'hop_no',v_hop_no,'from_participant_id',v_edge_from[v_edge_path_i],
          'to_participant_id',v_edge_to[v_edge_path_i],'amount',v_match));
        v_edge_remaining[v_edge_path_i] := v_edge_remaining[v_edge_path_i] - v_match;
      end loop;
      v_source_left := v_source_left - v_match; v_source_remaining[v_source_i] := v_source_left;
      for v_creditor_i in 1..coalesce(array_length(v_creditors,1),0) loop
        if v_creditors[v_creditor_i]=v_target then
          v_creditor_remaining[v_creditor_i] := v_creditor_remaining[v_creditor_i] - v_match; exit;
        end if;
      end loop;
      return query select v_path_no,v_sources[v_source_i],v_target,v_match::numeric(20,1),v_hops;
    end loop;
  end loop;
  for v_source_i in 1..coalesce(array_length(v_source_remaining,1),0) loop
    if v_source_remaining[v_source_i]<>0 then raise exception using errcode='P0001', message='final settlement source flow did not conserve'; end if;
  end loop;
  for v_creditor_i in 1..coalesce(array_length(v_creditor_remaining,1),0) loop
    if v_creditor_remaining[v_creditor_i]<>0 then raise exception using errcode='P0001', message='final settlement creditor flow did not conserve'; end if;
  end loop;
end;
$function$;

-- Return one deterministic activity-wide plan.  Flow paths with the same
-- endpoint are merged into one suggestion, while execution retains each
-- path group and its real hop capacities in final_settlement_paths.
create or replace function private.build_final_settlement_plan(p_activity_id uuid)
returns table(activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,1), ordinary_amount numeric(20,1), prepayment_return_amount numeric(20,1),
  currency character(3), source_financial_version bigint, is_prepayment_return boolean)
language plpgsql stable security definer set search_path = ''
as $function$
declare v_type public.activity_type; v_currency character(3); v_version bigint;
  v_from uuid[] := '{}'::uuid[]; v_to uuid[] := '{}'::uuid[];
  v_ordinary numeric[] := '{}'::numeric[]; v_returns numeric[] := '{}'::numeric[];
  v_n integer := 0; v_match integer; v_owner uuid; v_custodian uuid; v_balance numeric; v_flow record; v_uid uuid := (select auth.uid());
begin
  if v_uid is null then raise exception using errcode='28000',message='authentication is required'; end if;
  if not exists(select 1 from public.activity_members m where m.activity_id=p_activity_id and m.user_id=v_uid) then raise exception using errcode='42501',message='caller is not an activity member'; end if;
  select a.type,a.base_currency,a.financial_version into v_type,v_currency,v_version from public.activities a where a.id=p_activity_id and not a.is_deleted;
  if not found then raise exception using errcode='P0002',message='activity was not found'; end if;
  if v_type <> 'large'::public.activity_type then raise exception using errcode='23514',message='final settlement requires a large activity'; end if;
  for v_flow in
    select f.from_participant_id,f.to_participant_id,sum(f.amount)::numeric(20,1) ordinary_amount
    from private.build_final_settlement_flow(p_activity_id) f
    join public.participants fp on fp.activity_id=p_activity_id and fp.id=f.from_participant_id
    join public.participants tp on tp.activity_id=p_activity_id and tp.id=f.to_participant_id
    group by f.from_participant_id,f.to_participant_id,fp.participant_order,fp.id,tp.participant_order,tp.id
    order by fp.participant_order,fp.id,tp.participant_order,tp.id
  loop
    v_n:=v_n+1; v_from:=array_append(v_from,v_flow.from_participant_id); v_to:=array_append(v_to,v_flow.to_participant_id);
    v_ordinary:=array_append(v_ordinary,v_flow.ordinary_amount); v_returns:=array_append(v_returns,0::numeric);
  end loop;
  for v_owner,v_custodian,v_balance in select pa.owner_participant_id,pa.custodian_participant_id,pa.balance from public.prepayment_accounts pa where pa.activity_id=p_activity_id and pa.balance>0 order by pa.owner_participant_id,pa.custodian_participant_id loop
    v_match:=null;
    for v_i in 1..v_n loop if v_from[v_i]=v_custodian and v_to[v_i]=v_owner then v_match:=v_i; exit; end if; end loop;
    if v_match is null then v_n:=v_n+1; v_from:=array_append(v_from,v_custodian); v_to:=array_append(v_to,v_owner); v_ordinary:=array_append(v_ordinary,0::numeric); v_returns:=array_append(v_returns,v_balance); else v_returns[v_match]:=v_balance; end if;
  end loop;
  for v_i in 1..v_n loop
    if v_ordinary[v_i]>0 then return query select p_activity_id,v_from[v_i],v_to[v_i],(v_ordinary[v_i]+v_returns[v_i])::numeric(20,1),v_ordinary[v_i]::numeric(20,1),v_returns[v_i]::numeric(20,1),v_currency,v_version,false;
    elsif v_returns[v_i]>0 then return query select p_activity_id,v_from[v_i],v_to[v_i],v_returns[v_i]::numeric(20,1),0::numeric(20,1),v_returns[v_i]::numeric(20,1),v_currency,v_version,true; end if;
  end loop;
end;
$function$;

create or replace function public.preview_final_settlement(activity_id uuid)
returns table(activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,1), ordinary_amount numeric(20,1), prepayment_return_amount numeric(20,1),
  currency character(3), source_financial_version bigint, is_prepayment_return boolean)
language sql stable security invoker set search_path = '' as $function$
  select * from private.build_final_settlement_plan($1);
$function$;

create or replace function public.get_final_settlement_plan(activity_id uuid)
returns table(activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,1), ordinary_amount numeric(20,1), prepayment_return_amount numeric(20,1),
  currency character(3), source_financial_version bigint, is_prepayment_return boolean)
language sql stable security invoker set search_path = '' as $function$
  select * from private.build_final_settlement_plan($1);
$function$;

-- Compatibility name from the backend API contract. It has the same
-- read-only, non-persistent semantics as preview_final_settlement.
create or replace function public.preview_activity_settlement(activity_id uuid)
returns table(activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,1), ordinary_amount numeric(20,1), prepayment_return_amount numeric(20,1),
  currency character(3), source_financial_version bigint, is_prepayment_return boolean)
language sql stable security invoker set search_path = '' as $function$
  select * from private.build_final_settlement_plan($1);
$function$;

-- Create one actual final_settlement fact after taking both the Activity
-- advisory lock and Activity row lock, then recompute and match the requested
-- item. Path rows intentionally are not TransferAllocations and need not sum
-- to Transfer.amount (a multi-edge path repeats the same settled amount).
create or replace function private.create_final_settlement_impl(
  p_activity_id uuid, p_from_participant_id uuid, p_to_participant_id uuid,
  p_amount numeric(20,1), p_occurred_at timestamptz,
  p_on_behalf_of_participant_id uuid
)
returns table(transfer_id uuid, amount numeric(20,1), currency character(3), financial_version bigint)
language plpgsql volatile security definer set search_path = ''
as $function$
declare
  v_plan record; v_flow record; v_hop record; v_currency character(3); v_archived_at timestamptz;
  v_type public.activity_type; v_transfer_id uuid; v_version bigint;
  v_uid uuid := (select auth.uid()); v_path_order integer := 0; v_source_expense uuid;
  v_ordinary_total numeric(20,1); v_return_path_no integer;
begin
  if p_amount is null or p_amount <= 0 or p_from_participant_id is null
     or p_to_participant_id is null or p_from_participant_id = p_to_participant_id
     or p_occurred_at is null then
    raise exception using errcode = '22023', message = 'invalid final settlement';
  end if;
  perform private.lock_debt_projection_activity(p_activity_id);
  select a.type, a.base_currency, a.archived_at
    into v_type, v_currency, v_archived_at
  from public.activities a where a.id = p_activity_id and not a.is_deleted for update;
  if not found then raise exception using errcode = 'P0002', message = 'activity was not found'; end if;
  if v_type <> 'large'::public.activity_type then
    raise exception using errcode = '23514', message = 'final settlement requires a large activity';
  end if;
  if v_archived_at is not null then raise exception using errcode = '55000', message = 'archived activity is read-only'; end if;
  perform private.authorize_phase5_actor(p_activity_id, p_from_participant_id,
    p_to_participant_id, p_on_behalf_of_participant_id);
  select plan.* into v_plan from private.build_final_settlement_plan(p_activity_id) plan
    where plan.from_participant_id = p_from_participant_id
      and plan.to_participant_id = p_to_participant_id
      and plan.amount = p_amount;
  if not found then raise exception using errcode = '23514', message = 'final settlement does not match current plan'; end if;

  select coalesce(sum(f.amount),0)::numeric(20,1) into v_ordinary_total
  from private.build_final_settlement_flow(p_activity_id) f
  where f.from_participant_id=p_from_participant_id and f.to_participant_id=p_to_participant_id;
  if v_ordinary_total <> v_plan.ordinary_amount then
    raise exception using errcode='23514', message='final settlement flow changed while validating plan';
  end if;

  insert into public.transfers(activity_id, from_participant_id, to_participant_id,
    type, amount, currency, occurred_at, recorded_by, on_behalf_of_participant_id)
  values(p_activity_id, p_from_participant_id, p_to_participant_id,
    'final_settlement', p_amount, v_currency, p_occurred_at, v_uid,
    p_on_behalf_of_participant_id) returning id into v_transfer_id;
  if v_plan.ordinary_amount > 0 then
    insert into public.transfer_components(activity_id, transfer_id, component_type, amount)
    values(p_activity_id, v_transfer_id, 'settlement', v_plan.ordinary_amount);
  end if;
  if v_plan.prepayment_return_amount > 0 then
    insert into public.transfer_components(activity_id, transfer_id, component_type, amount)
    values(p_activity_id, v_transfer_id, 'prepayment_return', v_plan.prepayment_return_amount);
  end if;
  perform private.assert_component_total(v_transfer_id);

  -- Persist every residual-flow path and every capacity-limited hop exactly
  -- as emitted by the validator; no direct edge is fabricated.
  for v_flow in select f.* from private.build_final_settlement_flow(p_activity_id) f
    where f.from_participant_id=p_from_participant_id and f.to_participant_id=p_to_participant_id
    order by f.path_no
  loop
    for v_hop in select * from jsonb_to_recordset(v_flow.hops) as h(hop_no integer,from_participant_id uuid,to_participant_id uuid,amount numeric)
    loop
      v_path_order := v_path_order + 1;
      select ed.expense_id into v_source_expense from public.expense_debts ed join public.expenses e on e.id=ed.expense_id
      where ed.activity_id=p_activity_id and ed.debtor_participant_id=v_hop.from_participant_id and ed.creditor_participant_id=v_hop.to_participant_id
      order by e.occurred_at,e.created_at,e.id limit 1;
      insert into public.final_settlement_paths(activity_id,transfer_id,path_order,path_no,hop_no,from_participant_id,to_participant_id,amount,component_type,source_expense_id)
      values(p_activity_id,v_transfer_id,v_path_order,v_flow.path_no,v_hop.hop_no,v_hop.from_participant_id,v_hop.to_participant_id,v_hop.amount,'settlement',v_source_expense);
    end loop;
  end loop;
  if v_plan.prepayment_return_amount > 0 then
    select coalesce(max(f.path_no),0)+1 into v_return_path_no
    from public.final_settlement_paths f where f.transfer_id=v_transfer_id;
    v_path_order := v_path_order + 1;
    insert into public.final_settlement_paths(activity_id, transfer_id, path_order, path_no, hop_no,
      from_participant_id, to_participant_id, amount, component_type)
    values(p_activity_id, v_transfer_id, v_path_order, v_return_path_no, 1, p_from_participant_id,
      p_to_participant_id, v_plan.prepayment_return_amount, 'prepayment_return');
  end if;

  perform private.phase5_rebuild_after_transfer(p_activity_id);
  update public.activities a set financial_version = a.financial_version + 1
    where a.id = p_activity_id returning a.financial_version into v_version;
  return query select v_transfer_id, p_amount, v_currency, v_version;
end;
$function$;

create or replace function public.create_final_settlement(
  activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,1), occurred_at timestamptz default pg_catalog.now(),
  on_behalf_of_participant_id uuid default null)
returns table(transfer_id uuid, amount numeric(20,1), currency character(3), financial_version bigint)
language sql volatile security invoker set search_path = '' as $function$
  select * from private.create_final_settlement_impl($1,$2,$3,$4,$5,$6);
$function$;

-- A descriptive alias for clients that use the verb from the product copy.
create or replace function public.execute_final_settlement(
  activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,1), occurred_at timestamptz default pg_catalog.now(),
  on_behalf_of_participant_id uuid default null)
returns table(transfer_id uuid, amount numeric(20,1), currency character(3), financial_version bigint)
language sql volatile security invoker set search_path = '' as $function$
  select * from private.create_final_settlement_impl($1,$2,$3,$4,$5,$6);
$function$;

create or replace function public.execute_final_settlement_item(
  activity_id uuid, from_participant_id uuid, to_participant_id uuid,
  amount numeric(20,1), occurred_at timestamptz default pg_catalog.now(),
  on_behalf_of_participant_id uuid default null)
returns table(transfer_id uuid, amount numeric(20,1), currency character(3), financial_version bigint)
language sql volatile security invoker set search_path = '' as $function$
  select * from private.create_final_settlement_impl($1,$2,$3,$4,$5,$6);
$function$;

-- Permit the existing void endpoint to reverse final settlement facts too.
create or replace function private.void_prepayment_transfer_impl(tid uuid, reason text)
returns table(transfer_id uuid, voided boolean, financial_version bigint)
language plpgsql volatile security definer set search_path = ''
as $function$
declare aid uuid; rec uuid; v boolean; cr boolean; ar timestamptz; ver bigint; u uuid := (select auth.uid());
begin
  if u is null then raise exception using errcode = '28000', message = 'authentication is required'; end if;
  if reason is null or length(btrim(reason)) = 0 then raise exception using errcode = '22023', message = 'void reason is required'; end if;
  select activity_id into aid from public.transfers where id = tid;
  if not found then raise exception using errcode = 'P0002', message = 'transfer was not found'; end if;
  perform private.lock_debt_projection_activity(aid);
  select t.recorded_by, t.is_voided, a.created_by = u, a.archived_at
    into rec, v, cr, ar
  from public.transfers t join public.activities a on a.id = t.activity_id
  where t.id = tid and t.type in ('settlement','prepayment','prepayment_return','final_settlement')
    and not a.is_deleted for update of t,a;
  if not found then raise exception using errcode = 'P0002', message = 'financial transfer was not found'; end if;
  if ar is not null then raise exception using errcode = '55000', message = 'archived activity is read-only'; end if;
  if not exists(select 1 from public.activity_members where activity_id = aid and user_id = u) then raise exception using errcode = '42501', message = 'caller is not an activity member'; end if;
  if v then raise exception using errcode = '55000', message = 'transfer is already voided'; end if;
  if not cr and rec <> u then raise exception using errcode = '42501', message = 'member may void only a transfer they recorded'; end if;
  update public.transfers set is_voided=true, voided_at=pg_catalog.now(), voided_by=u, void_reason=btrim(reason) where id=tid;
  perform private.phase5_rebuild_after_transfer(aid);
  update public.activities a set financial_version=a.financial_version+1 where a.id=aid returning a.financial_version into ver;
  return query select tid, true, ver;
end;
$function$;

create or replace function private.archive_activity_impl(p_activity_id uuid)
returns table(activity_id uuid, archived boolean, changed boolean, archived_at timestamptz,
  total_debt numeric(20,1), total_prepayment numeric(20,1), completed boolean, has_unsettled boolean, warning text)
language plpgsql volatile security definer set search_path = ''
as $function$
declare u uuid := (select auth.uid()); creator uuid; deleted boolean; old_archived timestamptz; v_changed boolean; debt numeric; prepay numeric;
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
  select coalesce(sum(b.amount),0)::numeric(20,1) into debt from public.bilateral_debts b where b.activity_id=p_activity_id;
  select coalesce(sum(pa.balance),0)::numeric(20,1) into prepay from public.prepayment_accounts pa where pa.activity_id=p_activity_id;
  v_changed := old_archived is null;
  if v_changed then update public.activities a set archived_at=pg_catalog.now() where a.id=p_activity_id returning a.archived_at into old_archived; end if;
  return query select p_activity_id, true, v_changed, old_archived, debt, prepay,
    (debt=0 and prepay=0), (debt>0 or prepay>0),
    case when debt>0 or prepay>0 then 'activity has unsettled debt or prepayment balance' else null end;
end;
$function$;

create or replace function private.unarchive_activity_impl(p_activity_id uuid)
returns table(activity_id uuid, archived boolean, changed boolean, archived_at timestamptz,
  total_debt numeric(20,1), total_prepayment numeric(20,1), completed boolean, has_unsettled boolean, warning text)
language plpgsql volatile security definer set search_path = ''
as $function$
declare u uuid := (select auth.uid()); creator uuid; deleted boolean; old_archived timestamptz; debt numeric; prepay numeric;
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
  select coalesce(sum(b.amount),0)::numeric(20,1) into debt from public.bilateral_debts b where b.activity_id=p_activity_id;
  select coalesce(sum(pa.balance),0)::numeric(20,1) into prepay from public.prepayment_accounts pa where pa.activity_id=p_activity_id;
  return query select p_activity_id, false, (old_archived is not null), null::timestamptz, debt, prepay,
    (debt=0 and prepay=0), (debt>0 or prepay>0),
    case when debt>0 or prepay>0 then 'activity has unsettled debt or prepayment balance' else null end;
end;
$function$;

create or replace function public.archive_activity(p_activity_id uuid)
returns table(activity_id uuid, archived boolean, changed boolean, archived_at timestamptz,
  total_debt numeric(20,1), total_prepayment numeric(20,1), completed boolean, has_unsettled boolean, warning text)
language sql volatile security invoker set search_path = '' as $function$
  select * from private.archive_activity_impl($1);
$function$;

create or replace function public.unarchive_activity(p_activity_id uuid)
returns table(activity_id uuid, archived boolean, changed boolean, archived_at timestamptz,
  total_debt numeric(20,1), total_prepayment numeric(20,1), completed boolean, has_unsettled boolean, warning text)
language sql volatile security invoker set search_path = '' as $function$
  select * from private.unarchive_activity_impl($1);
$function$;

create or replace view public.activity_financial_status
with (security_invoker = true) as
select a.id as activity_id, a.type, a.financial_version, a.archived_at,
  case when coalesce(d.total_debt,0)=0 and coalesce(p.total_prepayment,0)=0 then 'completed' else 'active' end as financial_status,
  (coalesce(d.total_debt,0)=0 and coalesce(p.total_prepayment,0)=0) as completed,
  coalesce(d.total_debt,0)::numeric(20,1) as total_debt,
  coalesce(p.total_prepayment,0)::numeric(20,1) as total_prepayment
from public.activities a
left join (select activity_id, sum(amount)::numeric(20,1) total_debt from public.bilateral_debts group by activity_id) d on d.activity_id=a.id
left join (select activity_id, sum(balance)::numeric(20,1) total_prepayment from public.prepayment_accounts group by activity_id) p on p.activity_id=a.id
where not a.is_deleted;

create or replace view public.participant_financial_status
with (security_invoker = true) as
with debt as (
  select p.activity_id, p.id as participant_id,
    coalesce(sum(case when b.creditor_participant_id=p.id then b.amount else 0 end),0)::numeric(20,1) receivable,
    coalesce(sum(case when b.debtor_participant_id=p.id then b.amount else 0 end),0)::numeric(20,1) payable
  from public.participants p left join public.bilateral_debts b on b.activity_id=p.activity_id
    and (b.creditor_participant_id=p.id or b.debtor_participant_id=p.id)
  where not p.is_deleted group by p.activity_id,p.id
), prepayment as (
  select activity_id, owner_participant_id participant_id,
    coalesce(sum(balance),0)::numeric(20,1) receivable, 0::numeric(20,1) payable
  from public.prepayment_accounts group by activity_id,owner_participant_id
  union all
  select activity_id, custodian_participant_id,
    0::numeric(20,1), coalesce(sum(balance),0)::numeric(20,1)
  from public.prepayment_accounts group by activity_id,custodian_participant_id
), all_balances as (
  select activity_id,participant_id,receivable,payable from debt
  union all select activity_id,participant_id,receivable,payable from prepayment
), totals as (
  select activity_id,participant_id,sum(receivable)::numeric(20,1) receivable,
    sum(payable)::numeric(20,1) payable from all_balances group by activity_id,participant_id
)
select p.activity_id, p.id as participant_id, p.participant_order,
  coalesce(t.receivable,0)::numeric(20,1) as receivable,
  coalesce(t.payable,0)::numeric(20,1) as payable,
  (coalesce(t.receivable,0)-coalesce(t.payable,0))::numeric(20,1) as net_balance,
  case when coalesce(t.receivable,0)=0 and coalesce(t.payable,0)=0 then 'completed' else 'active' end as financial_status,
  (coalesce(t.receivable,0)=0 and coalesce(t.payable,0)=0) as completed
from public.participants p left join totals t on t.activity_id=p.activity_id and t.participant_id=p.id
where not p.is_deleted;

-- Archived activities are immutable through the Data API.  The public wrappers
-- are invoker functions; private implementations cross RLS only after the
-- creator check and Activity row lock.
revoke update (archived_at) on table public.activities from authenticated;

-- Archived activities are immutable across all collaboration tables too.  The
-- OLD check closes the move-out loophole on ledger_units/participants, while
-- the NEW check blocks joins and other move-ins to an archived Activity.
create or replace function private.assert_activity_writable_row()
returns trigger language plpgsql security definer set search_path = '' as $function$
declare old_activity uuid; new_activity uuid;
begin
  if tg_op <> 'INSERT' then old_activity := old.activity_id; end if;
  if tg_op <> 'DELETE' then new_activity := new.activity_id; end if;
  if (old_activity is not null and exists(select 1 from public.activities a where a.id=old_activity and a.archived_at is not null))
     or (new_activity is not null and exists(select 1 from public.activities a where a.id=new_activity and a.archived_at is not null)) then
    raise exception using errcode='55000', message='archived activity is read-only';
  end if;
  if tg_op='DELETE' then return old; end if;
  return new;
end;
$function$;
drop trigger if exists activity_members_activity_writable on public.activity_members;
create trigger activity_members_activity_writable before insert or update or delete on public.activity_members
for each row execute function private.assert_activity_writable_row();
drop trigger if exists participants_activity_writable on public.participants;
create trigger participants_activity_writable before insert or update or delete on public.participants
for each row execute function private.assert_activity_writable_row();
drop trigger if exists participant_claims_activity_writable on public.participant_claims;
create trigger participant_claims_activity_writable before insert or update or delete on public.participant_claims
for each row execute function private.assert_activity_writable_row();
drop trigger if exists ledger_units_activity_writable_row on public.ledger_units;
create trigger ledger_units_activity_writable_row before insert or update or delete on public.ledger_units
for each row execute function private.assert_activity_writable_row();
revoke all on function private.assert_activity_writable_row() from public,anon,authenticated;

-- Activities already expose no authenticated business-field update path; make
-- the direct DML boundary explicit so only the archive RPC can toggle it.
revoke insert, update, delete on table public.activities from authenticated;

-- Joining is a lifecycle write even when the caller is already a member (the
-- latter is otherwise an idempotent no-op), so reject archived activities
-- before the conflict-handled membership insert.
create or replace function private.join_activity_by_code_impl(p_join_code text)
returns table(joined_activity_id uuid, is_new boolean)
language plpgsql security definer set search_path = ''
as $function$
declare v_user_id uuid := (select auth.uid()); v_activity_id uuid; v_archived_at timestamptz; v_is_new boolean;
begin
  if v_user_id is null then raise exception using errcode='28000',message='authenticated user is required'; end if;
  if p_join_code is null or p_join_code !~ '^[0-9]{8}$' then raise exception using errcode='22023',message='join_code must be an 8 digit string'; end if;
  select a.id,a.archived_at into v_activity_id,v_archived_at from public.activities a where a.join_code=p_join_code and not a.is_deleted for update;
  if not found then raise exception using errcode='P0002',message='activity not found'; end if;
  if v_archived_at is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if;
  insert into public.activity_members(activity_id,user_id) values(v_activity_id,v_user_id) on conflict(activity_id,user_id) do nothing;
  v_is_new := found;
  return query select v_activity_id,v_is_new;
end;
$function$;

revoke all on function private.build_final_settlement_flow(uuid), private.build_final_settlement_plan(uuid), private.create_final_settlement_impl(uuid,uuid,uuid,numeric,timestamptz,uuid), private.archive_activity_impl(uuid), private.unarchive_activity_impl(uuid) from public,anon,authenticated;
grant execute on function private.build_final_settlement_plan(uuid) to authenticated;
grant execute on function private.create_final_settlement_impl(uuid,uuid,uuid,numeric,timestamptz,uuid), private.archive_activity_impl(uuid), private.unarchive_activity_impl(uuid) to authenticated;
revoke all on function public.preview_final_settlement(uuid), public.get_final_settlement_plan(uuid), public.preview_activity_settlement(uuid), public.create_final_settlement(uuid,uuid,uuid,numeric,timestamptz,uuid), public.execute_final_settlement(uuid,uuid,uuid,numeric,timestamptz,uuid), public.execute_final_settlement_item(uuid,uuid,uuid,numeric,timestamptz,uuid), public.archive_activity(uuid), public.unarchive_activity(uuid) from public,anon,authenticated;
grant execute on function public.preview_final_settlement(uuid), public.get_final_settlement_plan(uuid), public.preview_activity_settlement(uuid), public.create_final_settlement(uuid,uuid,uuid,numeric,timestamptz,uuid), public.execute_final_settlement(uuid,uuid,uuid,numeric,timestamptz,uuid), public.execute_final_settlement_item(uuid,uuid,uuid,numeric,timestamptz,uuid), public.archive_activity(uuid), public.unarchive_activity(uuid) to authenticated;
revoke all on table public.activity_financial_status, public.participant_financial_status from public,anon,authenticated;
grant select on public.activity_financial_status, public.participant_financial_status to authenticated;

commit;
