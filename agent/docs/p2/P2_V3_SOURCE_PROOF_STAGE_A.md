# P2 v3 Store 004 source-proof foundation

Status: disabled, CPU-only Store foundation. This note records the append-only 004 schema and its reservation-chain accounting. It does not add a source publisher or enable Runtime/API dispatch.

## Resume and reservation binding

The 003 logical query is an immutable description of the operation, normalized criteria, requested scope, and its creation-time audit metadata. An accepted Auth or clarification resume retains that same logical query and its already-consumed logical-read slot. The resume creates a fresh admission and a new page-zero query attempt. The attempt's admission supplies current owner/Turn, generation, input digest/sequence, claim epoch, authority epoch, and context revision for a GET reservation. The original query's generation/input fields remain historical descriptor fields; they are not treated as current authorization.

For a query-bound GET, the 004 trigger validates the reservation against the current query attempt and joins the current source admission through `query_attempts.admission_id`. For a pre-query metadata GET, the original 003 reservation remains admission-bound. A later attribution to the current query attempt is recorded only in the separate 004 capture-chain row; it does not rewrite the 003 charge event. A first admission may have no query or attempt and still incurs the physical GET charge.

The 003 `p2_v3_charge_events` row has no `input_seq` or `input_digest` columns. The 004 trigger therefore validates the fields that actually exist on that charge row, and validates current input identity against the referenced source admission. It does not refer to nonexistent charge-event columns.

## Source table roles and page accounting

Admission-bound metadata access is limited to these exact source table/role pairs: `activities` (`activity`, `financial_version`, `scope_label`), `activity_members` (`membership`), `participants` (`participant`, `scope_label`), `ledger_units` (`ledger_unit`, `scope_label`), `sub_activity_participants` (`ledger_unit`), and `participant_claims` (`actor`). Bootstrap admission GETs for financial tables are rejected before a reservation or capture-chain row is written. Once a query exists, source roles are checked against that query's operation allowlist.

`table_get_ordinal` is an audit ordinal for a source table within one capture chain. It is distinct from the model page index and from the HTTP `offset`/`Content-Range`. For example, a pre- and post-version fence can issue two requests to `activities`, each at offset zero; they receive distinct table GET ordinals. Stage A checks accounting and attribution, not the actual HTTP offset or response-range proof.

The reviewed limits remain 16 rows per source response, four GET reservations per source table per chain, 32 GET reservations per chain, and 48 GET dispatches per Turn. The schema also supports all 256 fact-card ordinals permitted by the v3 event contract (0–255). Limits derive from existing reservation/capture rows; this is not a second budget ledger.

The source-table ordinal is assigned transactionally from charged reservations: a pending GET occupies a slot, and a dispatched unknown GET remains charged. A `known_no_dispatch` terminal record with no `dispatch_started` releases its GET/table ordinal, while retaining its measured active cost and append-only audit sequence. A rejected reservation must leave neither charge nor capture-chain row. Two Store connections racing at chain count 31 are serialized by the existing SQLite write transaction; exactly one may create reservation 32, and reservation 33 leaves no orphan row.

## Validation and limits

The owned recovery-edge suite exercises all seven read-operation role paths, metadata admission attribution, query-bound reservations, bootstrap rejection of a financial source, per-table ordinal progression and the 4→5 rejection, known-no-dispatch ordinal reuse versus pending/unknown charging, a two-connection 31→32 race and atomic 33rd rejection, cross-owner/epoch/table/role rejection, the two-chain 47-settled-plus-48th-unknown recovery boundary, and the 256-card relational CHECK. The accepted Auth and clarification resume tests create the fresh admission and attempt, reuse the original query, and successfully reserve, dispatch, and settle a new query-bound GET without increasing the logical-read count; the former admission cannot reserve a GET after resume. The descriptor test covers strict typed `date` criteria, normalized reuse when opaque selected refs arrive in a different order, and rejection of changed criteria, scope, or selection. A Store operation test mutates the synthetic source component after verifier issuance and confirms the admission is rejected before an admission or charge is written.

The final isolated CPU run passed 43 tests across `test_p2_v3_store_recovery_edges.py` and `test_p2_v3_execution_cohort.py`; its immutable raw log and command record are linked from the D evidence manifest. Earlier failing runs remain preserved as history. No existing baseline test was modified to hide a schema-version assertion.

The capture table remains cost-only. These checks do not establish Supabase Auth, RLS, business membership or child-scope joins, strict raw-response parsing, accepted QueryEvidence, source truth, financial freshness, protected-output linkage, Runtime/API assembly, or production enablement. No live Supabase or model request was made.
