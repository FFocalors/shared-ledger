# P2 R2 status

**How this file is organized** (structure note added 2026-10-18; no original record text was deleted, merged or rewritten):

- **Current status** is `## Current private-v3 checkpoint — 2026-10-18` and the dated records under it, down to the `---` divider.
- **Historical record** is everything below `## Historical record (superseded) — 2026-10-12 and earlier`. It is a superseded snapshot; do not read it as current status.
- Each record in the current section carries a `**Record date: ...**` label. A date is shown only where the record itself states it; nothing was inferred. A record that does not state its own date is labeled `not stated` and carries an inline `<!-- 归属待定 -->` comment naming the evidence (if any) that might place it, left for the owner to decide.
- The records were not reordered: they stay in their original sequence, because later records refer back to earlier ones ("described above", "recorded below").

## Current private-v3 checkpoint — 2026-10-18

**Record date: 2026-10-18**

Private-v3 and native transport remain disabled by default. Current source/config pin: [native-runtime-resume-budget](D:/AI/runs/shared-ledger/p2/native-runtime-resume-budget-20261018-02/p2-v3-execution-manifest.json), SHA-256 `5df93c7fe360e8cedda27b2ca38379c031cd227768f31f7505c127bcd3dd92c6`; the four bindings are mirrored in the D startup example. The 50-test related CPU set passed, covering Runtime same-generation/input resume through immutable query descriptors and a new page-0 attempt, persisted cumulative actual-dispatch accounting across resume, Store charge accounting across equal-timestamp restart, and continuation nonce CAS ([result](D:/AI/runs/shared-ledger/p2/native-runtime-resume-budget-20261018-02/pytest-50-result.json)). This is synthetic CPU coverage, not a live Auth/process recovery test. Existing local Auth/RLS finance reads and the historical-pin native activity Turn remain bounded local evidence; the clarify native HTTP response passed post-hoc strict/parser validation under the preceding `78347cc36eedea5d75135cd03e4ca76c6cc7292289228d50e5ca947ea0a079f4` pin (1,540 prompt tokens plus 512 safety margin). The old `internal_failure` remains unexplained and unreproduced (old parallel=4; completed Turn parallel=1). A resumed query rereads page 0 and can obtain one fresh terminal continuation page; it does not restore an old cursor or skip page 0. Cloud Auth/RLS remains untested, model quality is `INSUFFICIENT_SAMPLE`, and no full Stage B/Stage D/CAP acceptance is claimed.


**Record date: 2026-10-17**

Latest isolated local Auth/RLS and Stage D follow-up (2026-10-17): a D-only Supabase stack used normal local A/B Auth tokens and the real local Data API through the HTTPS loopback bridge. A read its member activity and expense/debt DTOs, including amount, currency and debt direction; B could not read A's member rows using the same scope or a forged UI hint. Missing/invalid bearer tokens failed closed, and App session-owner checks passed. Local RPC writes were used only to prepare the fixture; subsequent acceptance requests were read-only. This is local evidence, not cloud Supabase acceptance. The ordinary activity had zero refund and prepayment rows (HTTP 200), so no populated refund/prepayment DTO or typed P2 QEV for those shapes was validated; member removal/revocation was not tested. An expired local JWT produced an actual App /v1/sessions 401; normal password login refreshed the same test account and the App verifier accepted the new token.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期。它一面指向本文件顶部（2026-10-18 检查点）的 source/config manifest，一面引用 D:\AI\runs\shared-ledger\p2\local-auth-acceptance-20261017\ 下的离线回放；两处指向不同日期，未替它推断。 -->

Historical cap2s source-pin check: the P2 source-local metadata acceptance cap was 2,000,000 µs (2 seconds), with backend total 20 seconds and active Turn total 240 seconds. Its focused overrun regression passed (1 passed in 3.93 seconds; D temp D:\AI\runs\shared-ledger\p2\p2-cap-2s-targeted-pytest-tmp). The old cap2s manifest remains historical; the current source/config manifest and hash are recorded at the top of this status. A zero-model-POST offline replay of a saved activity-read response accepted the Store query and produced two source receipts, one QEV and one fact proof/card; answer generation was intentionally blocked by that replay harness ([replay result](D:\AI\runs\shared-ledger\p2\local-auth-acceptance-20261017\stageD-activity-offline-replay-2cb9df4bcc\stageD-local-native-read-offline-replay-result.json)).

**Record date: 2026-10-17**

Earlier failed local App-ingress native Turn (2026-10-17, retained): it used https://127.0.0.1:56925 for both Auth and the derived backend origin, with the 2-second source loaded from the then-current manifest. SQLite records read.activities attempt started, but no source GET receipt or QEV; whether the bridge saw a GET is unknown. The Turn ended WAIT_INPUT with dependency_unavailable/internal_failure after one actual model POST; no accepted read, answer, or protected sidecar was produced. Its internal exception remains unlocated. This is not evidence of model quality failure or of the 2-second cap being the cause. Original result: [failed native App Turn](D:\AI\runs\shared-ledger\p2\local-auth-acceptance-20261017\stageD-native-activities-fb8f6ca049\stageD-local-native-activities-result.json); its Store database is in the same run directory.

**Record date: 2026-10-18**

Latest bounded local read diagnostic (2026-10-18): a corrected D-only harness first replayed the saved native decision through normal imports with zero model POSTs; read.activities, the adapter, Store attempt acceptance, and page issue all returned, with two source receipts. One real App-ingress native Turn then completed with two model POSTs and one read.activities query. Its SQLite run contains two HTTP 200 source receipts (activities and activity_members), one complete QEV, one fact proof/card, and one protected source-bearing answer. The protected answer citation and fact card both reference that current QEV; its query-result and fact-source links resolve to the two real source receipts. The frozen v1 message event has citations=[] by design; the v3 citations live in the protected sidecar. Evidence: [completed native Turn result](D:\AI\runs\shared-ledger\p2\read-failure-diagnostic-20261018-243c3b0c\stageD-activity-offline-replay-f805b6c0c7\stageD-local-native-read-offline-replay-result.json) and its [SQLite Store](D:\AI\runs\shared-ledger\p2\read-failure-diagnostic-20261018-243c3b0c\stageD-activity-offline-replay-f805b6c0c7\p2-native-replay-store.sqlite3). The result JSON retains shared-runner captured-response path/timestamp metadata; this live Turn delegated to LM Studio transport and did not replay that artifact. This is local evidence only. The previous internal_failure was not reproduced and its cause remains unlocated. This run used model t0-cp36-20261007, context 8192, and parallel 1; the earlier failed sample used parallel 4, so their latency is not comparable. At that time this diagnostic used the historical cap2s source/config pin and made no Agent source change; the later scope-projection fix and fresh current manifest are recorded above. Model quality remains INSUFFICIENT_SAMPLE; no overall Stage B, Stage D, or CAP acceptance is claimed.

**Record date: 2026-10-18**

Historical populated-fixture source/RLS checks (2026-10-18) used local GoTrue password-login JWTs, authenticated setup RPCs, and HTTPS Data API reads. They recorded one linked refund (-20 CNY), a large-activity prepayment account (40 CNY; owner A/custodian B), one usage/debt row (40 CNY; A debtor to B creditor), and one return (20 CNY; B custodian to A owner); ordinary-activity prepayment was denied (HTTP 400 / SQLSTATE 23514). A separate revoke fixture showed B's reads falling to zero after A removed B. Evidence: [populated fixture result](D:\AI\runs\shared-ledger\p2\stageB-populated-local-read-20261018-p2resume1\stageB-populated-local-read-result.json) and [member-revocation result](D:\AI\runs\shared-ledger\p2\stageB-populated-local-read-20261018-p2resume1\stageB-member-revocation-result.json). The first App wrapper attempt was invalid: its two-call model budget was below the readflow's three-call reservation, and its post-shutdown Store read raised StoreNotStarted; it was superseded by the successful authenticated App/Runtime/Store/QEV reads described above, not a production defect.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段是汇总性状态段（云端未验证、质量不足），段内没有日期，也没有可据以定位的证据目录。 -->

Cloud Supabase Auth/RLS closure remains unverified; the bounded local Stage D native answer and controlled-provider Stage B reads are documented above. Model quality remains INSUFFICIENT_SAMPLE; no CAP or overall Stage B/Stage D acceptance is claimed.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期。其证据目录名为 D:\AI\runs\shared-ledger\p2\pytest-native-wire-20261017-…，指向 2026-10-17；未据此推断。 -->

The repository now includes the default-off `P2V3NativeCandidateReadProvider`, selected explicitly through Settings/components, with the native wire choice and limits covered by the verified source/config pin. The focused tests `test_native_candidate_rebuilds_counted_wire_and_keeps_strict_sent_guard` and `test_native_provider_selection_and_budget_must_match_verified_manifest` passed (2 passed in 2.00s); the exact command and D: temp directory were:

```powershell
$env:PYTHONPATH = 'D:\project\Android\shared-ledger-agent\agent;D:\project\Android\shared-ledger-agent'
$base = 'D:\AI\runs\shared-ledger\p2\pytest-native-wire-20261017-fbaa2c35110d4fc5a1bb765183ebbcbb'
& '.\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider --basetemp $base tests/test_p2_read_prompt_provider_v3.py::test_native_candidate_rebuilds_counted_wire_and_keeps_strict_sent_guard tests/test_p2_v3_execution_cohort.py::test_native_provider_selection_and_budget_must_match_verified_manifest
```

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期。其证据目录 native-four-semantics-20261017-… 与 native-two-remaining-20261017-… 指向 2026-10-17；未据此推断。 -->

The current native source received one ordinary in-process startup check, recorded below. Cumulative native provider/parse diagnostics issued 4 actual POSTs across the original batch and a clarify-only follow-up, using `P2V3NativeCandidateReadProvider`, the pinned `native_candidate` manifest, model `t0-cp36-20261007`, `/api/v1/chat`, context 8192, output 1536, input cap 6144, margin 512, and temperature 0. `read.activities` with no scope passed sent guard and strict parser in 27.155s; general `answer` passed with `basis=non_business_general` and empty citations in 17.664s. The first missing-scope `clarify` returned a sent-guard-approved typed `P2ClarifyDecision` in 19.708s, but the original D runner then raised `AttributeError` by reading `.value` from plain-string `missing_slots`; its current-pending-slot condition was not verified and its error handler overwrote the raw case output. After the corrected runner passed its local harness selfcheck, the single clarify-only retry passed JIT measurement (1407 prompt + 512 margin = 1919/6144; context 8192, output 1536) but timed out at the 90-second HTTP deadline (90.133s), with no HTTP response or decision parse; the proposal case was not sent. No source queries or external Auth calls were made. These are bounded development provider/parse diagnostics, not a model-quality, CAP, or stage D pass; raw text from the original returned cases was not retained, the retry timed out without output, and real Supabase remains `USER_DEFERRED`. Artifacts: [original batch summary](D:\AI\runs\shared-ledger\p2\native-four-semantics-20261017-e5aedd35b06745af9cf7d2302201dd4a\result.json), [clarify retry result](D:\AI\runs\shared-ledger\p2\native-two-remaining-20261017-2d87865379e441148046f277c9e6227a\result.json), and [corrected harness selfcheck](D:\AI\runs\shared-ledger\p2\native-two-remaining-20261017-2d87865379e441148046f277c9e6227a\harness-selfcheck.json).

**Record date: 2026-10-17**

Latest bounded semantic diagnostic update (2026-10-17): the original three-POST batch is now matched to LM Studio log times 2026-10-17T13:01:53Z–13:02:57Z (model `t0-cp36-20261007`). A read-only recovery saved the third POST's exact generated clarify text in [the server-log recovery](D:\AI\runs\shared-ledger\p2\native-four-semantics-20261017-e5aedd35b06745af9cf7d2302201dd4a\clarify-serverlog-recovery.json). It contains `missing_slots=["activity_scope"]`; the server log truncates the request input, so equality with the actual request-time public pending/allowlist cannot be independently confirmed. The historical runner record shows sent-guard acceptance and typed `P2ClarifyDecision`, followed by its slot-assertion harness error; the later single clarify retry timed out with no response. The previously unrun proposal case then made one separate POST (HTTP 200, 7.042s), but the model returned a source-free `answer` rather than the only server-allowed `propose` kind, so the strict sent guard rejected it. No proposal was recognized and no preview, confirmation, backend execution, source query, or external Auth call occurred. At that checkpoint, cumulative count stood at 5 actual POSTs: 3 original (read and general answer passed; clarify returned/parsed but pending-slot equality is unverified), 1 clarify-only timeout, and 1 proposal guard rejection. This remains `INSUFFICIENT_SAMPLE`; neither model quality nor stage D/B is accepted, and real Supabase remains `USER_DEFERRED`.

**Record date: 2026-10-17**

Subsequent proposal-only update (2026-10-17): the native provider now appends `direct-decision-hint-r3`. When the server context says `trusted_intent.classification=proposal_intent` and the guard allows only `propose`, the hint says this is recognition only: select an operation from `guard.allowed_proposal_operations`, summarize the intent, and do not preview, confirm, or write. It distinguishes financial-source/business-write authorization from normal user identity validation and the server guard; it does not change read or source authorization. A fresh D-only native manifest pins this source and the existing configuration: SHA-256 `5d84dfec5336fba6a68926e3b273d5a4552f99623a958a1b1e544b2588d7874e`, model `t0-cp36-20261007`, 90-second HTTP timeout, output 1536, context 8192, input 6144, and 512 margin. The [manifest](D:\AI\runs\shared-ledger\p2\native-proposal-hint-r3-20261017-2e8067f1e68d4719ba6b24c6761c1b9a\execution-manifest\p2-v3-execution-manifest.json) replaces the earlier startup manifest for this source; the startup package [settings example](D:\AI\runs\shared-ledger\p2\native-startup-20261017-fa965f8550a64938be89377494ecbb97\native-settings.env.example) now points to the same r3 binding. The prior startup evidence is historical for pre-r3 source; the existing runner regenerates a fresh manifest when invoked. App startup and tests were not rerun.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期，直接接续上一段（2026-10-17）的 proposal 序列；其证据目录 native-proposal-hint-r3-20261017-… 指向 2026-10-17。未据此推断。 -->

The same proposal input `新增消费` then made one POST through the repository `P2V3NativeCandidateReadProvider` (HTTP 200, 0.89s). SDK JIT counted 1,498 prompt tokens + 512 margin = 2,010/6,144. The model returned `kind=propose`, `operation=expense.create`, with a short recognized-intent summary; both sent guard and strict parser accepted `P2ProposalRecognition`. It was recognition only: zero source queries/Auth calls/backend execution, preview, confirmation, or write. The [D-only result](D:\AI\runs\shared-ledger\p2\native-proposal-hint-r3-20261017-2e8067f1e68d4719ba6b24c6761c1b9a\result.json) retains the raw response and wire/count binding. Cumulative total is now 6 actual POSTs: the original 3, one clarify timeout, one proposal wrong-kind rejection, and this passing proposal recognition; 5 returned HTTP responses, 1 timeout. The recovered clarify raw also matches the `activity_scope` pending slot in an [offline classifier replay](D:\AI\runs\shared-ledger\p2\native-proposal-hint-r3-20261017-2e8067f1e68d4719ba6b24c6761c1b9a\clarify-offline-pending-replay.json), which is a semantic check against the known input, not proof of the truncated original request body. The native model sample remains insufficient; no CAP or stage D/B acceptance is claimed, and real Supabase remains `USER_DEFERRED`.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期，混合了 v3 语义/活动流程/Store 的定向命令与更早的 startup-check-7359b33b… 证据（该目录名无日期）。未替它推断。 -->

Focused CPU commands and results: `.venv/Scripts/python.exe -m pytest tests/test_p2_v3_runtime_semantics.py -q` passed 4/4 in 19.68s; `.venv/Scripts/python.exe -m pytest tests/test_p2_v3_runtime_activity_flow.py -q` passed 2/2 in 3.94s. The six-operation scoped adapter first-page checks previously passed 6/6, the Store two-page check passed 1/1, and local schema migration 5 → 6 passed. These are fixture/code-path checks, not live model or live business acceptance. The earlier, pre-native-integration `create_app → build_components` startup check passed wiring, schema/cohort inspection, and live/ready health; its [startup evidence](file:///D:/AI/runs/shared-ledger/p2/startup-check-7359b33b1da443c9867614f3b4635dcd/startup-check.json) has manifest SHA-256 `5c168e4694b33f40441401cfabef34166272c81351a326322fc3ada4890a0cff`. At that startup, provider status was `NOT_READY` / `last_call_failed` and port 1234 was not listening. Subsequent recovery started the LMS service on 1234 with only model `t0-cp36-20261007` at context 8192; the same SDK/checker reported its session ready and then closed ([provider diagnostic](file:///D:/AI/runs/shared-ledger/p2/startup-check-7359b33b1da443c9867614f3b4635dcd/provider-diagnostic.json)). This confirms counter/model preparation only; it is not a later app health-ready check or a successful generation.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期，只自称“earlier”于上一段的启动检查；引用目录 startup-check-f595d5986abb… 名称中无日期。未替它推断。 -->

The earlier [current-source manifest](D:\AI\runs\shared-ledger\p2\startup-check-f595d5986abb481f97b4c113a5fe451c\execution-manifest\p2-v3-execution-manifest.json) and [startup report](D:\AI\runs\shared-ledger\p2\startup-check-f595d5986abb481f97b4c113a5fe451c\startup-check.json) remain as historical evidence. That run used `agent_enabled=false`; this setting alone does not show that Runtime preparation was skipped, because the app lifespan starts assembled resources regardless and `P2Runtime.start` calls the candidate provider's `prepare()` whenever the v3 provider is wired. The saved report did not capture preparation outcome, so the run proves ordinary assembly, fresh D-backed Store startup/shutdown, and the recorded health responses only; its candidate preparation result is unknown.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期。其证据目录 native-startup-20261017-… 指向 2026-10-17；未据此推断。 -->

The current native-source check used the ordinary `create_app(Settings) → default build_components → lifespan` path with `agent_enabled=true`, both v3 candidate flags enabled, provider wire `native_candidate`, a 90-second HTTP timeout, a 1536-token output limit, and a fresh D-backed SQLite Store/journal. Its [manifest](D:\AI\runs\shared-ledger\p2\native-startup-20261017-fa965f8550a64938be89377494ecbb97\run-bf57bc978459458abd1342b0f18ffc82\execution-manifest\p2-v3-execution-manifest.json) was generated against the current source using the installed LM Studio SDK 1.5.0 `METADATA` and supplied local model identity; SHA-256 is `c00fa5eae6e78f173cb187b9f14ea53c0171d57d5a9615448c8ae6d3624700d5`. During lifespan the assembled candidate class was `P2V3NativeCandidateReadProvider`, `P2Runtime._p2_v3_ready=true` after its read-only prepare call, and the scheduler task was running. App startup and shutdown completed; the provider and counter checker closed, and the scheduler reference was cleared. `GET /health/live` and `GET /health/ready` returned 200, with schema and storage ready; `/health/provider` returned 200 `unavailable/not_tested`, and health reported `inference_available=false` / `runtime_available=false` because this run submitted no Turn and made no inference call. The run recorded zero Turns, model-generation POSTs, external Auth calls, and Supabase requests. The synthetic Auth settings were not contacted. The [startup report](D:\AI\runs\shared-ledger\p2\native-startup-20261017-fa965f8550a64938be89377494ecbb97\run-bf57bc978459458abd1342b0f18ffc82\startup-check.json), reusable [settings example](D:\AI\runs\shared-ledger\p2\native-startup-20261017-fa965f8550a64938be89377494ecbb97\native-settings.env.example), [startup instructions](D:\AI\runs\shared-ledger\p2\native-startup-20261017-fa965f8550a64938be89377494ecbb97\README.md), and runner are in the [D-only package](D:\AI\runs\shared-ledger\p2\native-startup-20261017-fa965f8550a64938be89377494ecbb97). The manifest CLI binds the supplied model path/hash/size as identity; it does not read or hash the GGUF artifact. The earlier compatibility and native generation attempts remain development-fixture diagnostics and do not establish model quality or reasoning control.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期，也没有可据以定位的证据目录。 -->

One prior real 1536-token-compatible request returned HTTP 200 but empty content; all 1536 tokens were reasoning and no source GET followed. No thinking control field was present, so no successful reasoning-control change is established. A separate non-business development diagnostic passed 1/1 and is not model-quality evidence. Cloud two-user Supabase and a completed Stage D Supabase-to-model answer remain unverified; the bounded local checks and incomplete Turn are recorded above. CAP is 0/17. No Teacher, sealed evaluation, or training work was performed.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期。其证据目录 compact-schema-real-read-answer-20261017 指向 2026-10-17；未据此推断。 -->

After the context-bound read-schema compaction, one synthetic Activity-discovery Turn was attempted against the already-loaded `t0-cp36-20261007` model. The pinned SDK 1.5.0 JIT count succeeded (977 prompt tokens, 364 schema tokens, 512-token margin), then the single actual POST timed out after 30 seconds with `TimeoutError` / provider code `cancelled`; no HTTP response, model text, or parse result was available. The Turn was persisted as `WAIT_INPUT/auth_required`; that application state does not establish that identity was actually invalid. The in-memory synthetic source received zero GETs and produced no typed query evidence or facts, so no answer call followed. This is a model-endpoint transport timeout, not a model-output or parser result; real Supabase remains untested. Evidence is in [the run directory](D:\AI\runs\shared-ledger\p2\compact-schema-real-read-answer-20261017), including `result.json`, `http-request-01.json`, and `prepared-model-context-01.json`.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期。其证据目录 compact-schema-real-read-answer-timeoutfix-20261017 指向 2026-10-17；未据此推断。 -->

The timeout-path fix restores P2's configured Runtime deadline after the inherited P1 ten-second clamp and gives production Runtime an outer budget of HTTP timeout + token-counter deadline + 1 second (36 seconds at current defaults; production HTTP remains capped at 30 seconds). A follow-up synthetic Activity-discovery attempt kept the same model, endpoint, compact schema, context 8192, output 1536, and temperature 0, using 60-second HTTP and 75-second Runtime limits for this diagnostic only. JIT counting succeeded (977 prompt tokens, 364 schema tokens, 512-token margin); the sole actual POST timed out at the HTTP deadline with provider code `timeout`. No HTTP response or model text was available, so there was no decision parse, source GET, typed QEV/fact, or answer POST. The Turn remained `WAIT_INPUT/auth_required` as the app's timeout pause state; this does not establish an identity failure. The existing LM Studio `main.log` predates the request, `lms` CLI is unavailable, and read-only `/api/v0/models` reports the model `loaded` without a busy indicator; server receipt, grammar errors, and generation-time reasoning state therefore remain unknown. Real Supabase remains untested. Evidence is in [the follow-up run directory](D:\AI\runs\shared-ledger\p2\compact-schema-real-read-answer-timeoutfix-20261017), including `result.json`, `http-request-01.json`, and `prepared-model-context-01.json`.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期。其证据目录 native-candidate-read-20261017 指向 2026-10-17；未据此推断。 -->

A separate native-route candidate reused the saved synthetic public Activity-discovery messages and appended the 1,333-byte context-bound schema as marked text in `system_prompt`; the single `/api/v1/chat` POST requested `reasoning=off`, `store=false`, context 8192, output 1536, and temperature 0, with no `response_format`, integrations, or tools. The client timed out after 60.05 seconds without an HTTP response, so output, reasoning length, server stats, and parser results are unavailable. This differs from the compatibility attempts by route, requested reasoning setting, and schema delivery as an unenforced text hint; it is not a controlled single-variable comparison, and the request does not establish that reasoning was actually disabled. Service receipt, schema adherence, and model quality remain unknown; real Supabase remains untested. Evidence: [native candidate result](D:\AI\runs\shared-ledger\p2\native-candidate-read-20261017\result.json), with the saved payload and one-use probe script in that directory.


**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期，是对上面两条超时请求的服务器日志复核（本地时间 16:14 与 16:20，未记日期）。未替它推断。 -->

A follow-up read of the existing LM Studio server log corrects the earlier “receipt unknown” note above: both timed-out requests reached the server and immediately started on slot 0 (no queue wait is shown). The compatibility request arrived at local 16:14:02; by 16:15:01 the server recorded 275 generated tokens at 4.62 tokens/s, then the client disconnected at its 60-second deadline. The native candidate arrived at 16:20:30, completed prompt processing for 889 tokens in 41 seconds (21.68 tokens/s), and the client disconnected at 16:21:30 without a complete HTTP response. The server log showed no grammar or resource error for these attempts. The model-load entry identifies `t0-cp36-20261007`, `n_slots=4`, and `n_ctx_slot=8192`. A later absolute-path `lms ps` showed the loaded model `IDLE`, context 8192, parallel 4, `DEVICE=Local`; neither that abstract device field nor the available load logs record GPU offload layers or a CPU/GPU backend, so 4.62 tokens/s cannot be attributed to CPU execution or missing offload from this evidence. The earlier PATH-based “lms unavailable” observation was superseded by the absolute CLI check. Selected source lines, with original line numbers and no prompt/response bodies, are in [the D-only evidence extract](D:\AI\runs\shared-ledger\p2\startup-check-7359b33b1da443c9867614f3b4635dcd\lmstudio-load-and-request-evidence.txt).


**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期。其证据目录 native-candidate-closed-loop-20261017-20261017a 指向 2026-10-17；未据此推断。 -->

One isolated native candidate Activity-discovery Turn then made one POST to `/api/v1/chat` and received HTTP 200 after 18.156 seconds. The response contained one `output[type=message].content` string of 273 characters; response stats reported 0 reasoning output tokens. The SDK JIT count passed at 1,351 prompt tokens plus the 512-token margin (1,863/6,144). The existing strict sent guard rejected the response with `ValidationError`: the model returned the older `candidates` wrapper, not a current P2 decision. The Turn failed with zero source GETs and no second POST. This is a protocol-mismatch observation, not a model-reliability pass. This `/api/v1/chat` request asked for `reasoning=off` and omitted `response_format`. Native remains a D-only diagnostic with schema text only; compatibility remains the production first choice. Treat the wrapper mismatch as input to future model/protocol adaptation; do not change v3 or frozen v1 to accept the old wrapper. Real Supabase remains `USER_DEFERRED`. Evidence: [native candidate result](D:\AI\runs\shared-ledger\p2\native-candidate-closed-loop-20261017-20261017a\result.json), with the response text and request/response files in that directory.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期，汇总更早的兼容/原生尝试；所引证据目录 startup-check-7359b33b… 名称中无日期。未替它推断。 -->

The read-only [LM Studio load/config and generated-response summary](D:\AI\runs\shared-ledger\p2\startup-check-7359b33b1da443c9867614f3b4635dcd\lmstudio-generated-response-summary.json) covers earlier attempts: compatibility logged empty content with 276 reasoning tokens; an earlier native attempt logged 181 content characters that were not complete JSON. It also records GPU ratio 1.0, Flash Attention enabled, context 8192, and parallelism 4; actual GPU device and offloaded-layer count remain unknown. Those earlier metadata do not describe the current candidate response or establish its execution device.


**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期。其证据目录 …direct-decision-hint-r1-20261017-20261017b 指向 2026-10-17；未据此推断。 -->

A D-only `direct-decision-hint-r1` prompt variant then used two native `/api/v1/chat` POSTs in one synthetic Activity-discovery Turn (22.156s and 29.157s). SDK JIT counted 1,501 and 2,175 prompt tokens plus the 512-token margin (2,013/6,144 and 2,687/6,144). The first 306-character response passed the strict sent guard as `read.activities`; the Runtime used the existing in-memory synthetic source (`activity_members`, `activities`) and built fresh typed QEV/fact context. The second 141-character answer included an extra root `"type":"application/json"` field and failed the strict sent guard with `ValidationError`; the Turn ended `FAILED` without another call. No real Supabase request was made. This remains an isolated native development candidate with schema and instruction text only; it does not prove model reliability or production compatibility. The fixture has been used through multiple development attempts and is not an independent quality measure. Compatibility remains the production first choice, and real Supabase remains `USER_DEFERRED`. Evidence: [direct-decision-hint-r1 result](D:\AI\runs\shared-ledger\p2\native-candidate-closed-loop-direct-decision-hint-r1-20261017-20261017b\result.json), with exact request/response files in that D-only run directory.


**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期。其证据目录 …direct-decision-hint-r2-20261017-20261017c 指向 2026-10-17；未据此推断。 -->

A further D-only `direct-decision-hint-r2` synthetic Turn made two native POSTs, both HTTP 200 (6.594s and 1.469s); SDK JIT counts were 1,576 and 2,264 prompt tokens plus 512 margin. The initial schema/guard allowed `read` only, and the 306-character `read.activities` response passed; the Runtime used only the in-memory synthetic `activity_members` and `activities` source. The answer schema/guard then allowed `answer` only; with one QEV and one fact in context, the 115-character answer cited that fresh QEV and passed the strict sent guard. The Turn completed; event polling returned 200, and polling after synthetic membership revocation returned 404. The canonical v1 message event keeps `citations=[]`; a read-only SQLite check verified that the protected answer sidecar retained the same QEV citation and linked it to the same query receipt and one fact proof/card. The D-only [result readback](D:\AI\runs\shared-ledger\p2\native-candidate-closed-loop-direct-decision-hint-r2-20261017-20261017c\result.json) records all seven binding checks as true. This is a repeatedly developed synthetic fixture, not independent model-quality or production acceptance. Native remains a D-only, prompt-hint candidate; compatibility remains the production first choice and real Supabase remains `USER_DEFERRED`. Evidence: [direct-decision-hint-r2 result](D:\AI\runs\shared-ledger\p2\native-candidate-closed-loop-direct-decision-hint-r2-20261017-20261017c\result.json), with responses and event readback in that D-only run directory.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段未自述日期，也没有可据以定位的证据目录。 -->

The candidate Runtime also now preserves a valid `non_business_general` `decision.text` instead of replacing it with a fixed greeting, while retaining the private parser/sent guard and the checkpoint, owner/turn/profile, empty-read, policy, and citations constraints. The focused CPU test `test_p2_v3_runtime_semantics.py::test_v3_non_business_turn_answers_without_source_reads` passed 1/1 in 7.05 seconds, including rejection of a financial input that supplied a forged matching checkpoint. This is fixture coverage, not live-model quality evidence.

**Record date: not stated — attribution undetermined**

<!-- 归属待定：本段为运行时默认值陈述，段内未自述日期，也没有对应的证据目录。 -->

Runtime defaults remain context 8192 / input 6144 / margin 512 / output 768 (default; explicit output up to 1536), at most 6 model calls and 4 reads, model concurrency 1, per-user 1 running + 1 queued, global queue capacity 16. The v3 read path reserves 3 model calls and 1 logical read; observed provider calls were 2 or 3, and reservations are not POST counts. This is a progress checkpoint, not overall P2 acceptance.

---

## Historical record (superseded) — 2026-10-12 and earlier

**Everything below this heading is a historical snapshot preserved verbatim; it is not current status.** Each `###` section below names the date it reports.

### Historical snapshot — 2026-10-12

The following sections preserve the 2026-10-12 record as historical evidence. In particular, its zero-generation statement and its statement that prepayment/refund operations and page continuation were not implemented describe that earlier checkpoint only; they are superseded by the current private-v3 status above. The older full-suite and host-runner results remain valid only for their recorded scope and date.

Status updated 2026-10-12 09:32 UTC. This R2 status is separate from and does not modify the locked R1 report/manifests, frozen v1 contracts, Store, P1 tests, or T1 artifacts.

### Historical CPU result (2026-10-12)

The latest full `agent/tests` run passed `275 tests in 89.74s` (exit `0`). The exact command, environment, D-only temporary directory, and raw output are in `D:\AI\runs\shared-ledger\p2\container-cpu-plan-20261012T003903Z-55fa00ece0d54accba98c28bb0c3a3a7\full-regression-r2-final-20261012T0945Z`. The pytest log SHA-256 is `b913b2f43c2a5de99c2500b70b3ebd693ef7f135aff5708262b40b54d099546a`. The read-only contract export check passed at `export-check-r2-20261012T0935Z` with exit `0` and `contract snapshot matches manifest`.

The D-only host CPU runner passed with synthetic Auth, a controlled fake provider, the actual P2 Runtime and backend adapter, and a loopback PostgREST-shaped fixture. It validated a complete `read.activities` response/body and grounded activity-list control answer, a separate conversation answer, persisted cancellation, and interruption after a durable read body. A fresh Runtime safely returned to `WAIT_INPUT/MISSING_FIELDS`; it made no provider/backend calls, did not reset budgets, and did not trust prior volatile provenance. The canceled and terminal control states stayed unchanged and no grants survived. This is a synthetic host diagnostic, not live-model or live-Supabase evidence. Separate expense/debt closed-loop CPU tests are not part of this runner scenario. Exact attempt output and source binding are under `host-self-test-attempt-r2-source-20261012T0921Z`; the runner output hash is `b467696a8a8dabb9323ea8ff94f32e043bee36589a5eaa521be77d9731653d54`.

### Historical R2 model and backend gates (2026-10-12)

At this historical checkpoint, real R2 model generations were `0`. Startup/load of the local model service was authorized, but the provider owned service and token-counter work; that runtime task made no LM request. The 13-request SDK token-fit gate had `0/13` successful counts; all 13 attempts ended in timeout, so actual token fit was `UNKNOWN`. Controlled fake-provider responses in CPU tests were not model generations or quality results.

Real Supabase Auth/Data API, RLS, and the complete live backend/model flow remain `NOT_RUN_USER_DEFERRED`. No real credentials or Supabase requests were used. Docker/container execution remains `NOT_RUN_STORAGE_UNVERIFIED`: read-only Docker inventory found a cached P1 image, but no allowlisted settings field established D-backed Docker storage. No build, pull, or container operation occurred.

The earlier R1 17-call model diagnostic remains `FAIL_SEMANTIC_DIAGNOSTIC`; it is historical and is not changed by this R2 CPU run. It did not pass the four-semantic gate or establish quality.

### Historical test timing record (2026-10-12)

The first corrected R2 full suite recorded `272 passed, 3 failed` in 118.08 seconds. Two failures were old MockRuntime tests using a fixed four-second wait; one P2 test required an exact five-second subprocess timeout while the implementation correctly supplied the remaining bounded deadline. The provider corrected its owned test assertion only; the final 275-test run passed.

A separate diagnostic ran the old read-four/single-repair test logic with an in-memory 15-second waiter and did not edit P1 source or tests. The read-four case reached `FAILED` with five model calls/four reads in 3.188 seconds. The repair case reached `FAILED` with two model calls/one repair in 4.125 seconds, just beyond the original four-second wait. This timing evidence does not establish a root cause. Preserve the observed timeout sensitivity; do not claim a code defect or hide the earlier failure. All original attempts and logs remain under the D evidence root.

### Historical source/test evidence provenance (2026-10-12)

The 28-file source snapshot created before the latest full run is `source-snapshot-r2-20261012T0920Z`, manifest SHA-256 `19d8791849920bd43c964eeb338eca7739e0a99f7e16a2b8d8552800fb7f11ba`, fingerprint `393fb8c4bfc48ae202c99851fe31885419c358a0f430479114114b7fca06d30e`. This proves the app/deployment dependency inputs were stable across that run. The token-budget test file was corrected separately before the final run; its resulting SHA-256 is `825fd50772363f35e2693c69726aac28b713684e1e268d387b2022962c68604e`, with a focused 22-test pass recorded by the provider. Do not reinterpret the earlier 28-file snapshot as a pre-run snapshot of all tests. A final post-run source-and-test inventory is being saved separately with the evidence manifest.

### Historical product limits and status (2026-10-12)

The CPU implementation retains multiple results only for distinct financial operations with matching volatile private bindings and complete financial-version maps; same-operation rereads stale the previous result. Restart loses volatile provenance, so a persisted body cannot become trusted without fresh source evidence. No durable continuation or restart/auth restoration of provenance has been implemented. The context/result capacity, missing continuation, prepayment/refund operations, and base-currency fact rendering remain gaps. Facts are rendered in original currency; the renderer does not calculate sums, base-currency totals, or balances.

The runner is a Windows host diagnostic. P1 Docker success is not evidence of P2 Linux-container support. Real model quality is `INSUFFICIENT_SAMPLE`; no R2 inference sample has been generated. This status is not an overall P2 acceptance or deployment approval.

