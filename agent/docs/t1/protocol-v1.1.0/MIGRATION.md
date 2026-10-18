# Migration and version boundary

Status: **approved for offline source, schema, and export review**. Final repository-freeze approval is determined by a separate external SHA-bound root receipt that must bind the final repository manifest; its hash is intentionally not embedded in these frozen documents to avoid a self-reference loop. The manifest's `root_approved=false` field is part of this external-approval design. This protocol review does not authorize data regeneration, model use, or a live backend.

## From immutable v1 to offline v1.1

Keep the vendor v1 contracts and their existing files byte-for-byte unchanged. The new profile explicitly negotiates API 1.0.0, semantic 1.1.0, operations 1.1.0, trajectory 1.1.0, and execution key 1. A complete supported tuple is required before parsing; mixed, incomplete, or unknown tuples fail closed. Do not reinterpret old payloads as v1.1, upgrade old proposal or execution identities, or silently expand v1 citations.

v1.1 adds typed query observations and query citations, canonical criteria, explicit backend and post-filter stages, completeness metadata, source/scope bindings, trusted deterministic renderers, and causal clarification/resume trajectories. Query citations are a new evidence type; they cannot be placed into a v1 candidate or accepted by the v1 parser. Do not fabricate facts, policy citations, or citations that point to a different result. Input preservation is character-for-character for the decoded Unicode text value; JSON wire encodings may differ while representing the same text.

The private sidecar is dataset replay metadata only. The SFT projection takes model input from `step.context` and target from the opaque semantic decision. Sidecar UUIDs and private identifiers never become model input or target tokens. The protocol registry remains offline: four semantic decisions, six named operations, CAP01–CAP17 represented, and every execution and external-write flag false. The protocol does not activate the old P2 API, real Auth/RLS, or production backend access.

## Existing candidates and future data versions

The 393-row release-v2 candidate and earlier 111-row baseline remain immutable. The preservation check compared split-file raw hashes and row counts; protocol probes did not read held-out semantics. Do not rewrite examples, source receipts, creation manifests, protocol fingerprints, or splits, and do not reuse old receipts as a new preparation. A protocol or data revision requires a fresh source freeze and new versioned preparation.

An explicit adaptation declaration is not enough by itself. The adaptation gate requires explicit conversion, a new source freeze, replay and review, and a new split; false or missing gates are rejected. Any future candidate must bind new frozen bytes and hashes, schema/export fingerprints, Gold and replay checks, split isolation and near-pair dispositions, and a new review packet. Run all current gates and record new receipts against that version.

The root’s review of 34 train-only rows found the business text, amounts, and scopes correct in all 34; output provenance passed for 31 and needs repair in rows 21, 22, and 24. Rows 21 and 24 are simulated tool-empty results. Row 22 has five fixture results before a title post-filter returns zero; its query, filter, scope, and completeness need to be bound. This review is not a genuine human-review receipt or live backend evidence.

Four data-quality actions remain before the old candidate can be reconsidered: bind query-result provenance for those three empty-result answers; remove appended “already read and consumed” hints from 33 of 34 contexts and match the P2-visible context; clarify ambiguous expenses using returned participant or expense title/date/amount rather than a bare internal expense reference; and add non-integral-cent AA and multi-person small-amount cases. The prior equal proposals were whole-cent cases, so the packet does not establish AA tail handling. This is missing coverage, not an AA algorithm defect.

Changes to canonical query-citation or trusted-renderer semantics require a new protocol version and freeze. Existing frozen inputs and receipts cannot be repaired retroactively by wording changes. Offline owner/turn/scope/revision and financial-fence checks establish consistency among supplied records; they do not prove cryptographic provenance, current backend authorization, archive/sub-activity rules, or a real write preflight.

## P2 and evaluation boundary

The bounded P2 17-call diagnostic is recorded as `FAIL_SEMANTIC_DIAGNOSTIC`; the current R2 evidence is design-only. This profile does not integrate the old P2 API or backend and does not authorize a new model or cloud call. Separate P2 development is not paused or prohibited; a live P2 path needs its own acceptance. The 34-row review is not P2 calibration, live CAP acceptance, or Student evaluation.

Training eligibility remains false; genuine human review, P2 calibration, and T2 authorization remain pending. Student evaluation is deferred under the user's instruction, and GPU evaluation remains deferred. This protocol work is an offline contract review only.
