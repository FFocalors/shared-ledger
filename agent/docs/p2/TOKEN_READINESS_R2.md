# R2 token readiness update

This note records the explicit local artifact preparation added after the R2 token-count preflight failed closed. It does not authorize or report model generation, and it does not replace or amend the frozen R2 candidate package at `D:\AI\runs\shared-ledger\p2\r2-final-prereg-preoutput-20261012T0048Z`.

## What changed

`LMStudioSDKTokenBudgetChecker.prepare_artifact_binding(*, timeout_seconds=30.0)` is an explicit, local-file-only readiness operation. It validates a finite timeout from 0.1 through 30 seconds, starts one monotonic deadline before waiting for the checker's artifact lock, then reuses the existing before-stat, complete SHA-256 read, after-stat, configured-size, and configured-digest checks. The in-memory binding cache is populated only after every check succeeds. It returns the verified SHA-256 and hash elapsed milliseconds. A cached call returns zero hash milliseconds; the caller should also record whole-call wall time when measuring readiness cost.

The operation does not import or call the LM Studio SDK, inspect loaded models, make HTTP requests, load a model, or generate. Production construction, health checks, and `measure()` do not call it automatically. Cache contents remain process-local and are never seeded externally.

The existing `verify_artifact_binding()` keeps its policy-configured five-second cold-hash deadline. Every normal `measure()` still has a single five-second total deadline covering artifact verification and the SDK child; the SDK call itself remains capped at five seconds. A cold 2.7 GB model artifact can therefore time out in regular measurement, as it did in the historical attempt below. The explicit preparation step lets an operator pay that local hash cost separately; it does not relax any per-measurement deadline. Later measurements still check the resolved absolute path and file stat signature against the prepared binding and fail closed if it changes.

## CPU verification

The focused CPU run used a D-drive pytest base directory and ran only `tests/test_p2_token_preparation.py` plus `tests/test_p2_token_budget.py`. Result: 22 passed, exit code 0, in 2.10 seconds. The new tests cover the regular five-second cold verification failure, the explicit 30-second preparation path using a simulated monotonic clock with a small fixture, invalid timeout values, wrong digest, before/after stat change, timeout without cache population, successful prepared measurement with a five-second helper bound, and post-preparation artifact mutation rejected before the helper starts.

This validates local admission behavior with CPU fixtures. It does not establish that any R2 request fits the loaded model context, and it is not an SDK token-count result.

## Preserved historical counter result

The earlier no-generation preflight remains preserved at:

`D:\AI\runs\shared-ledger\p2\lmstudio-r2-counter-20261012T0848Z-f08fec96414049a6966e755bc7749e55\sdk-counter-9-20261012T085744Z-4e507ada575e46179c9091da5f86f531\counter_preflight_result.json`

It reports `FAILED_CLOSED`, `error_code=counter_timeout`, `generation_endpoint_called=false`, and no successful token measurements. The cold file hash exceeded the regular five-second policy deadline before the SDK counter ran. The independent file-only hash took 14.119 seconds and matched the approved artifact SHA-256 `acfd01df6cbd3c8e1fa4dbe144f5852290689851c4f92d4ab892707d08724b34`; that separate observation does not turn the failed five-second measurement into a pass.

The frozen package manifest remains unchanged at SHA-256 `8cf72c3ed0190e3a3f94a4af2475d9bb43e539ac122d71fdcc8ab46fcfd57b2b`. Its candidate fingerprint and request fixtures describe the earlier source snapshot. This readiness change requires a new, independently hashed counter candidate record; the old candidate fingerprint is not the current source fingerprint. No request, prompt, schema, fixture, or historical result in that package is to be rewritten.

## R2 token-only follow-up

After freezing the source and focused tests, one D-drive run used the public preparation API and then attempted the nine frozen provider request bodies plus four persisted CPU-export typed bodies. Preparation verified the configured model artifact SHA-256 and completed in 6,110 ms (both measured hash cost and whole preparation wall time). The checker then attempted each of the 13 bodies once. All 13 failed closed with `counter_timeout` at 5,014–5,047 ms per case, so there are zero successful token measurements and token fit remains unknown. There were no retries, generation endpoint calls, model load/unload operations, or model outputs.

The candidate record has fingerprint `96e72c9299453213d8aaaafd58fad0ea13a07cdb292eba3b99a3a097b24dc578` and SHA-256 `68eb8ba32e5e29b17fedbc037074b3beafaa890cc3bc91b382e4f7111aecb4ba`. The result is preserved at `D:\AI\runs\shared-ledger\p2\token-readiness-counter-20261012T091438Z-0e2d0c6dbab64826a46417935b700032\counter-readiness-result.json` with SHA-256 `50fdcf35cfbd061e4d02378f61e55c3a55571ff04ff2d1e6beaf45d2bcd39cda`. Its runner, request fingerprints, per-case timeouts, and source-before/after snapshot are kept in that same directory. The 13 attempts were token counting only; they cannot call the generation endpoint and do not authorize model output. No further count attempts are implied by this record.

This remains a failed token-admission preflight. The 30-second local preparation step worked, but the five-second SDK measurement deadline did not. The counter failures do not establish that any request fits the context, and CPU tests do not establish answer quality, semantic correctness, or a complete R2 acceptance result.

## Read-only SDK stage diagnostic

After the failed 13-case run, one independently bounded metadata-only helper checked the explicit local SDK path. It completed in 7,438 ms. Importing the installed SDK took 1,233 ms; creating an explicit-origin client succeeded; the single `list_loaded_models("llm")` call took 2,797 ms and returned exactly one match for the approved model key; `get_info` took 16 ms and reported the expected model path and 2,708,804,480-byte size; `get_context_length` took 14 ms and returned 8,192. The diagnostic used no `count_tokens`, prompt template, generation, load/unload, or fallback endpoint. Its report is `D:\AI\runs\shared-ledger\p2\sdk-metadata-diagnostic-20261012T092212Z-22f4a0b6f7fb43c29b44863545f958c7\sdk-metadata-diagnostic.json`, SHA-256 `3d03faa943a359fc68a8e62635b3a8e1eee0a8c27dc589925bce2ad06e57b14d`.

These metadata timings help explain why a five-second total may be tight, but do not establish the exact cause of the token-counter timeout. No request was re-counted. The existing five-second measurement limit remains unchanged.

The event timestamps also show a 2,161 ms interval between successful explicit-client creation (`09:24:52.391123Z`) and the start of `list_loaded_models` (`09:24:54.552419Z`). The trace does not attribute that interval to a specific SDK operation, so it is recorded as an inter-stage delay rather than a measured API call. The helper's full wall time was 7,438 ms. This single metadata observation is not a latency guarantee or evidence that any token count can complete within five seconds.

After a test-only correction to assert the actual bounded helper contract (`0 < timeout <= 5s`), the focused token test run completed again with 22 passed in 1.78 seconds. Its log is `D:\AI\runs\shared-ledger\p2\token-preparation-retest-fc50b847cfa8447a8b8807867a365b1d\pytest.log`, SHA-256 `20ccac030e91eadbdf3b3b1eadd2b6a5db805182645c7a9873ffe248fdb076d7`. No production source changed in that test-only correction.
