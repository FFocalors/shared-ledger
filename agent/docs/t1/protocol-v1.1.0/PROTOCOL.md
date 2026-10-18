# T1 offline protocol v1.1.0

Status: **approved for offline source, schema, and export review**. Final repository-freeze approval is determined by a separate external SHA-bound root receipt at the path recorded in [ROOT_REVIEW.md](ROOT_REVIEW.md). That receipt must bind the final repository manifest; its hash is intentionally not embedded in these frozen documents, to avoid a self-reference loop. A manifest field of `root_approved=false` is part of this external-approval design and does not contradict a later receipt. This approval does not admit a dataset, authorize training, or establish live backend acceptance.

## Version profile and scope

The negotiated profile is API **1.0.0**, semantic **1.1.0**, operations **1.1.0**, trajectory **1.1.0**, and execution-key **1**. A parser accepts only a complete supported tuple; missing, mixed, or unknown versions fail closed. The vendor v1 contracts remain unchanged. v1.1 adds a separately versioned adapter, typed query evidence, and trajectory format; it does not reinterpret v1 payloads, expand old citations, or upgrade old proposal or execution identities.

There are four semantic decisions: answer, clarify, read, and propose. The registry defines six operations:

| Operation | Kind | Capability | Execution |
|---|---|---|---|
| read.activities | Read | CAP01 | Disabled |
| read.expenses | Read | CAP01 | Disabled |
| read.debts | Read | CAP01 | Disabled |
| expense.create | Proposal | CAP07 | Disabled |
| expense.update | Proposal | CAP08 | Disabled |
| expense.presentation.update | Proposal | CAP08 | Disabled |

All CAP01–CAP17 are present in the fixed registry. Every capability and operation execution flag and every external-write flag is false. This profile is synthetic and offline. It does not enable the old P2 API, a provider, a live backend, authentication, RLS, or financial writes. Immutable v1 structural guards remain in force.

## Query evidence and trust boundaries

v1.1 query references are a separate typed evidence kind from v1 fact and policy citations. A query reference identifies a particular query and result observation; it cannot authorize free-form financial assertions. v1 citation syntax and parser behavior stay unchanged, and the full negotiated tuple selects the v1.1 parser.

Each read binds the operation and normalized user criteria to the backend criteria actually used and to any local post-filter. In this offline profile the backend stage is explicitly scoped; the typed criteria are then checked against every returned row as post-filters. This is different from any P2 date-filter pushdown and does not establish P2 behavior. The digest binds both stages, selected scope, context and evidence-schema versions, source identity/version, and exact query/result bodies. Activity, expense, and debt filters have typed fields so a backend-empty result cannot be confused with a post-filter that matched none of the returned rows.

Adapter-private evidence binds owner and source turn, generation, expected compare-and-swap revision, freshness epoch, selected activity scope, context/schema versions, source identity and version, source fingerprint, query/body digests, observation time, pagination receipts, and source snapshot. Private activity UUIDs and financial-version fences are checked against scope and rows. A participant-filtered read binds its activity and participant references to the same current turn and activity. These checks establish offline consistency among supplied records; they do not prove cryptographic authenticity or that a live adapter obtained data through authorized backend access.

A result is complete only when page receipts form a continuous chain, the exact stable total is verified, the source-version fence holds across pages, row identities are unique, and the full result body matches its receipts. The returned count must equal that complete total. “No backend rows” and “backend rows existed but the post-filter matched none” remain distinct. Partial pages, unknown totals, truncation, errors, overflow, broken cursors, stale versions, or unverified sources cannot prove absence.

Each query is checked against its own current state. Multiple queries in one turn may each remain current when their owner, turn, generation, compare-and-swap revision, freshness epoch, scope, source snapshot, and context binding match. An observation that is stale for current use may remain in same-turn history context when marked as history, but it cannot enter the validated query set or trusted renderer. Restart, resume, or scope change requires a fresh authorized read before affected evidence is used.

## Rendering and business intent

Only the deterministic trusted renderer may turn a validated query reference into an answer. It rechecks the exact current query and matched fact set, distinguishes complete backend-zero from complete post-filter-zero, and marks partial results. It renders selected typed facts and their recorded amount/currency only. It does not sum, net, convert, infer, or accept arbitrary model-written financial claims from query or policy citations. Names and other user-visible values are escaped by the renderer.

Business intent is a trusted input to the protocol. A business query without usable permission or evidence cannot fall back to source-free conversation. A fixed closed-capability acknowledgement requires trusted opt-in. The offline checks do not certify a live permission source, Auth/RLS, archival rules, sub-activity allowlists, or a real write preflight.

## Causal trajectory and SFT projection

The v1.1 trajectory preserves the original Unicode input value character-for-character. This requirement applies to the decoded text value, not the HTTP JSON wire encoding. Typed tool observations are separate steps. A model step may include only observations emitted earlier in the trace. A read decision is followed by its matching typed tool observation; future results cannot be copied backward into an earlier context. Training-only “already read and consumed” hints are not part of the user input or context.

A clarification answer is a new accepted input tied to the immediately preceding clarification decision. It increments generation once, becomes the next model input verbatim, and retains earlier accepted user inputs in causal order. It is not a tool observation and does not authorize stale query evidence. For SFT, the private sidecar is replay metadata only: model input is projected from `step.context`, and the target is the opaque semantic decision. Sidecar UUIDs and private identifiers are never SFT tokens.

## Review status and limits

Root approved all 25 protocol requirements for the **offline source/schema/export review**. The approved source hashes, root reports, generated schema hashes, and D-only export evidence are recorded in [REQUIREMENTS.json](REQUIREMENTS.json), [SOURCE-INPUTS.json](evidence/SOURCE-INPUTS.json), [RESULTS.md](evidence/RESULTS.md), and [ROOT_REVIEW.md](ROOT_REVIEW.md). The final repository-freeze determination is external and must bind the final manifest hash.

This protocol review is not T1 formal data admission. The 393-row v2 candidate and 111-row baseline remain immutable. The root’s 34-row review is not a genuine human receipt: its business text, amounts, and scope were correct, but three rows need query-result provenance repairs. The remaining data actions are to remove appended “already read and consumed” hints from 33 contexts, replace bare internal expense references with user-understandable returned facts in ambiguous clarifications, and add non-integral-cent AA/multi-person small-amount examples. Training eligibility remains false; genuine human review, P2 calibration, and T2 authorization remain pending. The user deferred Student evaluation; GPU evaluation remains deferred.

The separate bounded P2 17-call diagnostic is `FAIL_SEMANTIC_DIAGNOSTIC`; the current R2 evidence is design-only. This profile neither integrates the old P2 API nor authorizes a new model or cloud call. Separate P2 work is not prohibited and needs its own live-path acceptance. Neither this offline protocol nor its root probes claim real CAP acceptance, production behavior, model quality, or Student/GPU results.

Related records: [REQUIREMENTS.md](REQUIREMENTS.md), [MIGRATION.md](MIGRATION.md), [ROOT_REVIEW.md](ROOT_REVIEW.md), [RESULTS.md](evidence/RESULTS.md), and [SOURCE-INPUTS.json](evidence/SOURCE-INPUTS.json).
