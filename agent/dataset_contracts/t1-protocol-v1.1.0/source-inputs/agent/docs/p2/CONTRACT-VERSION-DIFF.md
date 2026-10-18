# P2 deviations and gaps against frozen v1

Status as of 2026-10-11: canonical v1 contracts and export are unchanged. The safe A engineering subset passed CPU/fake verification. C completed 17 approved provider/Harness calls with status `FAIL_SEMANTIC_DIAGNOSTIC`; only transport compatibility is limited-pass. Thirteen responses were nonempty, four cap-64 responses were empty and unassessable. Pooled schema validity was 10/17 across caps; at default cap 768, responses were nonempty 9/9 and schema-valid 7/9. The clarification kind was correct 1/1, but exact required slots were correct 0/1. Among the six default-cap operation fixtures (three read and three proposal operations), exact selection was 0/3 for reads and 0/3 for proposals; grounded answers/citations were zero. No critical financial assertion about amount, currency, debt direction, settlement, participant, citation, or write success was observed among nonempty outputs, but an expense-context response contradicted supplied scope/read availability and other cases falsely refused work; this is not a safety pass. B (live Supabase scope/RLS) and D (live Supabase + model end-to-end) are `NOT_RUN_USER_DEFERRED`. CAP01–CAP17 pass count remains 0/17 and model quality is `INSUFFICIENT_SAMPLE`.

## Frozen inputs and independent P2 fingerprint

Current agent checkout frozen inputs:

- `contracts/v1.0.0/manifest.json`: `9d2d5938373681ab60ccdeb42a10190dd5b136615bce2026e29c94864a9dbca3`
- `contracts/v1.0.0/openapi.json`: `2ae0f297a72cc6ae39c69c92892325faf3718687cde2a061bf64f6ea5f4c021c`
- `contracts/v1.0.0/capability-registry.json`: `e444a702326923899704cdf1c8dc5ae13b05f140fe127ee1e855eb65a1fb03e8`
- `dataset_contracts/t1/protocol-fingerprint.json`: `089fc318d503cff7995ea8fead876c99b97351e334e270c3de17e3d1ee452f50`
- `evaluation/t1_teacher_probe/preregistration.json` (hash only): `745d636051726935fcc697d46783dbebf203ba623e73b05abcd8fb7e7359d8ba`
- `evaluation/t1_teacher_probe/preregistration.sha256` (hash only): `da30b646297ca77c67525f240fdd83320e5722c22e76b1517a49533374807d29`

T1's `app/contracts.py` source fingerprint is LF-normalized (`4da745eeb218cbd75cff2d30b62b0d895ceb8920c54f463cfa7dce35a1ef5130`); the initial raw-byte SHA in the agent checkout was `9fd214d9d8eb43c6f5b03b1d7e95b2bef274dbf9e8be495f536f495b48a5bf2d`. This is line-ending normalization, not a P2 contract change. `export_contracts --check` currently succeeds. The old T1 fingerprint and preregistration cover their original source set only; they are not the P2 source fingerprint or P2 evaluation. The final P2 source/test-only snapshot is `D:\AI\runs\shared-ledger\p2\final-delivery-20261011T0427Z-runtime\source-test-snapshot.json`; the original 04:04 CPU snapshot remains unchanged.

## 1. Health surfaces

The existing frozen canonical OpenAPI does not define `/health/provider` or `/health/ready`. Internal P2 provider health can represent `disabled`, `unavailable/not_tested`, and `ready` after a successful parsed provider inference. That per-instance signal does not imply semantic quality or deployed P2/Supabase readiness. The canonical provider health schema remains untouched. The live C probe had provider responses but no semantic pass; this report does not claim deployed P2 readiness.

## 2. Typed provenance and trusted expense supplements

Frozen v1 `ModelReadResult` already includes the complete typed `body.items`, result reference, operation, observation time, context version and simulation flag. P2 does not add a v1 `ModelContext` or semantic-decision field. The provider envelope is a P2-owned typed Pydantic model with bounded result provenance, labels and supplements. It contains only opaque model references and trusted scalar metadata; credentials, actual UUIDs, owner/Turn IDs and raw cursors stay server-side.

Internal provenance links each result to source, operation, observed time, context version, completeness, currentness, query/scope/source fingerprints and financial version. The labels are assembled from verified backend activity/participant/ledger DTOs, never from user/model strings. Payment and split rows are bound to the exact expense evidence, result and expense version. A mismatch, stale reference, unknown result, conflicting current version or unsupported amount shape is rejected.

The current runtime marks older result provenance stale on each new successful read. The supported subset therefore answers from the latest current result only; it does not combine separate operations into a single grounded answer. Durable old result bodies remain append-only for audit and are not silently edited or deleted. On process restart/auth pause, volatile P2 provenance cannot be reconstructed from body hashes; a saved body without current private metadata triggers deterministic clarification rather than being resubmitted as current.

## 3. Scope binding

Canonical Store validation requires all durable bound references in an activity-scoped context to have the selected activity scope, and ModelContext references must exactly match the durable projection. A no-activity scope only allows activity references. Consequently, listing several activities and selecting another one later in the same Turn is incompatible with append-only bindings. The implemented route supports activity listing in scope-none and expenses/debts for one verified activity context. Selecting another activity requires a new Turn launched through the existing verified UI activity-context entry.

## 4. Pagination and completeness

Frozen v1 has no page cursor, continuation state or completeness field. Its separate capacities are 16 read results per context, 64 typed bound references, 48 durable evidence entries and 16 fact items per result. The backend consumes all bounded HTTP pages in one call using stable sort keys and verifies the HTTP range/count and financial version fence. Only a complete result within those limits is appended. Exceeded rows/pages/bytes, partial pages, query-budget exhaustion or version change fail closed and ask the user to narrow the query; a partial result is never encoded as an empty list.

This is bounded single-call pagination only. Cross-request/restart continuation is not implemented or accepted as complete. Any future continuation needs a versioned typed cursor/completeness contract or separately approved P2 journal bound to owner, Turn, scope, canonical query, source/type/version, page index/cursor digest, generation/CAS revision and TTL. It must not persist a bearer or expose raw cursor to the model. Cursor/page/version mismatch or missing journal must fail closed. Current capacities and the four-read-per-generation budget cap any future continuation.

## 5. Financial representation gaps

Canonical `ExpenseFact` expresses expense original amount/currency and identifying facts; canonical `DebtFact` expresses debt original amount/currency. It does not express the full payment/split DTO, base-currency presentation, or prepayment/refund entities. The P2 supplement retains payment/split role, original amount/currency and base amount/currency from backend DTOs, but the current answer renderer prints only the original-currency payment and split lines. Backend debt base amounts/totals remain internal DTO inputs to source/version binding and are not included in ModelContext facts or rendered answer lines. Therefore no base-currency summary, total, net balance or converted amount is claimed. The Agent never sums, nets, converts or guesses a financial figure.

A complete empty query has no citation-bearing fact under the frozen answer schema. It completes with a deterministic explanation of this citation gap and asks for a new query; it does not fabricate a citation or policy fact.

## 6. Prepayment, refunds and writes

Frozen `ReadOperation` includes only activities, expenses and debts. Prepayment/refund records and signed refund semantics are not implemented. Adding them requires canonical DTO/evidence refs, amount and currency policy, refund linkage/partial-refund semantics, source version/completeness, RLS scope, permissions and T1/root version coordination. No new operation or field was added.

Proposal permissions are present only to let the closed semantic parser recognize create/update/presentation proposal intent in the verified activity context. P2 rewrites that intent to a deterministic non-execution acknowledgement. It does not persist a proposal, preview, confirm card, nonce or write command. `Gateway` stays `Unimplemented`. Proposal adjustment explicitly fails closed. No route to a business write was added.

## 7. Dependency failure and recovery

Frozen `WaitReason` has no dependency-offline or stale-source value. P2 uses the existing `AUTH_REQUIRED` pause only after revoking the current memory grant, and stores the actual sanitized dependency cause in a proof-bound error event. This does not claim token expiration. Auth resume requires an accepted request and a fresh verified lease; idempotency receipt replay does not renew one. Model/read/repair counters survive auth resume and restart within a generation. There is no automatic unbounded retry.

Scope-free clarifications are deterministic templates keyed by typed missing slots; historical clarification events matching those exact templates remain safe to poll after later resume/completion. Unproved P2 errors are hidden. API uses bounded read-ahead so a hidden error cannot block a following status while the public v1 event cursor remains the last delivered sequence. Financial/message facts remain subject to live scope checks.

## 8. Compatibility and rollback

P2 uses the existing route request/response schemas and exact backend project origin derived from the configured Auth project. `provider_mode` defaults to disabled; LM Studio defaults disabled, and its exact-artifact token checker is disabled unless all frozen binding inputs are explicitly set. Health/start does not probe the model, hash/load it, or auto-discover another endpoint. The P2 mode can be disabled as a rollback switch. Store schema, frozen contracts/export, migrations and old P1/mock behavior are unchanged.

## 9. Verification and out-of-scope changes

The full `agent/tests` command passed 248 tests in 46.60 seconds. The read-only export check passed. Exact command, result, failed collection-only invocation and hashes are in the D evidence directory referenced above. Those CPU commands did not run evaluation/T1/T0 tests, live Auth, live Data API, or live LM Studio inference. The separate C provider/Harness probe is not included in that CPU result; its complete 17-call diagnostics failed the semantic gate. B and D remain `NOT_RUN_USER_DEFERRED`. The verification and C run were on the Windows host; P2 Docker/container deployment and container interruption/recovery were not tested, and P1 Docker results do not establish P2 readiness.

The root's 2026-10-11 03:57:27Z read-only baseline audit found 171 of the original 176 files byte-identical; the three authorized P2 integration files were `app/api.py`, `app/components.py`, and `app/settings.py`. Two unrelated T1 changes were external parallel drift: `docs/t1/release-v2/.guide-text.tmp` disappeared (baseline SHA `5fb38314dd9e41a997cad8c636ee23787ee36833a3724817bb3171bedfe376cd`), and `evaluation/t1_teacher_probe/probe.py` changed from `af7a9b7f423a0e0dee94e2a15fbbcca42758017e04389481a2cf4947c7b0fe89` to `bea79cd3f952c65fa252d9d78001a1b19970e2896201744e41a3ef1a970d1843`. T1 protocol documents and metadata/fingerprint hashes were reviewed; no sealed dataset contents were accessed and no Teacher/evaluation run was performed. P2 did not edit or restore those files. The business checkout remains read-only. No commit or push was performed.
