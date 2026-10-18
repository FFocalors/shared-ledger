# Independent root review

Status: **APPROVED_OFFLINE_SOURCE_SCHEMA_AND_EXPORT_REVIEW**. Root marked PF-01 through PF-25 as `PASS_OFFLINE_REQUIREMENT_REVIEW`, based on exact source, schema, test, and export evidence. Final repository-freeze approval is determined by a separate external SHA-bound root receipt at the path below, which must bind the final repository manifest hash. The receipt hash is intentionally not embedded in these frozen documents, avoiding a self-reference loop. A manifest field of `root_approved=false` is part of this external-approval design. This review does not approve T1 data admission or training.

## Bound review evidence

The requirement-by-requirement review is `D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/ROOT-PF-REVIEW.json`, SHA-256 `22bc7188963daa58b9c7a1beb8b5f828742a65aa51f0bb486184a069d16dc712`. The root pre-freeze review is `D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/prefreeze-20261012T004838745457/ROOT-PREFREEZE-REVIEW.json`, SHA-256 `fb46818230b82c1d5c1a55a34e36c21f3c2110a079d06d4dd26ba9b704bf294b`.

The pre-freeze report records:

- 22/22 focused v1.1 package tests passed in 1.51 seconds.
- 46/46 independent root probes passed with stable source hashes; the probe artifact is `D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/root-probes-results-20261012T004842037763.json`, SHA-256 `01a877db99750aa48f967d0aac15bf35dc6d566d38e67cd32cc9f6e24dd17ebd`.
- Ten Draft 2020-12 schemas and five typed examples validated.
- All four explicit adaptation-gate negatives rejected; the positive adaptation example passed.
- A 36-file D-only scratch export passed write and check. Repeat write preserved bytes; unknown-output and archived-source-byte mutations were rejected; after restoring the exact archived bytes, check passed. The scratch manifest SHA-256 is `f43344f13e1c80b36acef0e2ded66239dae843a5356f669704a0ac33a0990d11`, and the archive index SHA-256 is `78eb7090084f39b46be70014dd8180588b225a486fd7533e4e1517e1df6e6f22`.

The executor's separate D-only preview attempt02 also passed write/check, repeated-write identity, mutation rejection, and restoration checks. Its probe-log SHA-256 is `9ac5a86158d568d9f8f05890b429dd17952a4a7da721067f5ae3a06449f00e39`. The preview and root pre-freeze evidence are offline artifacts; they are not the final repository capture.

The independent audit receipt is `D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/independent-audit-20261012/final-independent-audit-20261012.md`, SHA-256 `63500edfa41d2c2f7fa6686453d6b90bbd7ecc5c8510230749b46fb777da9ee1`; its machine-readable export receipt is `export-audit-final-results.json`, SHA-256 `e9dd0e2fb0de1de0bc7fbc5e275a1e582516056822cc3ad2480e93516042f03f`. The audit independently matched the stable source hashes, ran 22 package tests, validated ten schemas and five typed examples, rejected source/page/rendering/adaptation/causal mutations, and passed 17 export-mechanism checks. It supports the offline review only. Its D-only scratch captured the previous pending-document snapshot, so it is not the final repository candidate.

The exact nine approved source SHA-256 values, ten schema SHA-256 values, report identities, and scope exclusions are recorded in [SOURCE-INPUTS.json](evidence/SOURCE-INPUTS.json). The 25 individual root assessments and evidence paths are in [REQUIREMENTS.json](REQUIREMENTS.json).

## Preservation and review limits

The preservation report is `D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/preservation-20261012T003538035255.json`, SHA-256 `87530bd62c3aefd0b99df87d5abb58036093851b098583cf418ecf90d055c95e`, status `PASS_WITH_OBSERVED_PARALLEL_P2_DRIFT`. Against the original 154-file baseline, 149 matched and five P2-path changes were observed. Against the resumed 154-file baseline, 152 matched and two paths differed: `agent/app/p2_runtime.py` and `agent/docs/p2/R2_CLOSED_LOOP_DIAGNOSTIC.md`. Root reports the runtime's latest input projection is unchanged and R2 remains design-only. Neither path was restored or attributed. These are separate baseline comparisons, not a claim that either baseline was wholly unchanged.

The same preservation review reports that old candidate split raw hashes and row counts, creation/checker records, the human packet, and pending receipt matched. Protocol probes did not read held-out semantics; the preservation comparison used raw hashes/counts. No model was run and production remained disabled.

The offline private owner/turn/scope/revision and financial-fence checks establish consistency among supplied records. They do not prove cryptographic provenance, live backend authorization, Auth/RLS, archive or sub-activity rules, a real write preflight, or live P2 behavior. The old v1 structural Decimal, conservation, scope, lock, permission, and proposal checks remain separate from current-backend acceptance.

The 34-row root review of the old train-only packet is not a genuine human receipt. Business text, amounts, and scope were correct in all rows; provenance passed in 31 and requires repair in rows 21, 22, and 24. The packet also needs four quality actions before data can be reconsidered: repair those three query-result provenance cases; remove appended “already read and consumed” hints from 33 contexts and match P2-visible context; use returned participant or expense title/date/amount instead of bare internal expense references in ambiguous clarifications; and add non-integral-cent AA/multi-person small-amount cases.

Training eligibility remains false. Genuine human review, P2 calibration, and T2 authorization remain pending. Student evaluation is deferred under the user's instruction; GPU evaluation remains deferred. The bounded P2 17-call diagnostic is `FAIL_SEMANTIC_DIAGNOSTIC`, and R2 is design-only in the current hash-bound evidence.

## Separate repository-freeze approval

Final repository-freeze approval is determined by the external SHA-bound receipt at `D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/ROOT-FREEZE-APPROVAL.json`. It must bind the final repository manifest hash. Its hash is not embedded here or in the other frozen documents, preventing a self-reference loop. The manifest's `root_approved=false` field is part of the mechanism; the separate receipt determines approval. The D-only scratch candidate is not a substitute for this receipt.

Related records: [REQUIREMENTS.md](REQUIREMENTS.md), [RESULTS.md](evidence/RESULTS.md), and [SOURCE-INPUTS.json](evidence/SOURCE-INPUTS.json).
