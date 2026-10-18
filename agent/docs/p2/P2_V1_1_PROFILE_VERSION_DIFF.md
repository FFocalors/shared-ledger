# P2 T1 v1.1 profile: version-diff plan

**Status: planning only.** This does not approve source changes, live execution, or adoption of the complete P2 `READ_PROTOCOL_NEXT` proposal. Keep P2 v1, the current R2 model candidate and all frozen inputs unchanged. Wait for the pending counter revision and R2 diagnostic before any work that touches those inputs.

## Proposed profile boundary

Use the separately named candidate `p2.t1-read-v1.1.0-cpu-draft`, with the exact T1 tuple API `1.0.0`, semantic `1.1.0`, operations `1.1.0`, trajectory `1.1.0`, execution-key `1`. The selector is server-side and defaults to `disabled`; the current API request schema does not gain a model/user-controlled profile selector. CPU tests may inject the draft profile with fake transport only. Reject missing, mixed, or unknown tuples; never silently fall back between profiles. The frozen T1 registry still has execution disabled, so this draft cannot enable live reads.

This profile may reuse T1’s frozen typed query evidence, trusted-renderer, and clarification definitions as an **offline schema basis**. It must remain separate from canonical `contracts.py` v1 and from T1’s frozen package. Any executable profile requires a new source/schema manifest and explicit root/T1 approval; changing an operation’s execution status or semantic mapping requires a new freeze rather than an edit to v1.1.0.

## First CPU-only integration increment

Limit the candidate to the three existing read operations: `read.activities`, `read.expenses`, and `read.debts`. Exercise them with fake transport and fake identity only. Keep the current P2 date-pushdown route byte-for-byte unchanged; the v1.1 profile gets a separate scope-only backend path that follows the frozen T1 criteria model:

- `read.activities` records scope-none backend criteria.
- Expense and debt reads record the verified Activity scope as backend criteria. User criteria such as date, title, participant, and currency are represented and applied as local post-filters. Server-derived membership, active Activity, in-scope ledger units, and logical-delete constraints remain enforced and must be represented in the new profile’s source/query binding. If the bounded scope read cannot be complete within reviewed limits, return incomplete; do not treat the post-filter or partial result as zero.
- Do not disguise P2 date pushdown as T1’s scope-only backend stage. The old pushdown path remains available only to the unchanged P2 v1 behavior.

Capture a private typed page receipt at the transport boundary for every verified page: page index, requested and actual range, returned row count, exact total, stable ordering identity, response-body digest, and financial-version observation. Preserve the bytes/digests needed to bind the source result before parsing/post-filtering. `complete` may become true only after receipts prove a continuous range, stable exact total, unique rows, and the required source-version fence. A server-capped short page advances by the actual verified row count. Unknown totals, gaps, duplicates, changed totals/FV, auth or budget failures, and partial reads are incomplete and cannot prove absence. Do not reconstruct receipts later from `complete=True`.

Build `QueryEvidenceObservation` only from those verified facts. Bind it privately to owner, Turn, planning generation, active CAS/claim, selected scope, context/freshness version, source identity/version, and financial-version map. Raw UUIDs, bearer, offset/cursor, page URL, and untrusted model identifiers stay private. The model sees only the typed references and T1 fields selected for this profile. Do not add Store persistence or cross-request continuation in this increment; after restart/Auth pause, old volatile query evidence is stale and requires a fresh authorized read or a fail-closed clarification.

The trusted renderer uses only the current query/result and matched facts. It distinguishes complete backend-zero from complete post-filter-zero and cites the query evidence for either only when completeness and authorization were verified. Unknown, partial, stale, or missing evidence must not become “no records.” It must not sum, net, convert, infer a balance, or turn prepayment into debt.

Add a server-trusted business-intent gate before accepting a conversation answer. The current P2 seam has no `trusted_business_intent` input and permits a generic no-scope conversation path. Until a separately reviewed trusted intent source exists, unknown/unclassified business intent fails closed; the model cannot grant itself a conversation exemption. Conversation opt-in requires a trusted source and explicit design.

Map clarification to the T1 causal trace: preserve the decoded original Unicode text exactly; tie each accepted clarification to the immediately preceding clarification decision; record its response as a new user input, not a tool observation; preserve earlier accepted inputs in order; and increment generation exactly once. Clarification must not reactivate stale query evidence. This maps dialogue clarification only; it does not implement continuation or Auth-resume recovery.

## Planned file ownership after a separate implementation authorization

Each file has one owner; root should assign named workers before implementation. This plan does not itself assign a worker or permit edits.

| File | Single-owner responsibility |
|---|---|
| New `agent/app/p2_profile_v1_1.py` | Profile ID, exact version tuple, strict negotiation, disabled-default selection, T1 profile DTO validation and projection. Keep T1 profile types out of canonical v1. |
| `agent/app/p2_backend.py` | Backend owner adds fetch-time page receipts and the isolated scope-only read path. Keep existing P2 v1 pushdown/query behavior unchanged. |
| `agent/app/p2_runtime.py` | Runtime owner gates profile selection; binds owner/Turn/generation/CAS/scope/FV/freshness; applies trusted-intent and clarification rules; treats restart evidence as stale. No Store changes. |
| `agent/app/p2_harness.py` | P2 Harness owner validates the full negotiated tuple and typed query evidence; builds the P2 envelope and renders only verified current results and exact-zero distinctions. P1 `agent/app/harness.py` is outside this increment. |
| `agent/app/settings.py`, `agent/app/components.py` | Composition owner wires a server-side profile selector whose default is `disabled`; no profile selection from model or request body. |
| New `agent/tests/test_p2_v1_1_profile.py` | One CPU/fake integration owner adds the focused cases below without editing the existing 126 frozen inputs or R2 tests. |
| New `agent/contracts/p2-t1-read-v1.1.0-cpu-draft/` manifest/schema package | Profile owner records T1 input hashes, P2 source/mapping hashes, tuple, fixtures, criteria/result projection, enabled-operation inventory, denominator, and rollback switch. Do not alter `agent/contracts/v1.0.0`, T1 package, or existing exporter outputs. |

`agent/app/api.py`, `agent/app/store.py`, `agent/app/contracts.py`, provider/model prompts, T1 artifacts, old exports, and existing tests are outside this first increment. If implementation later needs one of them, root must authorize a separate ownership and compatibility review first.

## Focused CPU acceptance examples

- One complete and one multi-page synthetic read for each of the three read operations; assert query reference, normalized criteria, backend scope, post-filter, source/body/query digests, exact totals, and private binding. Verify date filtering occurs in the new path after scope fetch while the old P2 path is unchanged.
- A server response capped below requested page size advances by actual row count. Wrong/unknown `Content-Range`, total drift, duplicate/gap, expiry/401/403, stale FV, timeout, or byte/page budget exhaustion yields incomplete/error and no “zero” answer.
- Complete backend-zero and complete post-filter-zero produce distinct trusted query citations. Missing total or incomplete pages cannot produce either claim. Stale, cross-scope, wrong-generation, missing-receipt, or claim-lost evidence is rejected.
- No-scope business request, missing permission, or missing trusted intent cannot be accepted as generic conversation. Model-authored intent cannot opt out of the gate.
- Exact-Unicode original input and clarification response survive the trajectory; response links to the immediately previous clarify step; generation increments once; old query evidence stays stale after clarification/Auth restart.
- No query exposes a private UUID/token/cursor; no read computes totals or FX; proposal/write paths are never called. Prepayment, repayment, refund, and `next_page` are asserted unsupported by this draft.

Evidence is a new D-backed CPU manifest with source/schema hashes, exact test command/log, fake transport version, and per-case results. It must state “synthetic only”; it is not T1 data admission, real Auth/RLS acceptance, provider/model quality, or production approval.

## Deferred version decisions and rollback

Cross-request pagination/continuation and restart recovery need a separately approved protocol/state version, durable-owner/CAS design, TTL, and reauthorization tests. Prepayment, repayment-progress, and refund need separate typed operations/DTOs, source/ACL/RLS mapping, and T1/root version approval. They do not belong in `read.debts` or this CPU increment. The optional same-Turn Activity list-then-select flow remains a separate product/schema decision. The T1 offline zero-query shape can use its query citation; the frozen P2 v1 parser cannot.

Keep the new profile disabled by default. Rollback disables it for new Turns and returns to the unchanged P2 v1 path; do not reinterpret or rewrite an in-flight v1 context, delete refs, or convert partial v1.1 results. A tuple mismatch or profile failure fails closed—there is no automatic downgrade. No production use is eligible until a separate frozen profile explicitly authorizes reads and its real current-user Auth/RLS/source proofs pass.

## Baseline anchors

T1 offline freeze receipt SHA-256: `352dcba6cce50c249709be37ba96fd2427b43958406ec570fb5cd2a183ea2036`; its bound manifest SHA-256: `5665565eb503c16e5e8c8ca6cb207743ee52e5add1b0b27c7aeca8cc3a6a80c3`. T1 contract tuple and offline-only limits are in `agent/docs/t1/protocol-v1.1.0/PROTOCOL.md` and `MIGRATION.md`. The adopted P2 boundary review is `agent/docs/p2/T1_V1_1_P2_ADOPTION_REVIEW.md`, SHA-256 `003c3229027dbd6b532806459a88dad90b6f7e4dddbffcc3f27b799a1374a549`. The v1 `contracts.py` hash remains `9fd214d9d8eb43c6f5b03b1d7e95b2bef274dbf9e8be495f536f495b48a5bf2d`.