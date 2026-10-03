# v0.2 Authoritative Backend Receipt Harness

Status: **AUTHORITATIVE_BACKEND_RECEIPTS_PARTIALLY_BLOCKED**. This harness and its outputs are a separate v0.2 package. Frozen v0.1 data, prior result fixtures, Expected GT, AI Contract, Catalog, migrations, and training settings were not edited.

## Local execution and isolation

The harness refuses to run unless Docker identifies the `supabase_db_shared-ledger` container as belonging to this repository and maps it to local port 54322. It runs each fixture's setup, projection rebuild/RPC, receipt capture, and explicit `ROLLBACK` in one SQL session. Each run records the actual post-rollback Activity row count, which must be zero. It does not use the linked Supabase project.

The local reference adapters read database rows and use the frozen Tool Catalog response shapes. `get_expense` calls the real `public.get_expense_repayment_progress(uuid,uuid)` RPC and records its unprojected rows separately from the receipt projection. `find_expenses` applies the Catalog query composition to local `expenses`, `ledger_units`, and `activities` and records both source rows and projected receipt. FX source `same_currency` is projected to the Contract's `base_currency` label only when the stored currency matches the Activity base currency.

The only target Scenario pairs with source-complete seed facts are `scenario_gs_p0a_009/get_expense` and `scenario_gs_p0a_012/find_expenses`. Their exact Scenario DTO/business rows seed the transaction; deterministic UUIDv5 IDs map original entity aliases to test rows. Synthetic user, join code, and technical insertion times are harness scaffolding. The receipt payload is returned by database queries/RPCs; no Expected GT value is used to build it.

## Coverage

There are **69** target Samples in 15 Scenarios. Two executed receipts cover **9 Samples** (5 + 4); **60 Samples remain blocked**. See `batch_coverage.json` for row-level disposition and each Scenario's minimum database preconditions. The missing fields include complete nested Expense DTO columns, complete Transfer lifecycle/components/allocations, participant/balance projections, debt progress history, and exact refund source events. An omitted field is not seeded as null or empty unless the Scenario explicitly records that fact.

Six refund-dependent Samples are still blocked. `scenario_gs_p0b_037` has an original amount claim but no original Expense identity or active linked refund event ledger (event IDs, amounts, currency, deletion state). `dynamic_refund_db_probe.sql` is marked **SYNTHETIC_TEST_ONLY**: it inserts controlled test events in a separate rollback-only transaction, confirms the real database computes a cumulative 100 and rejects an over-cap insert, and contributes zero Scenario coverage.

## Result IDs and artifacts

`result_id_registry.json` assigns deterministic, globally unique IDs to each materialized Scenario/Tool pair. The legacy `result-trf-002-verified` collision remains pair-scoped in the inherited registry and is not used for either new fixture. Cross-scope alias resolution without Scenario and Tool is rejected by the validator.

`backend_result_fixtures.json` contains complete receipts, raw RPC/query outputs, source-record hashes, UUID maps and rollback evidence. The pair-specific `.sql` files are the reproducible setup and query used for each fixture; `dynamic_refund_db_probe.sql` is the separate synthetic trigger test. `pilot_run.json` records source hashes for all Frozen v0.1 dataset files, the entire prior v0.2 result-fixture package, the AI Contract, Tool Catalog and all Supabase migrations. `authoritative_sources.json` lists those hashes, tool schema hashes and the local DB identity. `batch_coverage.json` gives the complete 69-row and per-Scenario inventory. `validator_report.json` is emitted by the validator.

Both Scenario-symbol-to-UUID and legacy-result-ID-to-new-result-ID mappings are external v0.2 sidecars. Frozen Expected GT and historical references remain unchanged. A future Experiment B overlay must resolve and validate these mappings while preserving Expected GT reference compatibility; it must not silently rewrite GT. This harness does not claim historical IDs are interchangeable with mapped database IDs.

Rebuild the two executable fixtures and database probe, then validate:

```powershell
python scripts/ai_training_setup/authoritative_backend_receipt_harness.py
python scripts/ai_training_setup/validate_authoritative_backend_receipts.py
python -m unittest scripts.ai_training_setup.test_authoritative_backend_receipts
```

Experiment B cannot be rerun while 60 Samples lack authoritative receipts. This package implements local reference projections for evidence generation; it does not claim an AI Gateway deployment exists.
