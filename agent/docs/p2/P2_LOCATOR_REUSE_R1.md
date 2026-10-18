# P2 v3 locator reuse R1 — limited CPU slice

## Behavior implemented

`P2V3RequestReferenceRegistry.bind_entity` now reuses an existing opaque entity reference only when the persisted locator is unique for the exact `(owner_user_id, turn_id, entity_kind, private_entity_id, private_activity_id, private_ledger_unit_id)` identity and matches the Turn's currently verified immutable execution cohort. The lookup rejects ambiguous locators, cohort drift, a token already bound to another identity, and a generated-token collision anywhere in the local Store. SQLite `NULL` child identity is compared as a value, so an Activity-level entity cannot be confused with a child-scoped entity.

The admission transaction obtains the cohort from the current Store pin before it creates prospective refs. Reused refs preserve scope and entity identity across a new admission. `principal_ref` and `owner_turn_ref` remain newly minted per admission; this work does not provide Auth continuation or restore an old registry.

Metadata acceptance still independently re-parses the six captured source tables and rechecks the current claim, membership, Activity, child, participant, and source-row relationships. For a reused entity locator, the Store keeps the existing immutable locator row and its original `created_from_receipt_id`; it inserts new metadata proofs against receipts from the current admission. The old locator does not activate an old source receipt, label, membership check, or proof. A removed participant is omitted from the new projection even though its historical locator remains. A fresh admission for a child absent from the new source response fails without publishing metadata.

## CPU evidence

The final focused run used the Agent checkout and its existing `.venv` Python, with all test state, `TEMP`, `TMP`, and Python cache under the D-drive run directory. It included metadata acceptance, locator reuse, and the shared Store budget-port regression module. The raw command, UTC start/end, exit status, process-only environment, stdout/stderr, and before/after hashes are in `D:\AI\runs\shared-ledger\p2\locator-reuse-final-20261016T001402Z-caf32b4a\command.json`.

Command: `python.exe -B -m pytest -q -p no:cacheprovider --basetemp=<D-run> agent/tests/test_p2_v3_admission_metadata_acceptance.py agent/tests/test_p2_v3_locator_reuse.py agent/tests/test_p2_v3_store_budget_port.py`.

Result: **26 passed in 26.17s; exit 0.** The added cases cover a second admission reusing Activity/child refs while producing new receipts/proofs and refreshed labels; removed participant projection; membership revocation and missing-child refusal; forced private-UUID, cross-owner, and cross-Turn token collisions; cohort mismatch; and duplicate persisted locators. The old locator/proof rows remain unchanged in the successful second-admission case. The pre-expansion two-module run remains as historical evidence: `locator-reuse-r1d-20261016T001114Z-b80cd99a` (11 passed). The final run is separately captured and hashed; it does not overwrite that earlier run.

Earlier failed runs are retained as history, not represented as passing evidence: `locator-reuse-r1-20261016T000816Z-785c1325` (3 test assertion/fixture mistakes), `locator-reuse-r1b-20261016T000923Z-c0248c5c` (1 stale Turn-wide proof-count assertion), and `locator-reuse-r1c-20261016T001025Z-2f5b921f` (1 test helper could not claim another queued Turn). None of those earlier failures was rewritten or deleted.

## Limits

This is a synthetic SQLite/fake-transport identity-continuity test only. It does not prove real Supabase Auth, RLS, or current visibility; Runtime/API integration; query/continuation recovery; a fresh authorization lifecycle; or a production execution cohort. A locator remains a private identity mapping and is not permission. Query source reads must still reauthorize and re-prove current membership/scope and financial freshness. P2 remains unassembled and disabled. No SQL migration or frozen schema was changed.
