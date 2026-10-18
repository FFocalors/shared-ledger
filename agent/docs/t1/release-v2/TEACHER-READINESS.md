# T1 Teacher visible-text readiness

## Corrected interpretation, 2026-10-11 (Asia/Shanghai)

**Current v1 text-readiness conclusion: `QUARANTINED_EVALUATOR_DEFECT` / `TEACHER_TEXT_READINESS_INCONCLUSIVE`.** The earlier statement that the Teacher's original visible completion failed strict JSON is not supported by the saved evidence. Inspection of the frozen v1 runner shows that `post_once` passed the full visible completion to `redact_error`, whose last operation unconditionally returned `result[:400]`. The strict JSON parser then saw that shortened value. Its persisted 400-character length and `credential_redaction_applied_to_visible_content=true` therefore do not prove that an exact credential or token pattern was present, and the parse failure does not establish that the original completion was malformed.

A pure offline reproduction used only synthetic data: a valid 569-character three-case JSON object with each visible text 78 characters parsed before truncation and failed parsing after the old 400-character slice. This demonstrates the evaluator defect; it says nothing about the unavailable Teacher completion. The v1 raw response was never saved, so its original text cannot be reconstructed. The v1 preregistration, runner, request, and run manifest remain unchanged. No additional request was made for this correction.

Root review of the v1 evaluator defect is recorded at [evidence/ROOT_REVIEW.json](../../../evaluation/t1_teacher_readiness/evidence/ROOT_REVIEW.json). The synthetic reproduction and isolated v2 evaluator source/tests are in [t1_teacher_readiness_v2](../../../evaluation/t1_teacher_readiness_v2/runner.py); root reviewed the v2 source before its separate one-request check. The v2 candidate text evidence is summarized below for root and human review.

## Separate v2 synthetic text check (2026-10-11, Asia/Shanghai)

After root approved the isolated v2 runner and its 17 fake-only tests, one preregistered request was sent. It returned HTTP 200 in 5.75 seconds with `finish_reason=stop`; usage was 383 prompt, 1,134 completion, and 1,517 total tokens. The provider-returned model label was `deepseek-v4.1-flash` and matched the configured label as response metadata only. Strict JSON parsing was performed on the original in-memory completion before any text persistence. The three IDs, fixed conclusions, length limits, and no-completed-write check passed. No tool call was returned.

Root has approved the limited result as `APPROVED_LIMITED_THREE_CASE_TEXT_AVAILABILITY`. Root independently rechecked the four source hashes, preregistration/manifest bindings, request and manifest hashes, candidate text hashes, and all 17 fake tests. Root also reviewed the three cases semantically: all 3 passed. Human semantic review remains pending.

The three short texts reviewed by root are:

| Synthetic case | Candidate visible text | Characters | SHA-256 |
|---|---|---:|---|
| `activity-meadow-prepay` | “草地野餐”为普通 Activity，不支持预存，无法先存 60 元后抵扣。 | 38 | `677e8d6ce9914cc9b7191a644bb6e9477b0c7409c94b534f2ff2a8051e7309b6` |
| `expense-tea-84-two-payers` | 可准备创建 84 元茶点支出：甲付 52 元、乙付 32 元，甲/乙/丙等额分摊；尚未创建。 | 46 | `47a165ab00fa54482c0c670d4478858be737fffa8652068445f39974efe7e980` |
| `expense-locked-memo` | 财务字段已锁定；可准备将备注从“用品”改为“文件夹”，暂未修改。 | 32 | `3866eebf24e27a4f3d13a6ab22e3953289cb8d0ae94c01633e9eac22353ab078` |

This establishes only bounded transport plus strict-schema/short-text availability for these three synthetic cases. It is not a Teacher data-quality pass. Human semantic review remains pending; Student quality remains deferred; these candidates are not training data. No business data, Student model, GPU, database, train/validation/sealed data, or raw response was used or saved; hidden reasoning content was not saved. The single-request preregistration is `fe7997670342b9b8a19bf0ef49ec5b854a2249054e570b787c1fc654d0e82511`. The D-drive evidence directory contains only `request.json` and `run_manifest.json`: `D:/AI/runs/shared-ledger/t1-teacher-readiness-v2-20261011/`. Request SHA-256: `238ce566518cb33cd9378a595eed0bb4d2e3cb225bf7226029e6b3e942001cec`; manifest SHA-256: `acaae39eb78dd60ed4c30da003f61d460576360f8fe5f7ee9632641b66a9b170`.

The v2 source and 17-test suite hashes frozen before the request are recorded in the preregistration; root's limited approval is recorded in [evidence/ROOT_REVIEW.json](../../../evaluation/t1_teacher_readiness_v2/evidence/ROOT_REVIEW.json). This v2 result does not alter the separate v1 `QUARANTINED_EVALUATOR_DEFECT` / `TEACHER_TEXT_READINESS_INCONCLUSIVE` finding.

## Historical v1 transport record (retained, interpretation superseded)

The single v1 request reached the configured endpoint and returned HTTP 200. The fields below remain as recorded transport metadata; they do not establish visible-text validity or Teacher data quality.

| Observation | Recorded value |
|---|---|
| HTTP / elapsed | 200 / 11.687 s |
| Provider-returned model label | `deepseek-v4.1-flash` (metadata only; not independent identity proof) |
| Finish reason | `stop` |
| Usage | 457 prompt / 1,422 completion / 1,879 total tokens |
| Response request ID | `chatcmpl-3f9819260107428192e7c7aebe1a64f5` |
| Post-sanitizer completion length / SHA-256 | 400 characters / `d139f6cfb8b6b9a9b3be38735bcfdf7a8b24921ddec5aa2cc9af6bf9a14b92cb` |
| Old parser result | `false` on the 400-character truncated value; original strict-JSON status is inconclusive |
| Old redaction flag | `true`; the truncation itself changes any completion longer than 400 characters, so the flag is not evidence of a credential match |
| Hidden reasoning field | `reasoning_content` field was present; its value was not saved or displayed |
| Candidate | None admitted; v1 output remains quarantined and is not training data |

The v1 request used the existing OpenCode Go configuration read into memory only, provider `opencode`, model `deepseek-v4.1-flash`, and route `https://opencode.ai/zen/go/v1/chat/completions`. It used a probe-specific User-Agent and one stable `x-opencode-session`, with `max_tokens=2048`, a 60-second timeout, a 256,000-byte response cap, and no retry or fallback. The credential value was not written, printed, or hashed. The prompt contained only three synthetic states: ordinary Activity prepayment refusal; an 84-unit expense with two balanced payers and equal split; and a locked Expense memo-only presentation change. No business data, Student model, GPU, database, or sealed dataset was used.

The 400-character SHA identifies the old post-sanitization value, not a raw response artifact. The response envelope and hidden reasoning value were not saved. The prior manifest remains at `D:/AI/runs/shared-ledger/t1-teacher-readiness-20261011/`; its recorded hashes are request `eda1fee97f5907368fd05471ea5ed1cdfa7e34f61dd53fbf3a9ec9019a84ffae` and manifest `959247cc5dc1efbcadc19f94730c90726f160789064fcb503a84b5ccdbfd2c84`. The preregistration SHA-256 is `681a7657e893ee6457991350c4b8b3deb5d14c3423993d5455e976548b23dcbb`, and the frozen v1 runner SHA-256 is `f66bdf94a2f4f65e52f82579e52612834f76ad20dc16652cd704f9f7c74ebad5`.

**Assessment remains limited:** Teacher transport availability was shown by the earlier protocol canary, but v1 visible-text readiness is inconclusive due to this evaluator defect. Teacher data quality has not been assessed. Student model quality remains deferred. Human semantic review is pending; the v1 output is not training-eligible.
