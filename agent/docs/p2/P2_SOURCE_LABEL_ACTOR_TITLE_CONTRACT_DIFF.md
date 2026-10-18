# P2 current-actor, source-label, and expense-title contract delta

**Status:** source-backed candidate design for root review; no code or schema was changed by this document. It is not a T1 approval, a deployed-source verification, or an authorization to expose this profile. The four-version tuple remains the only version tuple; no `execution_key` or fifth protocol version field is proposed.

## Decision requested

The current disabled candidate has a user-visible gap: strict `ExpenseFact` omits the authoritative expense title already present on `P2ExpenseDTO`, and the model has no safe way to identify the authenticated user’s Participant when interpreting “我欠谁 / 谁欠我”. It also has no typed source-label channel for rendering payer, split, debtor, creditor, or selected Activity names. A source-grounded answer must not fill those gaps from prompt text, a UI hint, membership alone, or a model claim.

I recommend a separate profile revision, `p2.read-paged-prepayment-refund.v3-candidate`, pinned to a new schema fingerprint and a new prepared-request/token candidate. Keep the previous v2 candidate and its tuple/schema behavior unchanged. This design changes neither the canonical P1 contract nor any frozen T1 artifact.

## Exact candidate DTO delta

The names below are candidate names. They are not currently registered application DTOs.

| DTO | Exact public fields and bounds | Source and invariant |
|---|---|---|
| `P2EntityDisplayLabel` | `entity_ref: OpaqueRef`; `entity_kind: Literal["activity", "ledger_unit", "participant"]`; `scope_ref: OpaqueRef`; `display_name: ShortText` (1–200 Unicode code points, exact source text); `source_kind: Literal["activities", "ledger_units", "participants"]`; `observed_at: aware datetime`; `scope_financial_version: StrictInt[0..9223372036854775807]`; `source_financial_version: StrictInt[0..9223372036854775807] | None`; `source_row_updated_at: aware datetime | None`; `source_receipt_ref: OpaqueRef` | Exactly one of `source_financial_version` and `source_row_updated_at` is present. Activity names use the Activity financial version. Participant/unit names use their own source `updated_at` plus the Activity financial-version fence. The opaque receipt identifies the exact accepted source capture; it is never a permission. Oversized, empty, stale, or uncaptured labels are omitted as incomplete, never truncated or synthesized. |
| `P2CurrentActorBinding` | `actor_ref: OpaqueRef`; `activity_ref: OpaqueRef`; `participant_ref: OpaqueRef`; `source_kind: Literal["participant_claims.current_auth_user"]`; `observed_at: aware datetime`; `scope_financial_version: StrictInt[0..9223372036854775807]`; `source_receipt_ref: OpaqueRef` | `actor_ref` maps to exactly one current `participant_ref` for this generation. The public object contains no user UUID, Participant UUID, or claim-row UUID. The private receipt binds the exact claim row identity and `claimed_at`, since `participant_claims` has no row-level financial version. |
| `ExpenseFact` | Add required `title: ShortText` (1–200); retain the existing expense ref, amounts/currencies, payer/split lines, expense/version fields and `query_evidence_ref` unchanged. | Copy only the `title` from the same source `P2ExpenseDTO` row that produced the fact; keep the same qev and source/version binding. Missing/blank/oversized title makes that projection incomplete. Never fill it from `title_contains`, user text, prompt, or model output. |
| `P2ModelContext` | Add `current_actor: P2CurrentActorBinding | None`; add `source_labels: tuple[P2EntityDisplayLabel, ...]` with a maximum of 128. | All refs must be minted in the same owner/Turn/generation/scope epoch and resolve to a current accepted source receipt. No raw IDs or auth material are model-visible. Labels are a separate trusted channel; do not append them to `input_text` or `recent_messages`. |
| Candidate answer event sidecar | Add a server-derived `source_labels` projection, maximum 128, using the same typed label fields and receipt refs; keep the model's answer-text parser from accepting client/model-authored labels as authority. | The event builder copies only labels referenced by typed facts actually selected for cited qevs or by the current-actor binding used for the answer. Uncited/unused context labels are not emitted. Fresh owner/membership/scope checks are still required on event replay. |

For `read.activities` no-scope discovery, an Activity label uses the row-derived `entity_ref` as `scope_ref`; it does not claim a broad Activity scope. In scoped reads, `scope_ref` is the already source-authorized Activity or child scope. `ShortText` follows the current P2 bounded text rule (strict string, nonempty, max 200). Do not normalize Unicode, rewrite punctuation, trim the persisted label/title, or match names by substring. A source string outside the public bound is not safely representable and therefore yields incomplete projection/clarification; it is not clipped.

The candidate schema must keep the current four semantic kinds (`answer`, `clarify`, `read`, `propose`) and all seven read-operation names. This delta adds neither a read operation nor a proposal/write capability. `read.activities` no-scope discovery remains unchanged. UI Activity/Expense UUID hints remain untrusted input hints: accept them only through the existing source-authorize-and-rebind path before minting an opaque ref; never place the UUID itself in context, prompt, event, or log. A missing hint is not grounds to reject normal app-originated UI scope selection.

## Source mapping and trust boundary

| Public fact/label | Authoritative repository source | Required server mapping |
|---|---|---|
| Activity label | `P2ActivityDTO.name` and `financial_version`; main Activity read | Reuse the current authorized Activity snapshot. `P2ResolvedScope.observed_at` is currently captured before resolver reads; it is not a per-response observation. Bind the label to the actual captured Activity GET response time and source receipt. |
| Participant label | `P2ParticipantDTO.name`, Activity id, active/deleted state; main `public.participants` | Require same active Activity and current resolved roster. The main table has `updated_at` and an update trigger, but candidate `P2ParticipantDTO` currently omits it. Extend only the candidate source DTO/parser to select and validate `updated_at`; retain the Activity financial-version fence separately. |
| Ledger-unit label | `P2LedgerUnitDTO.name`, Activity id, active/deleted state; main `public.ledger_units` | Require same current Activity and authorized unit scope. Main table has `updated_at` and an update trigger, but the current candidate DTO omits it. Extend the candidate parser/select as for participants. A configured child-scope relationship still must be revalidated by the backend. |
| Current-user Participant | `public.participant_claims(id, activity_id, participant_id, user_id, claimed_at)` plus current active Participant in the same Activity | After fresh bearer verification and membership/scope resolution, derive the principal only from `VerifiedReadContext.principal_user_id`; issue an authenticated read filtered by exact Activity id **and** that principal. RLS's current claims policy permits a member to select all claims in an Activity, so application-side filtering is mandatory. Require exactly one row and an active Participant from the same resolved roster. Zero rows means no current actor; more than one or a stale/out-of-scope row fails closed. Never load all claim rows into model context and never call `claim_participant` from P2. |
| Expense title | `P2ExpenseDTO.title`, parsed from the same source row as amount, payer/split rows, and versions | Current `_expense_dto` already requires a nonempty `title`; current strict `ExpenseFact` and candidate mapper omit it. Add the exact title to that fact and to the source-bound typed card. The main business logic allows presentation-only title updates after financial lock, so title freshness must be checked independently of a financial mutation assumption. |

The source chain is repository evidence only. Main migrations, DTOs, and Android code do not prove current hosted deployment, live RLS behavior, or production row contents; no live service was queried here.

### Authentication, freshness, and private receipt binding

1. Verify the bearer and read `principal_user_id` from the verified context. Recheck current membership and the requested Activity/optional child scope; rebind UI UUID hints only after that source check.
2. Resolve the active Participant roster and source labels. Record each actual GET's observation time and capture receipt. Do not use the pre-read aggregate `P2ResolvedScope.observed_at` as the exact label observation time.
3. Read the current user's claim with both `activity_id = resolved Activity` and `user_id = verified principal`. Join the claim's Participant only against that same active resolved scope. The public actor ref does not grant authority and is not a substitute for checking a read grant.
4. Immediately before publishing an answer, freshly recheck membership/scope and the actor claim. Because the claim table has no row financial version, compare the private claim row id plus `claimed_at` and same-Activity/Participant binding. If changed, removed, or inactive, invalidate the actor-bound context and dependent qevs; do not publish a prior answer.
5. Keep principal UUID, Activity/Participant/claim UUIDs, JWT, raw response body, and internal grant/continuation tokens in the private source/Store receipt only. Public refs and digests are opaque audit pointers, never reusable capabilities. Bind private receipts to owner, Turn, generation, claim/context/input digest, scope epoch, exact request/response capture, typed DTO/projection hashes, and expiry/currentness state.
6. Charge the claims and label source reads to the existing active/backend bounds. They are internal source-resolution work, not an eighth model read operation. If the bounded resolver cannot complete, preserve an explicit incomplete/unknown result; do not infer an empty roster or zero debt.

This follows the backend owner's D-only design proposal for per-GET capture/reservation and Store-private locators. That proposal is not an implemented interface or root-approved Store schema; its hash appears in the input table.

## Failure and interpretation rules

- No current claim: omit `current_actor`; a first-person direction question must clarify or remain unsupported. Do not treat creator, activity member, payer, or message author as “我”.
- Stale, duplicate, or out-of-scope claim; non-current membership; label receipt mismatch; changed row version; missing timestamp/capture; or actor reference mismatch: fail closed and invalidate affected evidence.
- No unambiguous matching label in the accepted current scope: clarify rather than guessing a person from text. Preserve UI selection hints as untrusted inputs and validate them; do not make the user re-enter an already source-verifiable name.
- Expense title missing or outside the DTO bound: incomplete source projection, not an empty title, not a fallback to user wording.
- A participant name, payer/split role, debt direction, title, or current-actor mapping remains distinct typed source data. The renderer may display only source-derived labels and title. The model may not synthesize identities, calculate totals, infer FX, or claim creator/owner.
- Schema validation proves only shape/bounds. It does not prove Auth, membership, RLS, currentness, truthful source capture, natural-language intent classification, or factual quality.

## Versioning, compatibility, and rollback recommendation

Current candidate source is `p2.read-paged-prepayment-refund.v2-candidate` with exactly `api=2.1.0`, `semantic=2.0.0`, `operations=2.1.0`, `trajectory=2.0.0`. The new required `ExpenseFact.title`, new model-context actor/label fields, and typed event label sidecar change strict schema and prepared request bytes. They are **breaking for v2**: they must not be silently added under the same tuple, and old serialized bodies, prompt/token bindings, 13-request candidate, or v2 parsers must not be reused as evidence for this candidate.

Recommended identity/version tuple for the next reviewed candidate:

```text
profile_id = p2.read-paged-prepayment-refund.v3-candidate
api        = 3.0.0   # strict wire/schema break: required title + new typed context/event fields
semantic   = 2.1.0   # explicit current-authenticated-Participant interpretation; four semantic kinds stay fixed
operations = 2.1.0   # seven registered read names and proposal-only capability stay fixed
trajectory = 2.0.0   # no new continuation/resume behavior in this contract delta
```

This is a proposal for root/T1 review, not an assigned version. It introduces no fifth tuple field and no `execution_key` wire field. Persist the exact profile id, all four versions, and schema-bundle hash when a Turn is assigned; if the current Store schema lacks the tuple/hash, request a separately reviewed additive migration rather than infer it later. Unknown or mixed tuples fail closed. Keep the v2 profile/schema available for its own pinned Turns. A v2 Turn must never be upgraded in place or parsed with v3 because it happens to contain similar facts.

Rollback disables new v3 assignment and returns new work to the unchanged canonical default/explicitly permitted v2 route. Preserve v3 history and its version/hash; mark unfinished v3 work stale/incomplete and require a new Turn. Never reinterpret v3 state as v2, rewrite historical body/citations, or re-export canonical v1 to accommodate the candidate.

## Implementation boundary if separately authorized

A later implementation should be isolated from canonical contracts and should add, at minimum:

1. A versioned strict contracts module/schema bundle for v3 (`ExpenseFact.title`, context labels/actor, and event label sidecar); keep existing v2 models and `P2_VERSIONS` unchanged.
2. Candidate source DTO/select/parser work for participant/unit `updated_at`, exact per-GET observations/receipts, `participant_claims` filtered by verified principal, fresh before-answer comparison, and same-row expense title mapping.
3. Candidate adapter/runtime composition that uses those exact typed DTOs, never a shape/string heuristic or default auto-opt-in; source authorization stays server-side.
4. New strict CPU tests: exact Unicode title/labels; source empty/oversize; zero/one/multiple/stale/out-of-scope claim; broad member-readable RLS with explicit self filter; UI UUID hint source rebind; missing/stale receipt and changed current actor; no UUID/token leaks; actor absent first-person clarification; payer/split/debtor/creditor labels remain bound to their roles; v2 tuple remains byte-for-byte isolated.
5. Separate generated candidate schema, source/request/prompt/provider/config fingerprints, manifest, and token-only candidate. Existing 13 model requests and past counts are not applicable because the context/schema/body changes.

No app composition, Store migration, event API wiring, canonical registry/export, T1 frozen source, or model-facing activation is authorized by this design document.

## T1 handoff status

This delta must be handed to the T1 protocol owners as a candidate change set with the exact current-source hashes, old/new schema diff, failure cases, and rollback rule. T1 v1/v1.1 artifacts and candidate v2 evidence remain unchanged; no sealed/evaluation body, Teacher output, model, SDK, database, live API, or network was used. The change is not T1 approved, not training eligible, and not evidence of deployed/current source behavior. T1 review must decide the v3 identity, schema/export, source/currentness evidence, event sidecar, and new validation/count denominator before any integration or generation step.

## Source locations

The accompanying D manifest binds every read file by absolute path, byte count, and SHA-256. Principal line references:

- Candidate tuple and strict types: `agent/app/p2_read_contracts.py:34-55, 325-352, 864-886`.
- Current scope DTO omissions and expense source title parser: `agent/app/p2_backend.py:60-138, 517-550, 572-594, 648-692`; candidate scope refs: `agent/app/p2_read_backend.py:219-225, 655-701`; expense fact mapper and query evidence: same file near the `ExpenseFact(...)` source map and lines 1000-1055.
- Typed event answer/fact cards: `agent/app/p2_event_contracts.py:160-238`.
- Main tables/claim keys and updated-at triggers: `supabase/migrations/20260830100426_ledger_units_and_participants.sql:1-28`; broad member RLS and authenticated grants: `supabase/migrations/20260830100429_foundation_rls.sql:19-33`.
- Activity financial version fence: `supabase/migrations/20260831034645_backend_settlement_transfer.sql:29-50`; claim RPC behavior and direct-write revocation: `supabase/migrations/20260901124212_backend_finalization_integration_readiness.sql:290-337`.
- Expense title validation and presentation-only mutability: `supabase/migrations/20260923022250_business_logic_finalization.sql:131-168`, `supabase/migrations/20260921043414_expense_financial_lock_presentation_update.sql`, `docs/backend/BUSINESS_LOGIC.md:146,181,244`.
- Android current-user lookup/filter precedent and typed display DTOs: `app/src/main/java/com/ffocalors/sharedledger/data/financial/FinancialRemoteDataSource.kt:20-22,72-77`, `app/src/main/java/com/ffocalors/sharedledger/data/activity/ActivityModels.kt:62-77,222-228`, `app/src/main/java/com/ffocalors/sharedledger/data/activity/ActivityRepository.kt:100-149,286-292`, and `app/src/main/java/com/ffocalors/sharedledger/data/financial/FinancialDtos.kt:124-139`.