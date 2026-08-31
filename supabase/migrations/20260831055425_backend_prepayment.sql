begin;

-- Components are immutable transfer facts.  They are intentionally written by
-- explicit RPC code below, never by a trigger.
create table public.transfer_components (
 id uuid primary key default extensions.gen_random_uuid(), activity_id uuid not null references public.activities(id) on delete restrict,
 transfer_id uuid not null, component_type text not null check(component_type in ('settlement','prepayment','prepayment_return')),
 amount numeric(20,1) not null check(amount>0), created_at timestamptz not null default pg_catalog.now(),
 unique(transfer_id,component_type), unique(id,activity_id,transfer_id), foreign key(transfer_id,activity_id) references public.transfers(id,activity_id) on delete cascade
);
create index transfer_components_activity_transfer_idx on public.transfer_components(activity_id,transfer_id);
alter table public.transfer_allocations add column settlement_component_id uuid;
alter table public.transfer_allocations add constraint transfer_allocations_settlement_component_fk foreign key(settlement_component_id,activity_id,transfer_id) references public.transfer_components(id,activity_id,transfer_id) on delete restrict;
create index transfer_allocations_component_idx on public.transfer_allocations(settlement_component_id);
create table public.prepayment_accounts (
 id uuid primary key default extensions.gen_random_uuid(), activity_id uuid not null references public.activities(id) on delete restrict,
 owner_participant_id uuid not null, custodian_participant_id uuid not null, balance numeric(20,1) not null default 0 check(balance>=0), updated_at timestamptz not null default pg_catalog.now(),
 check(owner_participant_id<>custodian_participant_id), unique(activity_id,owner_participant_id,custodian_participant_id), unique(id,activity_id),
 foreign key(activity_id,owner_participant_id) references public.participants(activity_id,id), foreign key(activity_id,custodian_participant_id) references public.participants(activity_id,id)
);
 create index prepayment_accounts_custodian_idx on public.prepayment_accounts(activity_id,custodian_participant_id);
create table public.prepayment_usages (
 id uuid primary key default extensions.gen_random_uuid(), activity_id uuid not null references public.activities(id) on delete restrict,
 account_id uuid not null, expense_debt_id uuid not null,
 gross_amount numeric(20,1) not null check(gross_amount>0), amount numeric(20,1) not null check(amount>0 and amount<=gross_amount), created_at timestamptz not null default pg_catalog.now(),
 unique(account_id,expense_debt_id), foreign key(account_id,activity_id) references public.prepayment_accounts(id,activity_id) on delete cascade, foreign key(activity_id,expense_debt_id) references public.expense_debts(activity_id,id) on delete cascade
);
create index prepayment_usages_activity_debt_idx on public.prepayment_usages(activity_id,expense_debt_id);
alter table public.transfer_components enable row level security; alter table public.prepayment_accounts enable row level security; alter table public.prepayment_usages enable row level security;
create policy transfer_components_member_read on public.transfer_components for select to authenticated using((select private.is_activity_member(activity_id)));
create policy prepayment_accounts_member_read on public.prepayment_accounts for select to authenticated using((select private.is_activity_member(activity_id)));
create policy prepayment_usages_member_read on public.prepayment_usages for select to authenticated using((select private.is_activity_member(activity_id)));
revoke all on public.transfer_components,public.prepayment_accounts,public.prepayment_usages from public,anon,authenticated;
grant select on public.transfer_components,public.prepayment_accounts,public.prepayment_usages to authenticated; grant all on public.transfer_components,public.prepayment_accounts,public.prepayment_usages to service_role;

-- Historical voided settlements are facts too, hence get a component. Effective
-- projection queries always also require not is_voided.
insert into public.transfer_components(activity_id,transfer_id,component_type,amount)
select activity_id,id,'settlement',amount from public.transfers where type='settlement'::public.transfer_type;

-- Resolve existing Phase 4 allocations to their immutable settlement fact
-- before enforcing the component relationship for all future projections.
update public.transfer_allocations ta
set settlement_component_id = tc.id
from public.transfer_components tc
where tc.transfer_id = ta.transfer_id
  and tc.activity_id = ta.activity_id
  and tc.component_type = 'settlement'
  and ta.settlement_component_id is null;
do $check$
begin
  if exists (select 1 from public.transfer_allocations where settlement_component_id is null) then
    raise exception 'historical transfer allocation has no settlement component';
  end if;
end
$check$;
alter table public.transfer_allocations alter column settlement_component_id set not null;

create or replace function private.assert_component_total(p_transfer uuid) returns void language plpgsql stable security definer set search_path='' as $function$
declare a numeric; s numeric; begin select amount into a from public.transfers where id=p_transfer; select coalesce(sum(amount),0) into s from public.transfer_components where transfer_id=p_transfer; if a is null or a<>s then raise exception using errcode='23514',message='transfer component total must equal transfer amount'; end if; end;$function$;

create or replace function private.rebuild_transfer_allocations_locked(p_activity_id uuid) returns void language plpgsql volatile security definer set search_path='' as $function$
declare p_activity uuid:=p_activity_id; t record; d record; r numeric; x numeric; begin
 delete from public.transfer_allocations where activity_id=p_activity;
 for t in select tr.id,tr.from_participant_id,tr.to_participant_id,c.id component_id,c.amount from public.transfers tr join public.transfer_components c on c.transfer_id=tr.id and c.activity_id=tr.activity_id where tr.activity_id=p_activity and not tr.is_voided and c.component_type='settlement' order by tr.occurred_at,tr.created_at,tr.id loop
  r:=t.amount;
  for d in with q as (select ed.id,ed.amount,e.occurred_at,e.created_at,e.id eid,coalesce(sum(ed.amount) over(order by e.occurred_at,e.created_at,e.id rows between unbounded preceding and 1 preceding),0) prior,coalesce((select sum(z.amount) from public.expense_debts z where z.activity_id=p_activity and z.debtor_participant_id=t.to_participant_id and z.creditor_participant_id=t.from_participant_id),0) reverse_total from public.expense_debts ed join public.expenses e on e.id=ed.expense_id where ed.activity_id=p_activity and ed.debtor_participant_id=t.from_participant_id and ed.creditor_participant_id=t.to_participant_id) select id,amount-least(amount,greatest(reverse_total-prior,0))-coalesce((select sum(amount) from public.transfer_allocations where expense_debt_id=q.id),0) avail from q order by occurred_at,created_at,eid loop
   if d.avail>0 then x:=least(r,d.avail)::numeric(20,1); insert into public.transfer_allocations(activity_id,transfer_id,settlement_component_id,expense_debt_id,amount) values(p_activity,t.id,t.component_id,d.id,x); r:=r-x; exit when r=0; end if;
  end loop;
 end loop;
end;$function$;

-- The final projection first incorporates real settlement components, then
-- actual prepayment use. A linked-refund restoration cancels only its matching
-- negative debt amount; any excess remains a normal reverse debt.
-- Final three-stage implementation. Stage 1 creates every account and gross
-- FIFO usage after ordinary settlement and *generic* reverse debt only. Stage
-- 2 distributes each linked refund's negative Split benefit across all of the
-- original expense/owner usages globally. Stage 3 derives each balance.
create or replace function private.rebuild_prepayment_projections_locked(p_activity_id uuid) returns void language plpgsql volatile security definer set search_path='' as $function$
declare a record; d record; u record; aid uuid; left_amt numeric; take numeric; refund_left numeric; settlement_total numeric; reverse_total numeric; begin
 delete from public.prepayment_usages where activity_id=p_activity_id; delete from public.prepayment_accounts where activity_id=p_activity_id;
 if exists (with f as (select t.from_participant_id owner,t.to_participant_id cust,c.amount delta from public.transfers t join public.transfer_components c on c.transfer_id=t.id where t.activity_id=p_activity_id and not t.is_voided and c.component_type='prepayment' union all select t.to_participant_id,t.from_participant_id,-c.amount from public.transfers t join public.transfer_components c on c.transfer_id=t.id where t.activity_id=p_activity_id and not t.is_voided and c.component_type='prepayment_return') select 1 from f group by owner,cust having sum(delta)<0) then raise exception using errcode='23514',message='prepayment returns exceed funding'; end if;
 for a in with f as (select t.from_participant_id owner,t.to_participant_id cust,c.amount delta from public.transfers t join public.transfer_components c on c.transfer_id=t.id where t.activity_id=p_activity_id and not t.is_voided and c.component_type='prepayment' union all select t.to_participant_id,t.from_participant_id,-c.amount from public.transfers t join public.transfer_components c on c.transfer_id=t.id where t.activity_id=p_activity_id and not t.is_voided and c.component_type='prepayment_return') select owner,cust,sum(delta)::numeric(20,1) funded from f group by owner,cust having sum(delta)>0 loop
  left_amt:=a.funded; insert into public.prepayment_accounts(activity_id,owner_participant_id,custodian_participant_id,balance) values(p_activity_id,a.owner,a.cust,left_amt) returning id into aid;
  -- Gross residual is calculated from all bilateral facts except active linked
  -- refunds, then reduced by effective settlement components. This preserves
  -- reverse positive/negative Expenses and historical settlement overpayment.
  select coalesce(sum(case when t.from_participant_id=a.owner and t.to_participant_id=a.cust then c.amount when t.from_participant_id=a.cust and t.to_participant_id=a.owner then -c.amount else 0 end),0)
    into settlement_total
   from public.transfers t join public.transfer_components c on c.transfer_id=t.id
   where t.activity_id=p_activity_id and not t.is_voided and c.component_type='settlement'
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
 -- One linked refund's owner benefit is allocated over all matching gross
 -- usages, not separately per account; this enforces the cumulative cap.
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

/* create or replace function private.rebuild_bilateral_debts_locked(p_activity_id uuid) returns void language plpgsql volatile security definer set search_path='' as $function$
declare p_activity uuid:=p_activity_id; begin delete from public.bilateral_debts where activity_id=p_activity;
insert into public.bilateral_debts(activity_id,debtor_participant_id,creditor_participant_id,amount)
with f as (
 select ed.activity_id,least(ed.debtor_participant_id,ed.creditor_participant_id) lo,greatest(ed.debtor_participant_id,ed.creditor_participant_id) hi,case when ed.debtor_participant_id<ed.creditor_participant_id then ed.amount else -ed.amount end s from public.expense_debts ed where ed.activity_id=p_activity
 union all select t.activity_id,least(t.from_participant_id,t.to_participant_id),greatest(t.from_participant_id,t.to_participant_id),case when t.from_participant_id<t.to_participant_id then -c.amount else c.amount end from public.transfers t join public.transfer_components c on c.transfer_id=t.id where t.activity_id=p_activity and not t.is_voided and c.component_type='settlement'
 union all select pa.activity_id,least(pa.owner_participant_id,pa.custodian_participant_id),greatest(pa.owner_participant_id,pa.custodian_participant_id),case when pa.owner_participant_id<pa.custodian_participant_id then -pu.amount else pu.amount end from public.prepayment_usages pu join public.prepayment_accounts pa on pa.id=pu.account_id where pa.activity_id=p_activity
 union all select pa.activity_id,least(rd.debtor_participant_id,rd.creditor_participant_id),greatest(rd.debtor_participant_id,rd.creditor_participant_id),case when rd.debtor_participant_id<rd.creditor_participant_id then -(pu.gross_amount-pu.amount) else pu.gross_amount-pu.amount end from public.prepayment_usages pu join public.prepayment_accounts pa on pa.id=pu.account_id join public.expense_debts od on od.id=pu.expense_debt_id join public.expenses rf on rf.original_expense_id=od.expense_id and rf.base_amount<0 join public.expense_debts rd on rd.expense_id=rf.id where pa.activity_id=p_activity and rd.debtor_participant_id=pa.custodian_participant_id and rd.creditor_participant_id=pa.owner_participant_id
),n as (select activity_id,lo,hi,sum(s) s from f group by activity_id,lo,hi) select activity_id,case when s>0 then lo else hi end,case when s>0 then hi else lo end,abs(s)::numeric(20,1) from n where s<>0;
end;$function$; */

-- Linked refunds have already changed actual usage above, so bilateral debt is
-- simply signed ExpenseDebt plus settlement facts minus actual usage.
create or replace function private.rebuild_bilateral_debts_locked(p_activity_id uuid) returns void language plpgsql volatile security definer set search_path='' as $function$
begin
 delete from public.bilateral_debts where activity_id=p_activity_id;
 insert into public.bilateral_debts(activity_id,debtor_participant_id,creditor_participant_id,amount)
 with f as (
  select ed.activity_id,least(ed.debtor_participant_id,ed.creditor_participant_id) lo,greatest(ed.debtor_participant_id,ed.creditor_participant_id) hi,case when ed.debtor_participant_id<ed.creditor_participant_id then ed.amount else -ed.amount end s from public.expense_debts ed where ed.activity_id=p_activity_id
  union all select t.activity_id,least(t.from_participant_id,t.to_participant_id),greatest(t.from_participant_id,t.to_participant_id),case when t.from_participant_id<t.to_participant_id then -tc.amount else tc.amount end from public.transfers t join public.transfer_components tc on tc.transfer_id=t.id where t.activity_id=p_activity_id and not t.is_voided and tc.component_type='settlement'
  union all select pa.activity_id,least(pa.owner_participant_id,pa.custodian_participant_id),greatest(pa.owner_participant_id,pa.custodian_participant_id),case when pa.owner_participant_id<pa.custodian_participant_id then -pu.amount else pu.amount end from public.prepayment_usages pu join public.prepayment_accounts pa on pa.id=pu.account_id where pa.activity_id=p_activity_id
 ),n as (select activity_id,lo,hi,sum(s) s from f group by activity_id,lo,hi) select activity_id,case when s>0 then lo else hi end,case when s>0 then hi else lo end,abs(s)::numeric(20,1) from n where s<>0;
end;$function$;

create or replace function private.rebuild_expense_and_bilateral_debts(p_expense_id uuid,p_activity_id uuid) returns void language plpgsql volatile security definer set search_path='' as $function$
declare p_activity uuid:=p_activity_id; begin perform private.lock_debt_projection_activity(p_activity_id); perform private.rebuild_expense_debts_locked(p_expense_id,p_activity); perform private.rebuild_transfer_allocations_locked(p_activity); perform private.rebuild_prepayment_projections_locked(p_activity); perform private.rebuild_bilateral_debts_locked(p_activity); update public.activities set financial_version=financial_version+1 where id=p_activity; end;$function$;
create or replace function private.rebuild_activity_debt_projection(p_activity_id uuid) returns void language plpgsql volatile security definer set search_path='' as $function$
declare e uuid; begin if not exists(select 1 from public.activities where id=p_activity_id) then raise exception using errcode='P0002',message='activity was not found for debt rebuild'; end if; perform private.lock_debt_projection_activity(p_activity_id); delete from public.prepayment_usages where activity_id=p_activity_id; delete from public.prepayment_accounts where activity_id=p_activity_id; delete from public.transfer_allocations where activity_id=p_activity_id; delete from public.expense_debts where activity_id=p_activity_id; for e in select x.id from public.expenses x join public.ledger_units l on l.id=x.ledger_unit_id join public.activities a on a.id=l.activity_id where l.activity_id=p_activity_id and not x.is_deleted and not l.is_deleted and not a.is_deleted order by x.id loop perform private.rebuild_expense_debts_locked(e,p_activity_id); end loop; perform private.rebuild_transfer_allocations_locked(p_activity_id); perform private.rebuild_prepayment_projections_locked(p_activity_id); perform private.rebuild_bilateral_debts_locked(p_activity_id); end;$function$;

create or replace function private.authorize_phase5_actor(aid uuid,fr uuid,too uuid,behalf uuid) returns void language plpgsql stable security definer set search_path='' as $function$
declare u uuid:=(select auth.uid()); cr boolean; cl uuid; begin if u is null then raise exception using errcode='28000',message='authentication is required'; end if; if not exists(select 1 from public.activity_members where activity_id=aid and user_id=u) then raise exception using errcode='42501',message='caller is not an activity member'; end if; select created_by=u into cr from public.activities where id=aid; select participant_id into cl from public.participant_claims where activity_id=aid and user_id=u; if cr then if behalf is not null then if behalf not in(fr,too) or exists(select 1 from public.participant_claims where activity_id=aid and participant_id=behalf) then raise exception using errcode='42501',message='creator may act only for unclaimed transfer party'; end if; elsif cl is null or cl not in(fr,too) then raise exception using errcode='42501',message='creator must be party or act on behalf'; end if; elsif behalf is not null or cl is null or cl not in(fr,too) then raise exception using errcode='42501',message='member must use claimed participant'; end if; end;$function$;
create or replace function private.phase5_rebuild_after_transfer(aid uuid) returns void language plpgsql volatile security definer set search_path='' as $function$ begin perform private.rebuild_transfer_allocations_locked(aid); perform private.rebuild_prepayment_projections_locked(aid); perform private.rebuild_bilateral_debts_locked(aid); end;$function$;

-- Phase 4 settlement creator is explicitly replaced so its component is part
-- of the same fact transaction; no component trigger participates.
create or replace function private.create_settlement_transfer_impl(p_activity_id uuid,p_from_participant_id uuid,p_to_participant_id uuid,p_amount numeric(20,1),p_occurred_at timestamptz,p_on_behalf_of_participant_id uuid) returns table(transfer_id uuid,amount numeric(20,1),currency character(3),financial_version bigint) language plpgsql volatile security definer set search_path='' as $function$
declare aid uuid:=p_activity_id; fr uuid:=p_from_participant_id; too uuid:=p_to_participant_id; amt numeric:=p_amount; at_time timestamptz:=p_occurred_at; behalf uuid:=p_on_behalf_of_participant_id; debt numeric; tid uuid; cur character(3); ar timestamptz; cnt integer; ver bigint; u uuid:=(select auth.uid()); begin if amt is null or amt<=0 or fr is null or too is null or fr=too or at_time is null then raise exception using errcode='22023',message='invalid settlement transfer'; end if; perform private.lock_debt_projection_activity(aid); select base_currency,archived_at into cur,ar from public.activities where id=aid and not is_deleted for update; if not found then raise exception using errcode='P0002',message='activity was not found'; end if; if ar is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if; perform 1 from public.participants where activity_id=aid and id in(fr,too) and not is_deleted order by id for update; get diagnostics cnt=row_count; if cnt<>2 then raise exception using errcode='P0002',message='transfer participant was not found'; end if; perform private.authorize_phase5_actor(aid,fr,too,behalf); select bd.amount into debt from public.bilateral_debts bd where bd.activity_id=aid and bd.debtor_participant_id=fr and bd.creditor_participant_id=too; if debt is null or amt>debt then raise exception using errcode='23514',message='settlement exceeds current bilateral debt'; end if; insert into public.transfers(activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,recorded_by,on_behalf_of_participant_id) values(aid,fr,too,'settlement',amt,cur,at_time,u,behalf) returning id into tid; insert into public.transfer_components(activity_id,transfer_id,component_type,amount) values(aid,tid,'settlement',amt); perform private.assert_component_total(tid); perform private.phase5_rebuild_after_transfer(aid); update public.activities a set financial_version=a.financial_version+1 where a.id=aid returning a.financial_version into ver; return query select tid,amt,cur,ver; end;$function$;

create or replace function private.create_prepayment_impl(aid uuid,owner uuid,cust uuid,amt numeric(20,1),at_time timestamptz,behalf uuid) returns table(transfer_id uuid,settlement_amount numeric(20,1),prepayment_amount numeric(20,1),currency character(3),financial_version bigint) language plpgsql volatile security definer set search_path='' as $function$
#variable_conflict use_column
declare debt numeric:=0; st numeric; pp numeric; tid uuid; cur character(3); ar timestamptz; cnt integer; ver bigint; u uuid:=(select auth.uid()); begin if amt is null or amt<=0 or owner is null or cust is null or owner=cust or at_time is null then raise exception using errcode='22023',message='invalid prepayment'; end if; perform private.lock_debt_projection_activity(aid); select base_currency,archived_at into cur,ar from public.activities where id=aid and not is_deleted for update; if not found then raise exception using errcode='P0002',message='activity was not found'; end if; if ar is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if; perform 1 from public.participants where activity_id=aid and id in(owner,cust) and not is_deleted order by id for update; get diagnostics cnt=row_count; if cnt<>2 then raise exception using errcode='P0002',message='transfer participant was not found'; end if; perform private.authorize_phase5_actor(aid,owner,cust,behalf); select coalesce(amount,0) into debt from public.bilateral_debts where activity_id=aid and debtor_participant_id=owner and creditor_participant_id=cust; st:=least(amt,coalesce(debt,0)); pp:=amt-st; insert into public.transfers(activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,recorded_by,on_behalf_of_participant_id) values(aid,owner,cust,'prepayment',amt,cur,at_time,u,behalf) returning id into tid; if st>0 then insert into public.transfer_components(activity_id,transfer_id,component_type,amount) values(aid,tid,'settlement',st); end if; if pp>0 then insert into public.transfer_components(activity_id,transfer_id,component_type,amount) values(aid,tid,'prepayment',pp); end if; perform private.assert_component_total(tid); perform private.phase5_rebuild_after_transfer(aid); update public.activities set financial_version=financial_version+1 where id=aid returning financial_version into ver; return query select tid,st,pp,cur,ver; end;$function$;

create or replace function private.create_prepayment_return_impl(aid uuid,owner uuid,cust uuid,amt numeric(20,1),at_time timestamptz,behalf uuid) returns table(transfer_id uuid,amount numeric(20,1),currency character(3),financial_version bigint) language plpgsql volatile security definer set search_path='' as $function$
#variable_conflict use_column
declare bal numeric; tid uuid; cur character(3); ar timestamptz; cnt integer; ver bigint; u uuid:=(select auth.uid()); begin if amt is null or amt<=0 or owner is null or cust is null or owner=cust or at_time is null then raise exception using errcode='22023',message='invalid prepayment return'; end if; perform private.lock_debt_projection_activity(aid); select base_currency,archived_at into cur,ar from public.activities where id=aid and not is_deleted for update; if not found then raise exception using errcode='P0002',message='activity was not found'; end if; if ar is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if; perform 1 from public.participants where activity_id=aid and id in(owner,cust) and not is_deleted order by id for update; get diagnostics cnt=row_count; if cnt<>2 then raise exception using errcode='P0002',message='transfer participant was not found'; end if; perform private.authorize_phase5_actor(aid,cust,owner,behalf); select balance into bal from public.prepayment_accounts where activity_id=aid and owner_participant_id=owner and custodian_participant_id=cust; if bal is null or amt>bal then raise exception using errcode='23514',message='prepayment return exceeds available balance'; end if; insert into public.transfers(activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,recorded_by,on_behalf_of_participant_id) values(aid,cust,owner,'prepayment_return',amt,cur,at_time,u,behalf) returning id into tid; insert into public.transfer_components(activity_id,transfer_id,component_type,amount) values(aid,tid,'prepayment_return',amt); perform private.assert_component_total(tid); perform private.phase5_rebuild_after_transfer(aid); update public.activities set financial_version=financial_version+1 where id=aid returning financial_version into ver; return query select tid,amt,cur,ver; end;$function$;

create or replace function private.void_prepayment_transfer_impl(tid uuid,reason text) returns table(transfer_id uuid,voided boolean,financial_version bigint) language plpgsql volatile security definer set search_path='' as $function$
#variable_conflict use_column
declare aid uuid; rec uuid; v boolean; cr boolean; ar timestamptz; ver bigint; u uuid:=(select auth.uid()); begin if u is null then raise exception using errcode='28000',message='authentication is required'; end if; if reason is null or length(btrim(reason))=0 then raise exception using errcode='22023',message='void reason is required'; end if; select activity_id into aid from public.transfers where id=tid; if not found then raise exception using errcode='P0002',message='transfer was not found'; end if; perform private.lock_debt_projection_activity(aid); select t.recorded_by,t.is_voided,a.created_by=u,a.archived_at into rec,v,cr,ar from public.transfers t join public.activities a on a.id=t.activity_id where t.id=tid and t.type in('settlement','prepayment','prepayment_return') and not a.is_deleted for update of t,a; if not found then raise exception using errcode='P0002',message='financial transfer was not found'; end if; if ar is not null then raise exception using errcode='55000',message='archived activity is read-only'; end if; if not exists(select 1 from public.activity_members where activity_id=aid and user_id=u) then raise exception using errcode='42501',message='caller is not an activity member'; end if; if v then raise exception using errcode='55000',message='transfer is already voided'; end if; if not cr and rec<>u then raise exception using errcode='42501',message='member may void only a transfer they recorded'; end if; update public.transfers set is_voided=true,voided_at=pg_catalog.now(),voided_by=u,void_reason=btrim(reason) where id=tid; perform private.phase5_rebuild_after_transfer(aid); update public.activities set financial_version=financial_version+1 where id=aid returning financial_version into ver; return query select tid,true,ver; end;$function$;

-- Preserve the Phase 4 public endpoint while routing it through the same full
-- Phase 5 rebuild (allocations, usages, accounts, then bilateral debt).
create or replace function private.void_settlement_transfer_impl(p_transfer_id uuid,p_void_reason text)
returns table(transfer_id uuid,voided boolean,financial_version bigint)
language sql volatile security definer set search_path='' as $function$
 select * from private.void_prepayment_transfer_impl($1,$2);
$function$;

create or replace function public.create_prepayment(activity_id uuid,owner_participant_id uuid,custodian_participant_id uuid,amount numeric(20,1),occurred_at timestamptz default pg_catalog.now(),on_behalf_of_participant_id uuid default null) returns table(transfer_id uuid,settlement_amount numeric(20,1),prepayment_amount numeric(20,1),currency character(3),financial_version bigint) language sql volatile security invoker set search_path='' as $function$ select * from private.create_prepayment_impl($1,$2,$3,$4,$5,$6); $function$;
create or replace function public.create_prepayment_return(activity_id uuid,owner_participant_id uuid,custodian_participant_id uuid,amount numeric(20,1),occurred_at timestamptz default pg_catalog.now(),on_behalf_of_participant_id uuid default null) returns table(transfer_id uuid,amount numeric(20,1),currency character(3),financial_version bigint) language sql volatile security invoker set search_path='' as $function$ select * from private.create_prepayment_return_impl($1,$2,$3,$4,$5,$6); $function$;
create or replace function public.void_prepayment_transfer(transfer_id uuid,void_reason text) returns table(transfer_id uuid,voided boolean,financial_version bigint) language sql volatile security invoker set search_path='' as $function$ select * from private.void_prepayment_transfer_impl($1,$2); $function$;

revoke all on function private.assert_component_total(uuid),private.rebuild_prepayment_projections_locked(uuid),private.authorize_phase5_actor(uuid,uuid,uuid,uuid),private.phase5_rebuild_after_transfer(uuid),private.create_prepayment_impl(uuid,uuid,uuid,numeric,timestamptz,uuid),private.create_prepayment_return_impl(uuid,uuid,uuid,numeric,timestamptz,uuid),private.void_prepayment_transfer_impl(uuid,text) from public,anon,authenticated;
grant execute on function private.create_prepayment_impl(uuid,uuid,uuid,numeric,timestamptz,uuid),private.create_prepayment_return_impl(uuid,uuid,uuid,numeric,timestamptz,uuid),private.void_prepayment_transfer_impl(uuid,text) to authenticated;
revoke all on function public.create_prepayment(uuid,uuid,uuid,numeric,timestamptz,uuid),public.create_prepayment_return(uuid,uuid,uuid,numeric,timestamptz,uuid),public.void_prepayment_transfer(uuid,text) from public,anon,authenticated;
grant execute on function public.create_prepayment(uuid,uuid,uuid,numeric,timestamptz,uuid),public.create_prepayment_return(uuid,uuid,uuid,numeric,timestamptz,uuid),public.void_prepayment_transfer(uuid,text) to authenticated;
revoke all on function private.rebuild_activity_debt_projection(uuid) from public,anon,authenticated; grant execute on function private.rebuild_activity_debt_projection(uuid) to service_role;
commit;
