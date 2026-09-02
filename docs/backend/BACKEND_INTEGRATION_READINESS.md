# Backend Integration Readiness

Phase 7 freezes the database contract used by the Android client. Public
functions are `SECURITY INVOKER` wrappers with `search_path = ''`; their
authenticated callers invoke private `SECURITY DEFINER` implementations with
the same empty search path. The private schema is not exposed by the Data API.

## Public write contract

- Activity: `create_activity`, `join_activity_by_code`,
  `create_sub_activity`, `archive_activity`, `unarchive_activity`,
  `delete_activity`, `remove_activity_member`, `transfer_activity_creator`,
  and `update_activity_settings(activity_id, name, base_currency,
  multi_currency_enabled)`.
- Participants: `create_participant`, `delete_participant`,
  `claim_participant`, and `unclaim_participant`.
- Expense: `create_expense`, `update_expense`, `delete_expense`, and
  `restore_expense`.
- Settlement and prepayment: the existing Phase 4–5 create/void RPCs,
  including `void_prepayment_transfer`.
- Final settlement: `preview_final_settlement`,
  `preview_activity_settlement`, `create_final_settlement`, and
  `execute_final_settlement_item`.
- Collaboration: `add_transfer_dispute(transfer_id, participant_id, note)` and
  `remove_transfer_dispute(dispute_id)`.
- Attachments: `create_attachment`, `complete_attachment`, and
  `delete_attachment`; bytes are uploaded with the Storage API.

All financial writes reject anonymous callers and archived/deleted Activities.
Clients have no direct DML grants on financial facts or projection tables.
`financial_version` changes only for successful financial fact changes; dispute,
audit, attachment metadata, participant claims, and administrative operations
do not change it.

## Read contract

Authenticated Activity members may read the existing fact/projection tables and
financial-status views, plus `transfer_disputes`, `audit_logs`, and `attachments`.
`get_exchange_rate(p_base_currency, p_quote_currency)` reads the latest cache row.
The exchange-rate cache is reference data only and never rewrites an Expense's
stored FX snapshot.

## Realtime and Storage

The collaboration and financial tables are members of `supabase_realtime`; the
client must re-query projections/status after a change notification.  RLS still
controls row visibility.

`activity-attachments` is a private bucket. Object paths are
`<activity>/<ledger-unit>/<attachment>.<extension>`, upload requires a pending
metadata row and active membership, reads are Activity-member scoped, and
deletion requires the uploader or Creator while the Activity is writable.
Each Expense has at most ten active/pending image metadata rows; standalone
LedgerUnit attachments (`expense_id is null`) have the same per-unit limit.

## Contract-freeze checklist

- [x] Public RPCs are authenticated-only; anonymous callers receive `28000` or
  `42501` and no financial write is performed.
- [x] Public wrappers are `SECURITY INVOKER`, private implementations are
  `SECURITY DEFINER`, and both use `search_path=''`; private schema is not in
  the Data API.
- [x] Financial facts/projections have no authenticated direct DML grants.
- [x] Financial mutations lock the Activity, rebuild projections atomically,
  and increment `financial_version` once only for real fact changes.
- [x] Archived/deleted Activities reject all financial, participant, dispute,
  member-management, and attachment writes.
- [x] `completed` is computed from zero ordinary debt and zero prepayment
  balance and can return to active after a later financial write.

## Public RPC signatures and return summaries

These are the current PostgreSQL identities. Expense clients send original
currency inputs only; `base_amount` is server-computed.

```text
create_activity(name text, type activity_type, base_currency char(3), multi_currency_enabled boolean)
  -> activity_id, join_code, activity_name, activity_type, activity_base_currency, activity_multi_currency_enabled
join_activity_by_code(join_code text) -> activity_id, is_new
create_sub_activity(activity_id uuid, name text) -> parent_activity_id, ledger_unit_id, created_name, created_type
update_activity_settings(activity_id uuid, name text, base_currency char(3), multi_currency_enabled boolean)
  -> activity_id, activity_name, activity_base_currency, activity_multi_currency_enabled
archive_activity(p_activity_id uuid), unarchive_activity(p_activity_id uuid)
  -> activity_id, archived, changed, archived_at, total_debt, total_prepayment, completed, has_unsettled, warning
delete_activity(activity_id uuid) -> boolean
remove_activity_member(activity_id uuid, user_id uuid) -> boolean
transfer_activity_creator(activity_id uuid, new_creator_user_id uuid) -> uuid
create_participant(activity_id uuid, name text, participant_order integer)
  -> participant_id, participant_name, participant_order
delete_participant(participant_id uuid) -> participant_id, deleted
claim_participant(activity_id uuid, participant_id uuid)
  -> claim_id, claimed_participant_id, is_new
unclaim_participant(activity_id uuid) -> boolean
create_expense(ledger_unit_id uuid, title text, original_amount numeric, original_currency char(3), fx_rate numeric, split_method expense_split_method, payments jsonb, manual_splits jsonb, aa_participant_ids uuid[], occurred_at timestamptz, note text, original_expense_id uuid)
  -> expense_id, base_amount, version
update_expense(expense_id uuid, ledger_unit_id uuid, title text, original_amount numeric, original_currency char(3), fx_rate numeric, split_method expense_split_method, payments jsonb, manual_splits jsonb, aa_participant_ids uuid[], occurred_at timestamptz, note text, original_expense_id uuid)
  -> updated_expense_id, base_amount, version
delete_expense(expense_id uuid) -> deleted_expense_id, deleted, version
restore_expense(expense_id uuid) -> restored_expense_id, restored, version
create_settlement_transfer(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, occurred_at timestamptz, on_behalf_of_participant_id uuid)
  -> transfer_id, amount, currency, financial_version
void_settlement_transfer(transfer_id uuid, void_reason text) -> transfer_id, voided, financial_version
create_prepayment(activity_id uuid, owner_participant_id uuid, custodian_participant_id uuid, amount numeric, occurred_at timestamptz, on_behalf_of_participant_id uuid)
  -> transfer_id, settlement_amount, prepayment_amount, currency, financial_version
create_prepayment_return(activity_id uuid, owner_participant_id uuid, custodian_participant_id uuid, amount numeric, occurred_at timestamptz, on_behalf_of_participant_id uuid)
  -> transfer_id, amount, currency, financial_version
void_prepayment_transfer(transfer_id uuid, void_reason text)
  -> transfer_id, voided, financial_version
preview_final_settlement(activity_id uuid), preview_activity_settlement(activity_id uuid)
  -> activity_id, from_participant_id, to_participant_id, amount, ordinary_amount, prepayment_return_amount, currency, source_financial_version, is_prepayment_return
create_final_settlement(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, occurred_at timestamptz, on_behalf_of_participant_id uuid)
  -> transfer_id, amount, currency, financial_version
execute_final_settlement_item(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, occurred_at timestamptz, on_behalf_of_participant_id uuid)
  -> transfer_id, amount, currency, financial_version
add_transfer_dispute(transfer_id uuid, participant_id uuid, note text) -> dispute_id, created
remove_transfer_dispute(dispute_id uuid) -> boolean
create_attachment(activity_id uuid, ledger_unit_id uuid, expense_id uuid, filename text, mime_type text, size_bytes bigint) -> attachment_id, bucket, path, status
complete_attachment(attachment_id uuid) -> boolean
delete_attachment(attachment_id uuid) -> boolean
get_exchange_rate(p_base_currency char(3), p_quote_currency char(3))
  -> base_currency, quote_currency, rate, observed_at, source
```

## Read, error, and Realtime contract

Members have RLS-protected SELECT on all public fact/projection tables plus
`transfer_disputes`, `audit_logs`, `attachments`, and `exchange_rate_cache`.
The computed views are `participant_financial_status` and
`activity_financial_status`. Common SQLSTATEs are `28000` authentication,
`42501` permission/membership/archive boundary, `P0002` not found, `22023`
invalid input, `23505` uniqueness/claim conflict, `23503` FK conflict,
`23514` business rule, `55000` lifecycle/settings lock, `54000` attachment
limit, and `40001` serialization retry.

`supabase_realtime` contains exactly these 16 tables: `activities`,
`activity_members`, `ledger_units`, `participants`, `participant_claims`,
`expenses`, `transfers`, `expense_debts`, `bilateral_debts`,
`transfer_allocations`, `transfer_components`, `prepayment_accounts`,
`prepayment_usages`, `final_settlement_paths`, `attachments`, and
`transfer_disputes`. Notifications are refresh hints; RLS still controls
reads and Android must re-query status/projections.

## Storage checklist

1. Call `create_attachment` for pending metadata and an Activity-isolated path.
2. Upload bytes through the Storage API to private bucket
   `activity-attachments`; direct SQL storage DML is blocked.
3. Call `complete_attachment` after the object exists.
4. JPEG/PNG/WebP, max 10 MiB. Each Expense allows ten active/pending images;
   standalone LedgerUnit attachments (`expense_id is null`) have a separate
   ten-row limit enforced under the Activity lock.
5. Members read Activity-scoped objects; uploader or Creator deletes while
   writable. Anonymous/outsider/archived/deleted/missing-metadata and
   cross-Activity paths are rejected by policies/FKs.

## Deferred scope and freeze decision

Deferred: Dispute approval/freeze/arbitration, event-sourced audit history,
non-image attachments, third-party FX fetch jobs, custom event bus, and
Android SDK/repository/UI integration. Final Settlement remains the existing
large-Activity deterministic recommendation and does not alter daily debt.

**Backend Contract Freeze: READY.** Phase 1–7 migrations, public RPC
signatures, RLS/permissions, computed views, Realtime publication, and image
Storage protocol are frozen for Android integration. Future changes require a
new migration and explicit contract revision.
