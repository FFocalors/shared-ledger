# P2 v3 candidate profile: adoption status

**Status as of 2026-10-18: undecided (未裁决). This profile is not a formal baseline.** The v3 candidate is a default-off engineering candidate. No record has been found on this date that accepts it as the current baseline, freezes it, or rejects it. Until such a decision exists, the frozen v1 contracts remain the baseline and this profile may be used only as a disabled, opt-in candidate.

## Profile identity

The candidate is exactly this four-field tuple (no `execution_key` or fifth protocol version field):

```text
profile_id = p2.read-paged-prepayment-refund.v3-candidate
api        = 3.0.0
semantic   = 2.1.0
operations = 2.1.0
trajectory = 2.0.0
```

- Defined in `agent/app/p2_read_contracts_v3.py`: `P2_V3_CANDIDATE_PROFILE_ID` (line 36) and `P2_V3_VERSIONS` (line 50); the tuple is pinned as a `Literal` on every candidate wire model that carries it (lines 263, 298, 718, 1091, 1403).
- Candidate contract diff: `agent/docs/p2/P2_V3_CONTRACT_IMPLEMENTATION_DIFF.md`.
- Direct predecessor: `p2.read-paged-prepayment-refund.v2-candidate` (`api=2.1.0`, `semantic=2.0.0`, `operations=2.1.0`, `trajectory=2.0.0`), defined at `agent/app/p2_read_contracts.py:36` and documented in `agent/docs/p2/P2_READ_PAGED_V2_CANDIDATE_DIFF.md`. When the v3 gate is on, composition admits both candidate profile ids together (`agent/app/components.py:240-241`). Do not mix or substitute their tuples.
- For contrast, the frozen baseline is canonical v1: `api/semantic/operations/trajectory = 1.0.0`, manifest version 1, 55 generated files in `agent/contracts/v1.0.0/`. Its input paths and SHA-256 values are listed in `CONTRACT-VERSION-DIFF.md` under "Frozen inputs and independent P2 fingerprint".

## Enablement switches

Both switches are **default false** and use the `AGENT_` environment prefix (`agent/app/settings.py:32`):

- `AGENT_P2_V3_CANDIDATE_ENABLED` → `p2_v3_candidate_enabled` (`agent/app/settings.py:66`).
- `AGENT_P2_V3_NATIVE_CANDIDATE_ENABLED` → `p2_v3_native_candidate_enabled` (`agent/app/settings.py:67`).

Turning the base gate on requires, and fails closed without, all of: `provider_mode=p2`, `p2_lmstudio_enabled`, the exact-artifact token budget, the fixed reviewed budgets (context 8192, input 6144, schema margin 512) and a pinned execution manifest (path, SHA-256 and repository root). The native switch additionally requires the base gate, and an HTTP timeout above 30 seconds is available only to the native candidate (`agent/app/settings.py:263-298`).

What the gate selects at runtime, in `agent/app/components.py`: the v3 Store arguments, a `_CandidateProfileStore` bound to `P2_V3_CANDIDATE_PROFILE_ID` (lines 104-116), the v3 prompt/prepared provider (`P2V3ReadProvider`, or `P2V3NativeCandidateReadProvider` when the native switch is set, lines 205-221), and the Runtime's `enabled_candidate_profile_ids` (line 240). Operator-facing details, including the `native_candidate` manifest wiring, are in `agent/docs/p2/P2_CONFIGURATION_EXAMPLE.md` ("Optional native v3 candidate").

## Separation from frozen v1

- The profile lives in its own module, `agent/app/p2_read_contracts_v3.py`, next to but separate from the frozen v1 contract module and the v2 candidate module.
- Its only exporter is `export_p2_v3_json_schemas` (`agent/app/p2_read_contracts_v3.py:1823`), whose docstring is "Return isolated candidate schemas; never invokes the canonical exporter". No v3 schema is written into `agent/contracts/v1.0.0/`, and the canonical export is not rebuilt by it. One exported bundle is recorded as 128,558 bytes, SHA-256 `a52503a281057ad3301f6e6bd16945f7d3f1d863c550ccf318a0bbe8d2d49981` (`P2_V3_CLARIFICATION_PROJECTION_DIFF.md`).
- The v3 diff documents describe the module as "unassembled" and state that it "is not imported or registered by application composition" (`P2_V3_CONTRACT_IMPLEMENTATION_DIFF.md` line 19; the module docstring repeats it). That is now stale: `agent/app/components.py:32` and `agent/app/p2_runtime.py:39` import the module unconditionally, and the default-off settings flags — not the import — are what keep the candidate off. Treat the older "unassembled" wording as pre-assembly history, and verify against the current source before relying on it.

## Pagination behavior in the current code

The candidate has a typed continuation rather than cross-request cursors:

- `P2ReadContinueRequest` (line 295) and the paged projection `P2PageProjection` (line 694) are defined in the candidate contract module `agent/app/p2_read_contracts_v3.py`.
- The Runtime mints one continuation hint on the fresh query evidence and, after the continuation call, requires the returned page to be exactly page 1 with no further page, failing closed otherwise (`agent/app/p2_runtime.py:1157`: "v3 continuation must produce one terminal second page"). A resume rereads page 0 through a new attempt and a fresh admission instead of restoring an old cursor.
- The Store keeps only the next-page ref digest on the accepted page (`agent/app/p2_read_store.py:334`) and consumes the continuation ref exactly once (`consume_continuation`, `agent/app/p2_source_store_v3.py:719`, called from `agent/app/p2_read_backend.py:1466`).

This document asserts only the behavior above. The page ceiling is whatever `agent/app/p2_runtime.py` currently implements.

## Adoption record: none found — undecided

Searched on 2026-10-18: every document under `agent/docs/**` (including `t0`, `t1`, `p1`, `p2`) and the D-only evidence root `D:/AI/runs/shared-ledger/p2` (442 entries).

Root records about v3 that do exist, and why none of them decides the profile's adoption:

- `D:/AI/runs/shared-ledger/p2/root-runtime-integration-20261014/ROOT_V3_CONTRACT_IMPLEMENTATION_R1.md` (2026-10-14): "Engineering candidate decision: approve a separate, unassembled p2.read-paged-prepayment-refund.v3-candidate with exactly api3.0.0/semantic2.1.0/operations2.1.0/trajectory2.0.0. This is not formal T1 freeze/training/CAP/release, not production routing or model-run approval." This authorizes the candidate's creation; it explicitly excludes a formal freeze.
- `D:/AI/runs/shared-ledger/p2/v3-source-codec-backend-final-r4-20261015T0331Z-luna/ROOT_R4_NULLABLE_AND_SOURCE_LIMITED_REVIEW.json` (2026-10-15): `"decision": "ACCEPTED_FOR_DISABLED_CPU_CANDIDATE_FOUNDATION_ONLY"`. An increment-level acceptance, scoped to a disabled candidate foundation.
- Every other root artifact that mentions the profile is a per-increment work order, limited review or hash check (`root-runtime-integration-20261014/ROOT_V3_*.md`, `root-review-artifact-bindings-20261014`, `v3-protected-event-dto-*`, `v3-source-codec-backend-*`), not a verdict on the profile.
- No T1 record mentions the profile: `agent/docs/t1/` has no v3 or read-paged material, and `T1_V1_1_P2_ADOPTION_REVIEW.md` covers only the offline T1 v1.1.0 freeze.
- Wording caution: `P2_V3_PROMPT_PROVIDER_IMPLEMENTATION_DIFF.md` calls `p2.read-paged-prepayment-refund.v3-candidate` "the accepted profile". That refers to the review acceptance of one candidate slice, not to a baseline adoption.

Therefore: **no root accept-or-reject record for this profile exists as of 2026-10-18, and the profile's adoption status is 未裁决 (undecided).** The candidate's own documents consistently self-describe it as candidate, isolated, disabled and default-off, which is consistent with that status.

## What a decision would require

If the profile is to be adopted, rejected, or kept as a candidate, the decision record should name at least:

1. **Root review and a written verdict** naming the profile id and the exact tuple, stating what is accepted (schema only / disabled candidate / enabled default / formal baseline), binding the reviewed source, schema and manifest hashes, and dated. The `ROOT_R4_*` review JSON is a usable precedent format.
2. **T1 synchronization.** The frozen T1 registry contains only `read.activities`, `read.expenses`, `read.debts` and three disabled proposal operations; it has no prepayment, repayment or refund operation and no model-facing continuation action (`T1_V1_1_P2_ADOPTION_REVIEW.md`). The four extra read operations and the continuation control message in this profile therefore have no T1 mapping, and the existing T1 v1.1.0 receipt does not transfer to them. A decision must either add that mapping under a new freeze or state explicitly that T1 does not cover v3.
3. **Preregistration and hash impact.** The frozen input paths and SHA-256 values, including `dataset_contracts/t1/protocol-fingerprint.json` and the Teacher-probe preregistration hashes, are listed in `CONTRACT-VERSION-DIFF.md` under "Frozen inputs and independent P2 fingerprint". The v3 diff already requires that "the v3 candidate and its source/schema/request fingerprints require their own review. No previous v2/13-request result transfers" (`P2_V3_CONTRACT_IMPLEMENTATION_DIFF.md`). Adoption would need its own source/schema/request fingerprint set and an explicit statement about whether the existing preregistration covers it. Canonical `contracts/v1.0.0/` and its export must stay byte-for-byte unchanged.
4. **Rollback.** The existing switch semantics already define it: rollback closes new v3 assignments and holds or rejects unknown v3 bindings instead of reinterpreting or downgrading them (`P2_V3_CONTRACT_IMPLEMENTATION_DIFF.md`, "Assembly boundary and rollback"; `CONTRACT-VERSION-DIFF.md` §8 records Store schema, frozen contracts/export and migrations as unchanged). In practice: keep `AGENT_P2_V3_CANDIDATE_ENABLED` false by default, and if it was enabled, clear the switch and keep the pinned manifest for audit rather than rewriting in-flight bindings.
5. **Acceptance evidence for whatever is being accepted.** This document records the decisions and the current wiring only; it makes no model-quality, pass-rate or stage-acceptance claim of its own, and it does not restate any. The evidence that such a decision would have to rest on is tracked in `R2_STATUS.md` and `P2_DELIVERY_R3.md`.

## Can v3 be used as the formal baseline now?

**No.** The profile is default-off, its adoption is undecided, its extra read operations and continuation have no T1 mapping, and no decision record exists that would make it the baseline. It may be enabled and used only as the disabled, opt-in engineering candidate described above, under its own pinned manifest. The frozen v1 contracts remain the baseline.

## query-zero evidence semantics — ruling (2026-10-19)

**Decision: the frozen T1 protocol v1.1.0 typed query evidence is the single approved definition of "empty result evidence". The v3 candidate's `query_zero_classification` is NOT adopted as protocol.**

This closes the gap between P2 and T1 (RBR01), which had been left as "semantically identical but not the same artifact".

What the ruling means concretely:

1. **Authority.** RBR01, and any other claim of the form "this empty result is complete and verifiable", binds to the frozen T1 v1.1.0 typed query evidence and its trusted renderer. No P2 v3 artifact is required or sufficient for such a claim.
2. **The v3 field stays where it is, but carries no authority.** `query_zero_classification` remains an internal field of the candidate profile's DTOs and its validator (`agent/app/p2_read_contracts_v3.py:741`, enforced at `agent/app/p2_event_contracts_v3.py:910-948`). It is enforced only *inside* the candidate. It is not part of any approved protocol, it is not a T1-mappable field, and **no P2 or T1 document may cite it as the protocol's zero-result classification**.
3. **Semantic alignment is intentional but carries no transfer of authority.** The two enumerate the same distinction (a true backend zero versus rows returned then filtered to zero — T1 rows 21/24 versus row 22). That alignment means a future adoption proposal would be cheap to write; it does **not** mean the candidate field is already the protocol.
4. **Adoption, if ever wanted, is a separate decision.** It would require: a new protocol version carrying the field, a new T1 freeze with its own manifest/receipt, a preregistration impact statement, a root verdict, and T1 re-authorization of any affected dataset split. Until then the answer to "which one do we bind?" is v1.1, unconditionally.
5. **This ruling changes no code.** The candidate field, its validator and the v3 DTO are untouched; what changes is the claim made about them.

Cross-references: [baseline calibration](P2_BASELINE_CALIBRATION_R1.md) §6, [delivery status R4](P2_DELIVERY_R4.md).
