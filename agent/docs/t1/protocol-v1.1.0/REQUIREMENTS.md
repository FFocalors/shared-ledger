# Protocol freeze requirements matrix

The machine-readable source of truth is [REQUIREMENTS.json](REQUIREMENTS.json). Root reviewed every requirement as **PASS_OFFLINE_REQUIREMENT_REVIEW**. This scope is offline source/schema/export acceptance; it does not mean live backend acceptance, T1 data admission, human review, or training authorization. Final repository-freeze approval is determined only by a separate external SHA-bound receipt that binds the final repository manifest. Its hash is not embedded here, avoiding a self-reference loop; `root_approved=false` in a manifest is part of that design.

| ID | Offline requirement reviewed | Root status |
|---|---|---|
| PF-01 | Full API 1.0 / semantic, operations, trajectory 1.1 / execution-key 1 tuple; reject missing, mixed, or unknown versions. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-02 | Four semantics, six operations, CAP01–CAP17, with execution and external writes disabled. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-03 | Preserve original Unicode input value, separate typed observations, and exclude appended teacher-forcing hints. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-04 | Keep query citations distinct from facts and policy; v1 rejects the new query token. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-05 | Bind owner, turn, selected scope, generation, compare-and-swap revision, and freshness epoch. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-06 | Bind operation and normalized criteria to backend criteria and post-filter stages. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-07 | Bind actual result body, source identity/time/version, context, and financial snapshot. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-08 | Recompute exact matched facts and counts from the complete result. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-09 | Check pagination continuity, stable total, unique rows, and source-version fence. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-10 | Distinguish complete backend-zero from post-filter-zero. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-11 | Partial, unknown, truncated, errored, or overflowed results cannot prove no match. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-12 | Keep the synthetic source allowlist from claiming a real backend. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-13 | Use typed entity/fact/result/query references and keep private UUIDs out of model projection. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-14 | Fail closed on stale query state, restart/resume mismatch, scope/source change, or generation change; allow independently current queries. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-15 | Prevent query/fact/policy citations from authorizing arbitrary financial claims. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-16 | Prevent business queries from falling back to source-free conversation without trusted non-business intent. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-17 | Version causal trajectory and adaptation; exclude future evidence and require fresh artifacts for conversion. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-18 | Preserve v1 Decimal, conservation, scope, lock, permission, and proposal guards; keep live backend acceptance separate. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-19 | Validate ten Draft 2020-12 schemas with Pydantic cross-field/private checks. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-20 | Verify deterministic write/check, drift detection, unknown-file rejection, and immutable archived inputs. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-21 | Keep old API disabled and do not upgrade old proposal or execution identities. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-22 | Exercise synthetic positives and negatives for read operations, semantics, and causal traces. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-23 | Preserve old sources and candidates; report the observed parallel P2 baseline drift without attribution or restoration. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-24 | Separate offline protocol review from data admission, human review, training, and P2/model acceptance. | PASS_OFFLINE_REQUIREMENT_REVIEW |
| PF-25 | Bind root's independent requirement review to exact source/schema/test/export evidence. | PASS_OFFLINE_REQUIREMENT_REVIEW |

The root review report binds all 25 requirement assessments to the exact nine source hashes. The pre-freeze report records 22 package tests, 46 independent probes, ten schemas, five typed examples, and deterministic scratch export checks. An independent audit also verified source boundaries and the export mechanism against the then-current pending-doc scratch. See [ROOT_REVIEW.md](ROOT_REVIEW.md), [RESULTS.md](evidence/RESULTS.md), and [SOURCE-INPUTS.json](evidence/SOURCE-INPUTS.json) for hashes and scope limits.

Final repository-freeze approval is determined by the external SHA-bound receipt at `D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/ROOT-FREEZE-APPROVAL.json`. It must bind the final repository manifest hash. Its hash is not embedded in these frozen documents, avoiding a self-reference loop. The manifest's `root_approved=false` field is part of this design; only the external receipt determines the final approval.
