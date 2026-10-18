# T1 release-v2 candidate and review status

**Status (2026-10-11):** The 393-row candidate passed collection and near-pair technical gates, but formal T1 admission is incomplete. Root completed the 34-row train-only business review: business text, amounts, and scope passed 34/34; output provenance passed 31/34, with rows 21/22/24 requiring data revision. Overall decision: REQUIRES_TRAINING_DATA_REVISION. Genuine human receipt remains pending; P2 calibration and explicit T2 authorization are pending; training_eligible=false.

The candidate contains 135 train, 129 validation, and 129 sealed rows. Strict schema, independent Gold, and deterministic replay checks passed for all 393 rows. All 18 operation-by-split family counts are 20; 24 boundary rows are excluded from the positive-family floor. Exact duplicates, state leaks, blocking issues, and unresolved pair findings are zero. Root technically reviewed all 4,984 near-pair findings. These results establish collection integrity, not model quality or live backend acceptance.

The source-manifest identity is f92f5074d898ba25922bbd609e1c2fed2f82780eb4b03427c9317dacf03cbfc3; collection identity is 382dda0a21ab42d12f11df72794e1c8cece866cb0b557a8b592d0a1268aa1c86; creation manifest SHA-256 is 08bebb9c96101d6be09c4d5273d4ff7b019c4608c8057aeac64b661f3e0ea820; release-write metadata SHA-256 is 8316a5bfcc358a1fbfb76e4400972ab03eddf4085914b61d05117c045f1b3ba2. The candidate lives at D:\AI\runs\shared-ledger\t1-release-v2-20261011\candidate-v2; sealed was written last under the one-shot root receipt. No sealed semantic readback was performed.

## Root business review

The selected 34-row train-only packet passed technical integrity checks: row hashes, HTML anchors, and coverage verified. Root's final item-by-item report says all 34 business texts, amounts, and scopes are correct; 31/34 outputs have passing provenance. Rows 21/24 are true tool-empty results. Row 22 has five real read results, then a title post-filter that returns empty; its evidence must bind that filter and prove result completeness. The existing P1 citation kinds do not support a read-result citation. This is an inherited known contract gap, not a new business or model regression; resolving typed query evidence requires a versioned protocol change or an equivalent trusted, versioned renderer. Do not silently change the canonical freeze or fabricate a Fact, Policy, or mismatched citation.

The review also identifies three training-quality follow-ups: RBR02, 33/34 contexts manually say results were already read and consumed; RBR03, rows 19/20/26 use bare expense_ref values in clarification; and RBR04, rows 15/16/17 do not cover AA minor-unit tails because all shown equal shares can be expressed in whole cents. RBR04 is a coverage gap, not evidence of an AA algorithm defect. The 12 monetary proposals passed independent total and allowlist checks.

- [Root business review](ROOT-BUSINESS-REVIEW.md) includes all 34 root notes, the three provenance rows, four quality findings, scope, and evidence hashes.
- [P2 calibration findings](P2-CALIBRATION-REVIEW-FINDINGS.md) is a concise handoff for typed empty-result evidence and the other quality findings.
- Root report SHA-256: 77ce270ee836d889f119008348caaa702781e667a61a44e4964b84e826c9f7ad.

## Remaining admission gates

- Genuine human receipt remains pending: human_review_pending=true and human_reviewed=false. The user's request delegated the item review to root; it does not waive the formal gate.
- P2 baseline calibration and resolution of RBR01–RBR04 remain pending. Any canonical protocol change needs a new version and freeze.
- Explicit T2 authorization remains pending. This record does not authorize opening sealed examples for model evaluation.
- Student evaluation remains NOT_TESTED_USER_DEFERRED / DEFERRED_NOT_TESTED.
- Teacher's latest v2 check covers one request and three synthetic short-text cases, reviewed 3/3 by root. Teacher data quality remains NOT_ASSESSED.
- Synthetic replay is not live backend acceptance. Backend acceptance remains NOT_TESTED_SIMULATED_REPLAY_ONLY, and real Agent CAP coverage remains 0/17.
- Until data revision, genuine human review, P2 baseline calibration, and explicit T2 authorization are complete, training_eligible remains false. The old t1-synth-1.0.1 diagnostic freeze remains a separate immutable 111-row artifact.

The 72 files in baselineSnapshot were byte-preserved. Separately, root reviewed exact canonical graph signatures for 72 independent small-graph inputs and 24 relabeling pairs; this is not a review of the 72 source files. The v1 diagnostic freeze remains separate.

This guide was updated in the working tree after the v2 candidate was written. The frozen source archive and source manifest are unchanged. Any future preparation must use a fresh source freeze and receipt; do not reuse the earlier source receipt after an input change.
