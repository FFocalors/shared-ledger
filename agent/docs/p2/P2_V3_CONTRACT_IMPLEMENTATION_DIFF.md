# P2 v3 strict-contract candidate

**Status:** isolated, disabled, unassembled CPU candidate. This is not a formal T1 freeze/adoption, training/CAP eligibility, production routing, or model-run approval. It changes no canonical P1 contract, P2 v2 module, T1 frozen artifact, Store, Runtime, API, provider, or registry.

## Candidate identity and compatibility

The candidate uses exactly this four-field tuple:

```text
profile_id = p2.read-paged-prepayment-refund.v3-candidate
api        = 3.0.0
semantic   = 2.1.0
operations = 2.1.0
trajectory = 2.0.0
```

There is no `execution_key_version` or fifth protocol field. Existing v2 profile, schemas, parsers, exported canonical contracts, and prepared requests remain pinned to their prior identity and bytes. V3 is a separate module and never routes v3 values through v2 profile-bound models or guards. Unknown/mixed tuples and v2 labels fail closed. Old v2 Turns and receipts must remain on their original profile. A v3-aware future Runtime must keep each admitted Turn pinned; disabling assignment means hold/resume the same Turn with fresh authorization, not discard, downgrade, or automatically create a new Turn.

The actual application module is `agent/app/p2_read_contracts_v3.py`; the focused contract test is `agent/tests/test_p2_read_contracts_v3.py`. The v3 module is not imported or registered by application composition. Its only exporter, `export_p2_v3_json_schemas`, returns a separate candidate schema bundle and does not call the canonical exporter.

## Public source DTO delta

`ExpenseFact.title` is required, strict text from the same accepted expense source row and qev as the rest of the expense fact. It preserves the exact Unicode string, accepts 1–200 characters, rejects blank/over-bound text, and never trims, clips, or fills from user/model text. The model does not calculate totals, net currencies, or infer FX.

`P2ModelContext` adds required `current_actor: P2CurrentActorBinding | None` and `source_labels: tuple[P2EntityDisplayLabel, ...]` (maximum 128). `current_actor` exposes only opaque `actor_ref`, `activity_ref`, and `participant_ref`, the literal source marker `participant_claims.current_auth_user`, an aware observation time, the Activity financial-version fence, and an opaque metadata receipt reference. `P2EntityDisplayLabel` exposes an opaque entity/scope ref, entity kind (`activity`, `ledger_unit`, or `participant`), exact bounded `display_name`, source kind, aware observation time, Activity financial-version fence, exactly one row-version source (`source_financial_version` for Activity, or `source_row_updated_at` for Participant/unit), and an opaque metadata receipt.

The context rejects duplicate labels, wrong entity/source-kind combinations, inconsistent current scope, inconsistent financial-version fences, invalid timestamps, and a current actor without its matching Participant label. No-scope `read.activities` may carry only self-scoped Activity labels; each discovered Activity may have its own financial version. Unresolved or unauthorized scope carries no source metadata or prior facts. UI UUID hints remain a separate untrusted resolver input and are not accepted as model authority, a label, or a minted ref.

These DTO checks establish shape only. They do not verify bearer/Auth identity, membership, RLS, whether the claim query was filtered by the verified user, source capture, currentness, or the truth of the metadata receipt. `participant_claims` and labels are bootstrap metadata before model read selection; they are not an eighth model operation and cannot satisfy a financial qev/citation or authorize a financial answer. Actual per-GET capture receipts and fresh source authorization remain Runtime/backend responsibilities.

## Semantics, reads, and private authorization

The four semantic kinds remain `answer`, `clarify`, `read`, and `propose`. All seven operation names remain unchanged: `read.activities`, `read.expenses`, `read.debts`, `read.refund_events`, `read.prepayment_accounts`, `read.prepayment_usages`, and `read.prepayment_return_events`. `read.debts` continues to name the reviewed `expense_debt_line` candidate source variant; this contract does not change the existing v2 settlement-options RPC. Expense debt source `original_amount` and `original_currency` remain nullable; base zero remains legal and distinct from unknown original values. Monetary source lexemes and strict non-coercing int64 financial versions retain their field-specific bounds.

The private `P2IntentContext` is independently bound to the same v3 profile and four-field tuple. It carries server-created `P2PendingClarification` entries with a typed slot, reason, current generation, source input sequence/digest, and relevant read or proposal operation. Read slots are `activity_scope`, `ledger_unit_scope`, `expense_target`, `participant_target`, `currency`, `date_range`, `prepayment_account`, and `return_target`; proposal slots are `proposal_target`, `proposal_title`, `proposal_amount`, `proposal_currency`, `proposal_participant`, and `proposal_occurred_at`. Reasons are the bounded values `missing_required_scope`, `multiple_scope_matches`, `ambiguous_user_reference`, `required_target_missing`, and `source_label_unavailable`, with slot/operation combinations validated. Its clarification flag must agree with that pending set, and every entry must bind the current generation, source input sequence, and input digest. The JSON decision shape limits `missing_slots` to known slot names; `parse_p2_decision` revalidates the trusted context and accepts only a nonempty unique subset of the slots bound to the current input. It rejects invented slots, stale input/generation bindings, and an `expense_target` clarification when no such slot is pending. The presence of a pending filter is an explicit Runtime decision for that request; the read criteria themselves continue to permit absent optional filters. In particular, a full expense read does not require an `expense_ref`.

Proposal-specific slots are independently bound to the exact proposal operation. An unresolved proposal target requires a pending `proposal_target` slot and permits clarification only. Resolved proposal recognition remains reachable; proposal detail slots may independently require clarification. `propose` only recognizes intent. No preview, confirmation, card, mutation, or write operation is introduced.

Financial answers retain the strict per-cited-qev guard: each cited receipt must have exactly its own current matching grant/binding for owner/Turn, generation/input, scope, operation, criteria, and expiry. A cited subset is allowed; uncited bindings do not have to be cited and cannot authorize a different qev. Cross-scope, missing, stale, or expired cited bindings fail closed. Public actor/label receipts are not qevs and cannot substitute for these private bindings. Source freshness remains a Runtime responsibility.

`parse_p2_model_context` and `parse_p2_decision` accept exact JSON and revalidate typed instances at their trust boundaries. They reject duplicate keys, non-finite JSON values, extra/private fields, and model-copy/construct bypasses. These are parser/DTO checks, not Auth or data-source verification.

## Assembly boundary and rollback

No Runtime loop is implemented here. A future loop must use the existing `P2Runtime` scheduler, claim/session, and Turn/control API; a second scheduler, Runtime, service, or database is out of scope. This slice adds no migration. The previously suggested `agent/migrations/002_p2_turn_protocol_binding.sql` path is prohibited; any future candidate SQL must be a separately authorized, append-only `agent/app`-owned `003-or-later` artifact reviewed with the Store owner.

Rollback closes new v3 assignments and keeps any already admitted v3 Turn pinned to its original version/schema/source identity, budget, and history. V2-only workers must hold/reject unknown v3 bindings; they may not reinterpret or downgrade them. Resumption happens in the same Turn only with fresh bearer verification, membership/scope/actor checks, and source revalidation within the remaining budget. A different profile or new Turn requires an explicit new user task.

The v3 candidate and its source/schema/request fingerprints require their own review. No previous v2/13-request result transfers. Formal T1 freeze/adoption, training/CAP, and release require their own explicit T1 review. This work does not inspect T1 data bodies, Teacher output, or sealed/evaluation material.

## CPU evidence boundary

The focused tests construct synthetic, non-sensitive DTO fixtures and invoke only the strict Pydantic/JSON helpers. They cover version and read dispatch, title/amount/nullable-source bounds, actor/label scope relationships, all four semantic branches, current private slot/reason binding, per-qev citation subsets, and malformed/stale/extra-field cases. Passing tests prove candidate shape and guard behavior only. No SDK/model, network, Docker, Supabase CLI/MCP, database, canonical exporter, T1 body, or live source was used. `NOT_APPROVED` remains the formal T1/model/runtime status.

The complete command, exact stdout/stderr/exit, interpreter/import provenance, input/output hashes, and independently generated v3 schemas are recorded in the D-only package `D:\AI\runs\shared-ledger\p2\v3-contract-implementation-20261014`. This document records the candidate delta; the D manifest is the evidence binding.

## R2 review correction: per-query authorization and Activity-version coherence

The R2 correction removes the former single-primary-grant fallback for factual answers. Every cited qev must have its own private binding to the exact current receipt and matching operation, criteria digest, scope, owner Turn/input generation, and expiry. An empty binding set never authorizes a cited answer. An answer may still cite a valid subset; an expired grant or receipt that is not cited does not invalidate that subset. Shape parsing remains separate and does not mint or require source authorization before the read is selected.

The model-context validator now rejects duplicate qev refs before building lookup maps. For scoped contexts, every financial qev carries exactly one Activity fence for the authorized parent Activity; metadata labels, the current-actor binding, financial qevs, and financial facts that assert a version must agree for that Activity. A fact's `financial_version` must match its enclosing qev's matching Activity fence. Child-scope Expense/Refund facts use the trusted scope DTO's parent Activity for this check; no Activity ref is inferred from model text. For no-scope Activity discovery, fences are compared independently per Activity, so separate Activities may validly have different versions. Metadata-only bootstrap remains valid without financial qevs or facts. `ActivityFact` has no numeric `financial_version` field; its `context_version` is a distinct source value and is not treated as an inferred numeric fence.

These checks establish internal DTO consistency only. They do not establish Auth identity, source authorization truth, capture authenticity, or currentness. The immutable first candidate package and its 24-pass record remain in `D:\AI\runs\shared-ledger\p2\v3-contract-implementation-20261014`; R2 changes and CPU evidence are separately bound in `D:\AI\runs\shared-ledger\p2\v3-contract-review-fix-r2-20261014`.
