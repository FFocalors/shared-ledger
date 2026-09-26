# Database test status

Latest full deterministic run: clean-reset isolated local Supabase, **43 migrations**, **30 standalone test files / 223 pgTAP assertions passing**; all six concurrency test files passed. This includes `mass500_micro_aa_debt_allocation.sql`, which covers the MASS500-001 regression. The run is recorded in [MASS500_001_FIX.md](../../../verification/findings/MASS500_001_FIX.md). MASS2000 also verified a fresh 43/43 migration reset before its scan; it did not rerun the full pgTAP or Android suites. The C02 reverse-refund fixture explicitly timestamps the -60 refund one second before the -40 refund, so TARGETED allocation remains stable across generated UUIDs.

| Test file | Status | Traceable note |
| --- | --- | --- |
| `aa_original_currency_debt_contract.sql` | PASS | 28 assertions covering 100/3 AA, multi-payer AA, multiple creditors, foreign and negative AA, and zero-base micro foreign debt; original Payment/Split/net/Debt conservation remains independent of base rounding. |
| `critical_financial_concurrency.sql` | PASS | Idempotent requests, version races, refund cap, prepayment and final-settlement races. |
| `critical_financial_ordering.sql` | PASS | C02/C03 ordering, linked refunds, multi-currency views, and settlement rebuild behavior. The C02 -60/-40 refunds have explicit occurred-at ordering so both requested refund Expenses remain eligible deterministically. |
| `exchange_rate_expense_snapshots.sql` | PASS | FX snapshot behavior against a deterministic cache fixture. |
| `fix_original_currency_debt_projection.sql` | PASS | Original-currency repayment allocation and projection rebuild. |
| `idempotency_request_replay_contract.sql` | PASS | Exact retry result, payload/actor/operation binding, archived retry, and no duplicate transfer. |
| `linked_refund_contract.sql` | PASS | Refund linkage, cumulative cap, permanent source lock, and FX snapshot inheritance. |
| `mass500_micro_aa_debt_allocation.sql` | PASS | MASS500-001 regression: tiny multi-participant AA debt base allocations remain nonnegative and conserve the base total. |
| `phase10_sub_activity_delete_restore.sql` | PASS | Delete/restore lifecycle and immutable settlement-history rejection. |
| `phase11_multi_currency_settlement.sql` | PASS | Multi-currency settlement behavior. |
| `phase12_multi_currency_allocation_invariants.sql` | PASS | Allocation invariants across currencies and zero-base rows. |
| `phase2c_base_amount_normalization.sql` | PASS | Base-amount normalization boundaries. |
| `phase3_debt_projection_concurrency.sql` | PASS | Concurrent debt-projection mutations. |
| `phase3_debt_projection.sql` | PASS | Debt projection and rebuild invariants. |
| `phase3_deleted_expense_read_restore.sql` | PASS | Deleted-expense projection behavior. |
| `phase4_settlement_transfer_concurrency.sql` | PASS | Concurrent settlement creation and projection locking. |
| `phase4_settlement_transfer.sql` | PASS | Settlement allocation, immutable source facts, and editable unsettled expenses. |
| `phase5_prepayment_concurrency.sql` | PASS | Concurrent prepayment and return limits. |
| `phase5_prepayment_extended.sql` | PASS | Usage release, return/void limits, permanent source behavior, and exact rebuild preservation. |
| `phase5_prepayment.sql` | PASS | Prepayment components, Usage, refunds, and account balance projections. |
| `phase6_final_settlement_concurrency.sql` | PASS | Concurrent final-settlement execution. |
| `phase6_final_settlement.sql` | PASS | Final preview, multi-hop debts, return paths, and projection totals. |
| `phase7_finalization_concurrency.sql` | PASS | Finalization and attachment concurrency limits. |
| `phase7_finalization.sql` | PASS | Finalization lifecycle and attachment behavior. |
| `phase9_fair_aa_final_settlement.sql` | PASS | Fair-AA final-settlement allocation. |
| `rpc_client_contract.sql` | PASS | Authenticated v2 contract and legacy-write RPC privilege checks. |
| `targeted_expense_repayment_multicurrency.sql` | PASS | Targeted repayment and allocation across currencies. |
| `targeted_expense_repayment.sql` | PASS | Targeted allocations remain attached to selected Expenses after rebuild. |
| `transfer_restore_contract.sql` | PASS | Historical transfer-restore APIs are unavailable to client and server roles. |
| `u03_historical_foreign_currency.sql` | PASS | Existing USD FIFO/targeted repayment, return, final paths, refund, and void remain valid after disabling new foreign-currency facts; new Expense/Prepayment writes are rejected. |
| `phase8_transfer_restore.sql` | RETIRED | Historical positive-restore behavior conflicts with immutable Transfer facts; current revocation contract is covered by `transfer_restore_contract.sql`. The runner rejects explicit selection of this file. |

`legacy_rpc_fixture_adapters.sql` is a transaction-local fixture helper included with `\ir`; it is not a standalone test and is excluded from the run. Business-flow fixtures use the v2 prepayment RPC so they exercise durable settlement allocations. Client privileges and production RPC behavior are checked independently in `rpc_client_contract.sql`.

`phase8_transfer_restore.sql` remains **RETIRED** and is excluded from the 29 active test files; its replacement contract remains `transfer_restore_contract.sql`.

On this Windows host, Supabase CLI 2.116 cannot bind-mount the test directory and reports a malformed `/` path. The runner detects that mount failure and executes the same SQL files with the cached `pg_prove` image on the isolated database network; the final database test result above is from that successful run. Concurrency fixtures that commit through `dblink` persist outside their caller transaction, so run the complete suite on a clean/reset isolated database.
