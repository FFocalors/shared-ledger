begin;

-- Foreign-key covering indexes for Phase 5 projection joins. Keep the
-- activity-first indexes used by rebuilds and member-scoped reads; these
-- transfer/account-first companions support FK checks and fact lookups.
create index if not exists prepayment_usages_account_activity_idx
  on public.prepayment_usages (account_id, activity_id);

create index if not exists transfer_allocations_component_activity_transfer_idx
  on public.transfer_allocations (settlement_component_id, activity_id, transfer_id);

create index if not exists transfer_components_transfer_activity_idx
  on public.transfer_components (transfer_id, activity_id);

commit;
