# P2 v3 clarification projection amendment (R3)

Status: engineering-only, default-off candidate. This is not a T1 freeze, release approval, live provider approval, or Runtime assembly proof. The reviewed profile remains `p2.read-paged-prepayment-refund.v3-candidate` with the existing four versions `api=3.0.0`, `semantic=2.1.0`, `operations=2.1.0`, `trajectory=2.0.0`; this amendment adds no fifth version and does not reinterpret those versions as permission to change the canonical protocol.

## Why this amendment is needed

The R2 v3 DTO already has private `P2PendingClarification` values with server-derived `slot`, `reason`, `operation`, `generation`, `source_input_seq`, and `input_digest`. `P2IntentContext.trusted_branch_guard` checks the private input/generation binding. The model-visible `P2ModelContext`, however, carries only a generic decision allowlist and `proposal_clarification_required`; it does not tell the model which exact pending slots, reasons, or operation currently justify clarification. A later request builder cannot safely bridge that gap by inventing a prompt, adding an arbitrary clarification, or treating optional expense filters as required.

## Exact public delta

Add a new strict public DTO with exactly these fields:

```python
class P2PendingClarificationProjection(P2WireModel):
    slot: P2ClarificationSlot
    reason: P2ClarificationReason
    operation: P2ReadOperation | P2ProposalOperation | None = None
```

Its validator reuses the same closed slot/reason/operation coherence rules as private `P2PendingClarification`; the public form contains no authority bindings. Add a required `P2ModelContext.pending_clarifications: tuple[P2PendingClarificationProjection, ...]` with `max_length=16` and no default. Duplicate slots are rejected. Public schema export for the isolated candidate includes this type/property; the canonical exporter and canonical schema remain untouched.

Add a pure trusted-boundary validator, named `validate_p2_clarification_projection(model_context, intent_context)`, that strictly revalidates both DTOs from serialized JSON before comparing them. It requires matching profile/four-version tuple, `model_context.generation == intent_context.generation`, `model_context.trusted_intent.source_input_seq == intent_context.source_input_seq`, matching server classification, and exact equality of canonicalized `(slot, reason, operation)` tuples independent of tuple ordering. The private validator continues to enforce each pending item’s private generation, input-sequence and input-digest binding. The new validator does not invent an input-digest algorithm or expose a digest.

The helper is a consistency check, not an authentication mechanism. A trusted Runtime must build both inputs from the current server-side Turn state and call the helper before prompt construction and token counting. A model-supplied projection, caller-supplied boolean, or successful shape parse does not mint or extend source authority. Existing private `parse_p2_decision` checks for cited fresh query evidence and per-query grant bindings remain in force.

## Guard reachability changes

A nonempty public pending tuple permits `clarify` only; it may not be combined with `read`, `answer`, or `propose`. With no pending tuple, `clarify` is not advertised. Decision-kind/operation allowlists must agree: absent `read` means an empty read-operation allowlist; absent `propose` means an empty proposal-operation allowlist.

For `proposal_intent`, unresolved target/detail slots require a nonempty exact pending projection, `proposal_clarification_required=true`, clarification-only allowlisting, and no proposal operation. A complete resolved proposal has no pending slots, `proposal_clarification_required=false`, and permits recognize-only `propose` with the supported proposal operation; it does not advertise an impossible clarification branch. The private guard still checks `proposal_target_resolved` and rejects recognition while any proposal clarification remains pending.

For `factual_business` and `ambiguous`, a pending slot is clarification-only. Without a pending slot, an ordinary full `read.expenses` request with optional filters absent remains reachable; absence of `expense_ref` is not itself a missing slot. Factual answers still require cited source evidence and private per-query grants. `ambiguous` remains default-deny for source-free factual answers. For `non_business`, no business pending slots or business operations are allowed; a source-free general answer remains reachable without advertising `clarify`.

These allowlists express routing constraints only. They do not prove that a language classifier correctly classified natural language, that a source row is authentic/current, or that a user is authorized.

## Compatibility, schema pin, and rollback

This changes the candidate `P2ModelContext` schema by adding a required bounded property and changes the candidate source module. Therefore any previously recorded request-body, token-count, model-run, or generation approval is not reusable for this cohort. R1/R2 packages and existing test Turn pins remain immutable. New engineering assignments must pin the exact new schema/source cohort; do not repin or reinterpret older Turns. An old schema without `pending_clarifications` is unsupported by this candidate parser and must be held/rejected by any later dispatcher rather than guessed or silently upgraded.

Canonical/P1 contracts, schema, exporter, model provider, prompt policy, Store, Runtime, API, registry, and T1 files are unchanged by this amendment. No default-on routing is authorized. Rollback means disable/hold the new v3 cohort while retaining all prior Turn/profile/schema pins and histories; do not rewrite an existing v3 Turn or route it through v2/canonical parsing. A future dispatcher must reject mixed/unknown source/schema tuples and keep canonical/P1 requests on their existing path.

## Owned implementation and verification boundary

The authorized shared Agent-owned files for this amendment are `agent/app/p2_read_contracts_v3.py`, `agent/tests/test_p2_read_contracts_v3.py`, and this version-diff document. The D-only evidence package is `D:\AI\runs\shared-ledger\p2\v3-clarification-projection-r3-20261014`. CPU tests should cover valid scope/target/proposal pending projections, nonbusiness and no-pending reachable branches, exact tuple matching in both tuple orders, slot/reason/operation mismatch, classification/generation/source-input-sequence mismatch, typed-copy/construct bypass, duplicate/unknown/secret fields, and the 16-entry bound. These checks do not test the Runtime call site, token fit, source authorization truth, RLS, external API behavior, or model quality.

## Input snapshot pins

Before editing, the current contract source was copied byte-for-byte to the D package as `baseline\p2_read_contracts_v3.py` (84,207 bytes, SHA-256 `48d070171f4f94a22e13d3988e0c572d5c89b802e337ce1cd131453962b24e97`); its owned test was copied as `baseline\test_p2_read_contracts_v3.py` (42,876 bytes, SHA-256 `80f44df12cfcd88c376156b1826d295867df32538394515a7b24d943c0e20fc9`). The controlling R3 direction is pinned as `baseline\ROOT_V3_CLARIFICATION_PROJECTION_R3.md` (5,057 bytes, SHA-256 `df219a2f715c75f977a5f53b6e5995bdbc4c154881978a3da2669ea30b173de1`). The complete source-input table, including read-only backend/Store draft hashes, is `pre-edit-snapshots.json` (SHA-256 recorded in the D package receipt). Store/backend entries there are input pins only; this amendment does not modify those modules.

## R3 implementation supplement (2026-10-14)

The final candidate change also closes two assembly gaps found during source review. Public and private pending clarification now share the same classification rule, and the public/private pairing helper reapplies that rule after strict DTO revalidation:

- `proposal_intent` may carry proposal-specific slots only with their proposal operation. The only shared slots it may carry are `activity_scope` or `ledger_unit_scope` with `operation=None`; a read operation or read-detail slot is rejected.
- `factual_business` and `ambiguous` reject proposal-specific slots/operations. Their read-detail slots must remain bound to the applicable read operation; operation-neutral scope slots are allowed. `non_business` carries no business pending slots.
- Proposal pending context remains clarification-only. A proposal’s unresolved target rule remains enforced by the private context; a shared scope clarification does not create a read grant or imply that the proposal is executable.

Verified scope now permits a metadata-only pre-read private context with no financial grant, but only when it has no fresh query receipts and no per-query authorization bindings. This represents already-verified scope/actor/label bootstrap before the model has selected an operation and criteria. It does not authorize a read or factual answer: the private decision parser rejects a first read without an exact fresh grant and rejects an answer without a source grant plus fresh query evidence. The intended sequence is shape parse, fresh scope/source authorization for the selected operation and criteria, strict private guard, then GET. No placeholder grant, query, or criteria is minted during metadata bootstrap.

The isolated CPU regression at `runs\pytest-final-05\run.json` used Python 3.12.0 and pytest 8.4.2 from the Agent virtual environment, with cwd `D:\project\Android\shared-ledger-agent\agent`, `TEMP` and `TMP` under this D package, and arguments `-B -m pytest --color=no -p no:cacheprovider -q --basetemp D:\AI\runs\shared-ledger\p2\v3-clarification-projection-r3-20261014\tmp\pytest-basetemp-05 D:\project\Android\shared-ledger-agent\agent\tests\test_p2_read_contracts_v3.py`. It ran from `2026-10-14T13:32:31.0576311Z` to `2026-10-14T13:32:33.5802892Z`, exit 0, and reported `34 passed in 0.42s`; stdout and empty stderr are retained in the same run folder. It covers proposal/read slot mixing through both DTO validators, operation-neutral shared proposal-scope clarification, metadata-only pairing, read/answer denial before grant, receipt-without-grant denial, and fresh-grant read acceptance.

Historical failures remain preserved. `pytest-run-02.json` records one fixture mismatch: the test helper defaulted the private scope status to `absent` while the public projection correctly used `unresolved`; the fixture was corrected and `pytest-run-03.json` recorded 32 passing checks before this final delta. `runs\pytest-final-04\run.json` records a collection import failure because that invocation used the business-main cwd while importing the Agent checkout; it was not a code failure. The final run used the Agent cwd explicitly. These runs are not represented as one continuous pass.

The candidate remains unassembled and default-off. These checks do not establish classifier accuracy, current source truth, authorization/RLS, provider behavior, Store persistence, Runtime sequencing, or T1/CAP/model acceptance. Canonical/P1 and the frozen v2 contract remain unchanged.
### Final R3 CPU verification receipt

The authoritative final run after the last test-fixture adjustment is `runs\pytest-final-08\run.json`, not the earlier `pytest-final-05`, `pytest-final-06`, or `pytest-final-07` captures. It ran the complete current `test_p2_read_contracts_v3.py` once at `2026-10-14T13:34:16.2055919Z`–`2026-10-14T13:34:19.0106129Z`, exit 0, with 34 passed in 0.41 seconds and no warnings. The test uses typed nested DTOs in its `model_construct` bypass fixtures so the bypass is exercised without relying on serializer-warning behavior. The same test now verifies that both public and private typed-copy/construct classification mismatches are rejected by the projection helper after strict revalidation, and that verified metadata-only contexts cannot be combined with fresh receipts without a grant. This remains CPU-only contract/guard evidence; no source request, external service, Runtime, or model was invoked.
An isolated candidate-schema document was exported by `export_candidate_schema.py` to `p2-v3-candidate-schemas.json` at `2026-10-14T13:35:18.7726900Z`–`2026-10-14T13:35:19.7627282Z`, exit 0. The 128,558-byte schema file has SHA-256 `a52503a281057ad3301f6e6bd16945f7d3f1d863c550ccf318a0bbe8d2d49981`. This calls only `export_p2_v3_json_schemas()` in the isolated candidate module; it does not invoke or change the canonical exporter.
At the final R3 package freeze, read-only source-input comparison showed `p2_read_backend.py` and `p2_backend.py` still matched the pre-edit pins, while `p2_source_store_v3.py` and `p2_source_store_v3_migration.sql` had changed in the shared Agent checkout during parallel Store-owner work. R3 did not edit or test those files. `final-manifest.json` records both pre-edit and freeze-time hashes/byte counts for every source input so those concurrent changes are not attributed to this R3 patch.