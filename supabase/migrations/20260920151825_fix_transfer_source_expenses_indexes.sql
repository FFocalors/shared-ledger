-- Keep the constraint-backed identity key as the sole uniqueness index.
drop index if exists public.transfer_source_expenses_identity_idx;

-- Support FK lookups and source-history lock checks by activity.
create index if not exists transfer_source_expenses_activity_idx
  on public.transfer_source_expenses (activity_id);
