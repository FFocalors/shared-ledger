# P2 SDK token-counter session implementation (R2)

**Status:** The implementation passed the frozen CPU verification; a separate token-only candidate is prepared for root review. No live SDK count or model generation has been run for that candidate.

## Current frozen baseline and candidate preregistration (2026-10-12)

The current implementation and session tests are bound to CPU evidence manifest `D:\AI\runs\shared-ledger\p2\sdk-session-cpu-root-20261012T1045Z-ae0cc7f775024896b3ed1246001e37c4\evidence-manifest.json` (SHA-256 `3c9eaf059971c3de37d2a3bd4d586e226d8b08904611320b67e8d0de74ea2dc1`). The manifest records 126 frozen inputs with identical before/after hashes, a passing focused suite, full agent test suite, and read-only v1 export check. The focused and full test commands did not probe a live SDK, model, Supabase, or Docker.

Current implementation SHA-256: `app/p2_token_budget.py` `a0a772be001475ee27ff9ee4289da09e3f7e45f4a855b2cc9f9edff595cc6965`. Relevant tests: `tests/test_p2_token_budget.py` `825fd50772363f35e2693c69726aac28b713684e1e268d387b2022962c68604e`, `tests/test_p2_token_preparation.py` `cc3d5d7bf3f8487203e800c088c468fb98f8ea042034d6e178f0012ffb6e4106`, and `tests/test_p2_token_session.py` `5d33776fa196b217eb000f1edffcf7a643e5944fcb1168fee6ff1aaaa41c258a`.

A fresh 13-request token-only candidate is staged at `D:\AI\runs\shared-ledger\p2\persistent-sdk-session-prereg-20261012T110711Z-568d385094044be6b84a59561ea8aa17`. Its candidate fingerprint is `efa6835acc1e429aeeae99edab33d35fb6314c34bd26128fe8bc7316e5f902e3`; package manifest SHA-256 is `74832ec076afcba97ee33377fcbdd73d4961c1f658ee6dfdb2452f7c376e9ca4`; the review-only runner text SHA-256 is `6dc18f85889e224498edae2d213558dace0790d826081551898cc24a4900b967`. The package preserves the nine frozen provider request bodies and four representative export bodies byte-for-byte. It binds the candidate to the current source/test snapshot and the fixed `t0-cp36-20261007` model/artifact, and specifies one session preparation (15-second ceiling), 13 maximum measurements (one per request; five-second total deadline each), 6144 input budget including a 512-token schema margin, 768 output cap, 8192 context, zero generations, no retry/reprepare/cold fallback, stop-on-first-failure, and up to one second of additional cleanup grace. The SDK version was read from installed `dist-info/METADATA` only; this preparation did not import or call the SDK or count tokens. The candidate remains unexecuted pending review. The earlier 13-timeout result remains historical evidence and is not retried by this candidate.

The session counter keeps one explicitly prepared LM Studio SDK client in a checker-owned helper process. It only looks up an already-loaded handle, applies the model prompt template, counts the prompt and schema separately, and repeats the loaded-model identity checks after counting. It has no load or inference path. Nothing in construction, health checks, or ordinary startup prepares the SDK session automatically.

`prepare_artifact_binding(timeout_seconds=30)` is an explicit local-file-only readiness step. It hashes the configured artifact and admits the cache only if the before/after file identity, configured size, and configured SHA-256 all match. `prepare_sdk_session(timeout_seconds=15)` then starts the SDK phase deadline, waits for the single-flight gate, closes any previous owned helper, creates a fresh session ID, and verifies the SDK version and an already-loaded model through the bound local origin. A failed explicit session preparation leaves session mode required; measurement cannot silently fall back to the cold helper.

Each measurement uses a monotonic five-second deadline covering the gate, state-lock waits, cached artifact stat checks, JSON serialization, helper pipe write/read, the SDK template/count calls, the second fresh loaded-model lookup, and final admission. It checks the configured model key, path, artifact hash and size, API origin, and context length before counting; the model path and context must still match afterward. Token counts are returned only after the parent repeats the artifact identity check and verifies the input-plus-schema-margin and output caps.

The private helper protocol binds each request to an immutable checker candidate ID, a fresh per-preparation session ID, a SHA-256 binding fingerprint, and a monotonically increasing integer request ID. Parent and child reject boolean request IDs. The child accepts one bounded JSON line per request (1 MB maximum); responses are limited to 4 KB. Prompt text, schema contents, counts, and SDK errors are not written to ordinary logs. A timeout, malformed or oversized response, identity mismatch, artifact change, helper exit, or close race fails closed.

One cleanup owner per session makes one kill/reap attempt and joins the exact pipe threads captured by the failed exchange. It records a single absolute cleanup deadline one second after cleanup begins; repeated invalidation or `close()` calls do not start another grace period. If the owned process or pipe threads remain live at that deadline, the checker records cleanup failure and refuses to start another SDK helper. Cleanup grace is separate from the measurement/prepare deadline, so it may add up to one second to a failed call. State-lock waits remain bounded by the active measure/prepare deadline; `close()` waits at most 50 ms for the state lock before taking the fail-closed path.

## Current CPU verification (latest frozen source, 2026-10-12)

The latest root-owned CPU evidence is D:\AI\runs\shared-ledger\p2\sdk-session-cpu-root-20261012T1045Z-ae0cc7f775024896b3ed1246001e37c4\evidence-manifest.json (SHA-256 3c9eaf059971c3de37d2a3bd4d586e226d8b08904611320b67e8d0de74ea2dc1). It binds 126 frozen inputs with identical pre/post hashes.

- Focused token-budget, preparation, and session suite: **42 passed**, exit 0; stdout SHA-256 6f15b6d3cbc1c13280cef03978d7d54a1fb62ea41e1167ce951d3de44730bc09.
- Full agent test suite: **295 passed**, exit 0; stdout SHA-256 d6caed6abf1b27746a7505311410ba0c700153ff3d2bf7d9bbb61268ab2d3a74.
- Read-only v1 export check: pass, exit 0; stdout SHA-256 bbaa6b601b509b2670dab8d0893dcd70e095bdf2bcd33d85ec96fa848999ff52.

These runs were CPU-only and did not probe a live SDK, model, Supabase, or Docker. The older 41-pass focused run below is historical and is bound to its older source snapshot.

## Append-only token-only candidate revision

The current executable candidate is staged at D:\AI\runs\shared-ledger\p2\persistent-sdk-session-prereg-r2-reviewfix-20261012T113028Z. Candidate fingerprint: 6eba8e79e6c6f8e2be5ef997f45e92d02b4d0691b5ba4c67b40187a83ff6e326; candidate file SHA-256: f04cf7c7a888d4c2c9b4b3beff6dc6f8c6dd8afa6a93af709382dddf07feab21; runner SHA-256: a51dde679bb40b74afca3cc0308338194d8ae4183a5198ecfa09392760348392. It supersedes the prior R2 draft by candidate SHA a503f28c1133a461996ec80c7a2d0392da3c478dd6995fab0c7d60e82edcd7f3 and fingerprint df4ca8c0cb3a61f6ed0b1dee3bbe91688ed4b7cf302d1d05141a279b527e8df3; that earlier draft remains preserved with its own package manifest.

The R2.1 runner uses one prepare_sdk_session(timeout_seconds=15) call, which performs its one internal artifact readiness operation. Its failed-measure records distinguish wall time including possible cleanup from the unknown measurement-only duration. It polls the saved checker-owned process after public close and writes the final result-log SHA only after closing the append-only journal. The execution gate requires the exact reviewed fingerprint. Current CPU-only check output SHA-256 is 146bc7565e4b884356e4e1d36428e5ecc15bad9bd098b2afbec829e8523b10db; it verified all 13 raw and typed request hashes and the 126 frozen inputs, ran two mock stop-policy scenarios, and reported zero SDK imports, checker construction, prepare calls, measurements, or generations. Package manifest SHA-256: 795d7ba01b66c9ffbb05a3fa1852167138ab94dab976eee8f896e2ab90da2159. The candidate is pending root review; no SDK or count call has been made.

## Historical focused CPU run (superseded source snapshot)

This historical focused CPU run used the checked-in fake helper plus fake SDK objects; it did not import or connect to a live LM Studio service. It covered fresh before/after model lookups, path and context changes before and after counting, bounded state-lock waits, no cold fallback after failed preparation or changed artifacts, strict boolean-ID rejection, late-ready and late-result close races, helper exit, oversized output, pipe-thread cleanup, a stalled child timeout, and one-shot cleanup after delayed fake reap.

- Command, from `agent/`: `PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp <D-only-run-dir> tests/test_p2_token_session.py tests/test_p2_token_budget.py tests/test_p2_token_preparation.py`
- Result: **41 passed in 2.14 seconds**, exit code 0.
- Run directory: `D:\AI\runs\shared-ledger\p2\sdk-session-final-focused-20261012T095956Z-31263795f4bd4290891cd0dbfc6e1f36`
- Log SHA-256: `254E3CF88D7C1678297840EEC85387B629313E5A0F691813345900CD213FC36C`
- Observed command interval: `2026-10-12T09:59:56.6883874Z` to `2026-10-12T09:59:59.5768130Z`.

Source and test hashes at the time of this run:

| File | SHA-256 |
| --- | --- |
| `app/p2_token_budget.py` | `9638F32C993B8B93329CDC6B0BCD1EF04BC07B5A85C51C45A41B68380F2FCAEE` |
| `tests/test_p2_token_session.py` | `BB77FAAE1FC7B63227FF53DDCC700CD7D733D21D2829CB7C582E2165B9F51FFE` |
| `tests/test_p2_token_budget.py` | `825FD50772363F35E2693C69726AAC28B713684E1E268D387B2022962C68604E` |
| `tests/test_p2_token_preparation.py` | `CC3D5D7BF3F8487203E800C088C468FB98F8EA042034D6E178F0012FFB6E4106` |

Earlier token-only candidate attempts remain unchanged: all 13 timed out and failed closed, with zero successful counts and zero generations. This CPU run does not supersede those results and does not establish actual token fit. A future count requires a newly reviewed source/candidate freeze and separate authorization; the 13 earlier request attempts are not to be retried.
