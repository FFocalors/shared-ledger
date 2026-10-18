# Protocol build and verification results

Status: **APPROVED_OFFLINE_SOURCE_SCHEMA_AND_EXPORT_REVIEW**. Root approved the exact offline source/schema/export requirements. Final repository-freeze approval is determined by a separate external SHA-bound receipt that must bind the final repository manifest; its hash is not embedded in these frozen documents, avoiding a self-reference loop. The manifest's `root_approved=false` field is part of this design. These results do not approve T1 data admission, human review, live backend behavior, or training.

| Check | Result | Evidence and scope |
|---|---|---|
| Focused v1.1 package tests | **22 passed, 1.51s** | Root pre-freeze command: `agent/.venv/Scripts/python.exe -m pytest agent/evaluation/t1_protocol_v1_1/tests -q -p no:cacheprovider --basetemp=D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/prefreeze-20261012T004838745457/pytest-temp`. |
| Independent root protocol probes | **46 passed, 0 failed** | Exact final source hashes were stable before/after. Synthetic offline probes only; no model or held-out semantics. |
| Generated schemas and examples | **10 schemas and 5 typed examples passed** | Draft 2020-12 validation plus Pydantic cross-field/private checks. |
| Explicit adaptation gates | **Positive case passed; four false/missing-gate cases rejected** | Conversion, new source freeze, replay/review, and new split cannot be claimed implicitly. |
| D-only deterministic export | **36 files; write/check passed** | Repeat write preserved bytes. Unknown output and archived-source-byte drift were rejected. Restoring the exact archived bytes restored a passing check. This was a scratch candidate, not the final repository capture. |
| Root PF-01–PF-25 review | **25/25 PASS_OFFLINE_REQUIREMENT_REVIEW** | Exact evidence is bound by the root matrix; individual assessments are in [REQUIREMENTS.json](../REQUIREMENTS.json). |
| Independent source/export audit | **17 export checks passed** | Independently matched the approved source hashes, ran 22 package tests, validated ten schemas/five examples, and rejected source/page/rendering/adaptation/causal mutations. Its D-only scratch used the earlier pending-document snapshot and is not the final repository candidate. |
| Protected-baseline comparison | **PASS_WITH_OBSERVED_PARALLEL_P2_DRIFT** | Original baseline: 149/154 matched, five observed P2-path changes. Resumed baseline: 152/154 matched, two observed P2 paths. See [ROOT_REVIEW.md](../ROOT_REVIEW.md). |
| Immutable-v1 regression reference | **11 passed, 2.49s** | Separate test of the unchanged v1 contract only; not part of the v1.1 package count or full T1 acceptance. |

## Bound report identities

Root's requirement matrix is `D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/ROOT-PF-REVIEW.json`, SHA-256 `22bc7188963daa58b9c7a1beb8b5f828742a65aa51f0bb486184a069d16dc712`. The root pre-freeze report is `D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/prefreeze-20261012T004838745457/ROOT-PREFREEZE-REVIEW.json`, SHA-256 `fb46818230b82c1d5c1a55a34e36c21f3c2110a079d06d4dd26ba9b704bf294b`.

The 46-probe result is `D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/root-probes-results-20261012T004842037763.json`, SHA-256 `01a877db99750aa48f967d0aac15bf35dc6d566d38e67cd32cc9f6e24dd17ebd`. The independent audit report is `D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/independent-audit-20261012/final-independent-audit-20261012.md`, SHA-256 `63500edfa41d2c2f7fa6686453d6b90bbd7ecc5c8510230749b46fb777da9ee1`; its export receipt SHA-256 is `e9dd0e2fb0de1de0bc7fbc5e275a1e582516056822cc3ad2480e93516042f03f`. The final nine source hashes and all ten schema hashes are in [SOURCE-INPUTS.json](SOURCE-INPUTS.json).

The D-only export scratch manifest SHA-256 is `f43344f13e1c80b36acef0e2ded66239dae843a5356f669704a0ac33a0990d11`; its archive index SHA-256 is `78eb7090084f39b46be70014dd8180588b225a486fd7533e4e1517e1df6e6f22`. Executor preview probe-log SHA-256 is `9ac5a86158d568d9f8f05890b429dd17952a4a7da721067f5ae3a06449f00e39`. These identify scratch evidence only.

Root's preservation report is `D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/preservation-20261012T003538035255.json`, SHA-256 `87530bd62c3aefd0b99df87d5abb58036093851b098583cf418ecf90d055c95e`. The original 154-file comparison found 149 matches and five observed P2 changes; the resumed comparison found 152 matches and two changed paths (`agent/app/p2_runtime.py` and `agent/docs/p2/R2_CLOSED_LOOP_DIAGNOSTIC.md`). The runtime input projection was reported unchanged; R2 remains design-only. No authorship was inferred and neither path was restored.

The separate immutable-v1 regression used Python 3.12.0, Pydantic 2.13.4, jsonschema 4.25.1, and pytest 8.4.2 with `agent/.venv/Scripts/python.exe -m pytest agent/tests/test_protocol_contracts.py -q -p no:cacheprovider`. It is only a v1 contract baseline.

## Exclusions

No model or GPU was run, production was not enabled, and no P2 API, Supabase, Auth, or RLS call was made. The offline tests and probes do not establish real source authenticity, live authorization, archive/sub-activity membership, real write preflight, P2 calibration, or model quality. Training eligibility remains false; genuine human review, P2 calibration, and T2 authorization remain pending. Student evaluation is deferred under the user's instruction. The separate bounded P2 17-call diagnostic is `FAIL_SEMANTIC_DIAGNOSTIC`, while R2 remains design-only.
