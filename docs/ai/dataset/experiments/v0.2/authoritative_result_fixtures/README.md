# v0.2 Authoritative Tool Result Fixtures

Status: **AUTHORITATIVE_RESULT_FIXTURES_BLOCKED**. This is an independent v0.2 fixture package. Frozen v0.1 samples, Scenarios, Ground Truth, Surface Forms and splits, the AI Contract, and training settings are unchanged.

## Rebuildability result

Of the 108 result-dependent Samples identified by Experiment B, **39 are reconstructable** and **69 remain blocked**. The 39 covered Samples use 7 unique `lookup_business_rule` results across 7 Scenarios; surface variants share their Scenario result. Each fixture reads an exact paragraph from the frozen authoritative policy documents, records its source hash and line pointer, and captures `observed_at` at that real document-read event. These timestamps describe new v0.2 document reads; they are not timestamps for old Backend or Gateway observations. `financial_version=null` follows the Tool Catalog and Contract for non-financial rule lookups. The content is extracted directly from `docs/backend/BUSINESS_LOGIC.md` or `docs/ai/AI_MODEL_CONTRACT.md`; each fixture records the source heading, line range, and selection marker.

The `scenario_gs_p0b_037` refund-history result remains blocked. Frozen BUSINESS_LOGIC §13 establishes the cumulative refund cap but not that this Scenario's current cumulative amount is 100; the user only supplies the original Expense amount. A rule passage cannot stand in for that missing live financial state.

The other 63 Samples depend on database-query results with incomplete Scenario payloads and no captured Scenario-specific receipt. The AI Gateway is explicitly not implemented. RPC/query source code alone cannot recreate the prior result: missing DTO/state must not be filled from Expected GT. `sample_rebuildability.json` records each of the 108 Samples, Expected fact claim, authoritative source pointer/hash, model-visible result content where materialized, and exact blocker otherwise.

## Formal Tool schemas

Success receipts require `status=success`, `result_id`, RFC3339 `observed_at`, `financial_version` (decimal string or null), and closed `data`. Error receipts require `status=error`, `result_id`, and the catalog `$defs.error` object. The full closed schemas, including every nested DTO requirement, come from the Tool Catalog and are preserved in `tool_receipt_schema_inventory.json`.

| Tool | Required payload fields | Backend mapping |
|---|---|---|
| `find_expenses` | items, next_cursor, truncated | `existing_query_composition` |
| `find_participants` | items, next_cursor, truncated | `existing_query_composition` |
| `get_debt` | bilateral_debts, expense_progress | `existing_query_composition` |
| `get_expense` | expense, repayment_progress | `existing_query_composition` |
| `get_final_settlement` | mode, suggestions, source_financial_version | `existing_rpc` |
| `get_participant_balance` | participant_id, base_currency, base_reference, balance_by_currency | `existing_query_composition` |
| `get_prepayment_accounts` | accounts, usages | `existing_query_composition` |
| `get_transfer` | id, activity_id, type, from_participant_id, to_participant_id, payment, occurred_at, recorded_by, on_behalf_of_participant_id, is_voided, void_reason, components, disputes, source_allocations | `existing_query_composition` |
| `lookup_business_rule` | baseline_commit, passages | `frozen_document_adapter` |

Authority paths include `get_expense_repayment_progress` in `supabase/migrations/20260921051720_targeted_expense_repayment_contract.sql:952`, `preview_final_settlement_v2` in `supabase/migrations/20260920142845_multi_currency_prepayment_final_settlement_core.sql:625`, plus query/RPC mappings declared per Tool in `docs/ai/schema/tool_catalog.json`. Business rules come from `docs/backend/BUSINESS_LOGIC.md`. Its SHA-256 matches the bytes at baseline commit `55fb28a7c0660462e5842e2eb5c71cfa763e5801`; the Tool Catalog and AI Contract cite the same baseline.

## Result ID binding

The validator requires every materialized `result_id` to have one global Scenario/Tool binding and pass that Tool's complete nested schema. The 7 lookup fixtures preserve their globally unique legacy IDs, so existing references still match. The old `result-trf-002-verified` is reused for `scenario_gs_p0b_010/get_debt` and `scenario_gs_p0b_014/get_final_settlement`; the registry reserves distinct pair-scoped IDs for those bindings and forbids resolving the old alias without an explicit Scenario/Tool key. Neither result is materialized and no Frozen v0.1 reference or Ground Truth changed. The later B overlay must keep the scoped mapping explicit.

The previous Experiment B audit counted `scenario_gs_p0b_014/get_final_settlement` as the single contract-valid result pair. Full nested validation against the current Catalog DTO found `suggestions[0]` lacks required `payment`, `ordinary_amount`, `prepayment_return_amount`, `is_prepayment_return`, `path_currency`, and `source_financial_version`, while supplying disallowed `amount` and `currency`. It is excluded as a fixture; the frozen source remains unchanged.

## Validation and remaining gate

- Materialized fixtures: **7**; full nested success/error schemas checked; schema errors 0.
- Fixture Result ID binding errors: **0**; alias mapping errors: **0**; legacy cross-Scenario/Tool collision pairs: **1**, explicitly scoped but still blocked.
- Sample coverage: **39/108**; remaining blockers: **69**.
- Focused binding tests: **4 passed**.
- Frozen canonical Dataset Validator: **valid**, 0 errors and 155 existing `SEMANTIC_GROUP_REVIEW` warnings; full output is in `canonical_dataset_validator.json`.
- Local Supabase CLI is available, but the AI Gateway is unimplemented and no Scenario-specific database seed/query receipts exist. Its SQL test harness operates on mutable test database state and was not used to synthesize result facts. No linked/remote database was accessed.

Experiment B is **not ready to rerun** while 69 Samples lack complete authoritative results and the duplicate legacy ID pair needs explicit reference compatibility in the overlay. No training or Experiment C work was performed.
