# T1 release-v2 candidate and preparation record

**Status (2026-10-11):** the 393-row candidate passed the collection gate and root near-pair technical review. Root completed the final review of the 34-row train-only packet: business text, amounts, and scope passed 34/34; output provenance passed 31/34; rows 21/22/24 require data revision. Overall decision: REQUIRES_TRAINING_DATA_REVISION. See [root business review](ROOT-BUSINESS-REVIEW.md) and [P2 calibration findings](P2-CALIBRATION-REVIEW-FINDINGS.md). Genuine human receipt, P2 calibration, and explicit T2 authorization remain pending; training_eligible=false.

## Candidate and gate result

The release output is `D:\AI\runs\shared-ledger\t1-release-v2-20261011\candidate-v2` with 393 rows: 135 train, 129 validation, and 129 sealed. All 18 operation-by-split independent-family counts are 20. The 24 boundary rows are explicitly excluded from the positive-family floor. Strict schema, independent Gold, and deterministic replay checks passed for all 393 rows; exact duplicate and state-leak counts are zero. The collection checker reported no blocking issues or unresolved pair findings. This is a dataset-collection and technical-review result, not a model-quality or live-backend acceptance result.

Root completed technical review of 4,984 near-pair findings against visible business structure and boundary-request structure. The recorded dispositions are 4,908 visible-business-structure distinctions, 20 directed-debt-graph distinctions, 55 create-versus-update boundary distinctions, and 1 unauthorized-request-structure boundary distinction. There are zero unresolved pair findings. These are technical dispositions, not human semantic review. The previously pending 26-pair set concerned only the 24-case boundary subset; it was never the full candidate's near-pair total.

The 72 files in `baselineSnapshot` are byte-preserved. Separately, root completed an exhaustive exact canonical graph-signature review of 72 independent small-graph inputs and 24 relabeling pairs. The graph review is not a review of the 72 source files. The Teacher source archive contains 13 files and 14 bindings; root found zero mismatches.

## Frozen and written artifact identities

The immutable generation source freeze contains 47 files. Its source-manifest identity is `f92f5074d898ba25922bbd609e1c2fed2f82780eb4b03427c9317dacf03cbfc3`; the source-manifest artifact file is under `review/final-preparation-20261011-attempt-02/source-manifest.json` in the D-drive run directory. The source freeze, exact copied inputs, and review records remain archived under `D:\AI\runs\shared-ledger\t1-release-v2-20261011\review\`. The status-only guide update described below occurred after candidate writing: it does not mutate this immutable manifest or the candidate. Any future preparation must create a fresh source freeze and receipt.

| Artifact | SHA-256 / identity |
|---|---|
| Source manifest identity | `f92f5074d898ba25922bbd609e1c2fed2f82780eb4b03427c9317dacf03cbfc3` |
| Archived `source-manifest.json` file | `d686bdf77a67c80701600d4a90a4dca1222edd3910bc667522472dda820d4b8f` |
| Collection | `382dda0a21ab42d12f11df72794e1c8cece866cb0b557a8b592d0a1268aa1c86` |
| Checker report | `0fa561067849b9233ddbe23245aaa8710a34e0c9d5d934bf6ecb0f3e7339dd21` |
| Creation manifest | `08bebb9c96101d6be09c4d5273d4ff7b019c4608c8057aeac64b661f3e0ea820` |
| Release write metadata | `8316a5bfcc358a1fbfb76e4400972ab03eddf4085914b61d05117c045f1b3ba2` |
| Root preparation receipt | `f25401a9a4680781a13ef5cee2c94950aa2798f57d2627b0f6f1bb018afdf68e` |
| Root pair-review details | `684f97232277ff6eb7c0c111c3bdb921fe415407f5394dd450cf9205b3c4db08` |
| Root publication/preservation audit | `7d5f87b3deb6b90c3fc7ea3164cb44f1783ca4df2a90d3ce11cc991940c86274` |
| Root sealed-write receipt | `0102577b3055dcd8a49b53db1590ebda03633b7def828f336ef23acc5146e044` |

The creation manifest binds 135 train rows (payload SHA-256 `be8795a68e9d739ecb72360d66b223accc428b735eab1d65cb2f6e71b6dc7247`), 129 validation rows (`5e4c4faa0318ad8ceec79b5ac0f9e1aef679d5ad9caa8e55b767a13e0acfd903`), and 129 sealed rows (`1501d8931324fcba36d10e6c91c0f16f24dd2347497d7dd7c5eac0527f37f9db`). Sealed was written last under the one-shot root write receipt. The preservation audit independently confirmed split hashes and line counts; no sealed semantic readback was performed.

## Human review and remaining admission gates

A 34-row, train-only packet is at D:\AI\runs\shared-ledger\t1-release-v2-20261011\review\human-review-v2\train-review.html. Its packet identity is 899f647ed5cd8749bb43d8f7cdca0e442579309682890da535a038527ae41e94; HTML file SHA-256 is da26c47aa4a8bd6da3d1ddd1ca57b5cb776e313583cb1365d11798f72d7cd92b; selection SHA-256 is 22c89fb2419c53d5234c8d619d0603fcfad77c49b10da5e2427b198073f15ab0; packet-manifest SHA-256 is 5ed6f7254e559b0d12de7c4d9707c014af83c93a88683cfa427206e7f4c127da. Root technical packet-integrity review verified all 34 row hashes and HTML anchors (SHA-256 d09f090cd0ffcff8a0a1013fe1d2633c8b29b99a4e4bd9cf33aad38dbe690eb0); this proves integrity/coverage, not semantic approval. Root business review report SHA-256 77ce270ee836d889f119008348caaa702781e667a61a44e4964b84e826c9f7ad found all 34 business texts, amounts, and scopes correct, with 31/34 output provenance checks passing and rows 21/22/24 requiring revision. Rows 21/24 are true tool-empty results. Row 22 has five real read results followed by a title post-filter that returns empty, so the filter and result completeness must be bound. Current P1 citation kinds do not support read-result citations; this is an inherited known contract gap, not a new regression. Typed query citation requires a versioned protocol change, or an equivalent trusted versioned renderer; do not silently change the canonical freeze or fabricate Fact/Policy/citations. Keep the persisted packet unchanged. Root report and row notes are in [ROOT-BUSINESS-REVIEW.md](ROOT-BUSINESS-REVIEW.md).

- P2 baseline calibration remains pending. RBR02–04 also need follow-up: 33/34 contexts contain manually added already-read/consumed hints; rows 19/20/26 use bare expense_ref during clarification; rows 15/16/17 do not demonstrate AA minor-unit tails. RBR04 is a coverage gap, not an AA algorithm error. See [P2 calibration findings](P2-CALIBRATION-REVIEW-FINDINGS.md); do not change the original read-only task or app/tests as part of this status record.
- Explicit T2 authorization remains pending. This record does not authorize opening sealed examples for model evaluation.
- Student evaluation remains `NOT_TESTED_USER_DEFERRED` / `DEFERRED_NOT_TESTED`.
- Teacher's latest v2 check is limited to three synthetic short-text cases, reviewed 3/3 by root. Teacher data quality remains `NOT_ASSESSED`; this is not training data.
- Synthetic replay is not live backend acceptance. Backend acceptance remains `NOT_TESTED_SIMULATED_REPLAY_ONLY`, and real Agent CAP coverage remains 0/17.

Until training data is revised, genuine human receipt, P2 baseline calibration, and explicit T2 authorization are complete, the formal value remains training_eligible=false. The root report is complete, but human_review_pending=true and human_reviewed=false remain unchanged.

## Binding and replay requirements

Each candidate binds its fixture, independent state family, original user request, policy evidence, and independent gold separately and explicitly. Missing totals remain missing; never infer a total from listed allocations. Legacy boundary cases use a large child activity with its root parent. Explicit selection of the full participant list is valid. A read floor must be present and actually visible to the model. Teacher-forced contexts and results do not count as model-driven closed-loop success.

Simulated replay checks deterministic harness behavior against synthetic fixtures. It is not a real Backend result, live business acceptance, or proof that Agent CAPs work against Supabase. Keep those engineering and model-quality conclusions separate.

## Teacher evidence boundary

The old Teacher v1 visible-text result is quarantined because its evaluator truncated completions at 400 characters before strict JSON parsing. That is an evaluator defect, not evidence that the original completion was malformed. The original v1 response was not retained and cannot be reconstructed; do not attempt to recreate it or reuse it as candidate data. Keep the v1 preregistration and evidence immutable. The separate v2 three-case check establishes limited text availability and those cases' semantics only, not Teacher dataset quality.
