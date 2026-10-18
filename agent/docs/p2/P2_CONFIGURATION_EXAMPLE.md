# P2 configuration example

Settings use the `AGENT_` environment prefix (`case_sensitive=False`). This file only documents configuration: it contains no credentials and does not enable any live service. The paths below are for the Windows host used for this engineering work; D-drive paths do not work directly inside a Linux container.

## Safe disabled profile

From PowerShell, these values keep the provider disabled and avoid Supabase or LM Studio traffic:

```powershell
$env:AGENT_STORAGE_PATH = 'D:\AI\runs\shared-ledger\local-agent.sqlite3'
$env:AGENT_PROVIDER_MODE = 'disabled'
$env:AGENT_AGENT_ENABLED = 'false'
$env:AGENT_P2_LMSTUDIO_ENABLED = 'false'
$env:AGENT_P2_TOKEN_BUDGET_ENABLED = 'false'
$env:AGENT_P2_JOURNAL_PATH = 'D:\AI\runs\shared-ledger\p2\agent-p2journal.sqlite3'
```

The P2 journal path must be absolute and on `D:`. Parsing Settings does not create it. In P2 mode, a D-drive journal is required; if `AGENT_P2_JOURNAL_PATH` is omitted, the default is the configured storage database path with `.p2journal.sqlite3` suffix and it must also resolve to D:.

## Live P2 configuration template, only after B approval

Do not use this template for live requests until the B gate has explicitly passed. 本机有限 A/B Auth/RLS 已执行，但整体 B 仍未完成；cloud 未执行，本轮按用户选择使用本机隔离环境。 Keep secrets in the operator's secret manager and inject them at process launch; never save their values in this document, shell history, source control, test logs, or evidence manifests.

```powershell
# Required after B approval. Supply these two values from the approved deployment.
$env:AGENT_PROVIDER_MODE = 'p2'
$env:AGENT_SUPABASE_AUTH_BASE_URL = '<approved Supabase project Auth URL>'
$env:AGENT_SUPABASE_API_KEY = '<approved publishable/anon key from secret manager>'
$env:AGENT_P2_JOURNAL_PATH = 'D:\AI\runs\shared-ledger\p2\agent-p2journal.sqlite3'

# Keep model transport explicitly disabled until the separate C result and
# operator approval authorize the frozen local provider setup.
$env:AGENT_P2_LMSTUDIO_ENABLED = 'false'
$env:AGENT_P2_TOKEN_BUDGET_ENABLED = 'false'
$env:AGENT_P2_LMSTUDIO_ENDPOINT_URL = 'http://127.0.0.1:1234/v1/chat/completions'
$env:AGENT_P2_LMSTUDIO_MODEL_KEY = '<exact loaded LM Studio model key>'

# Optional exact-artifact token counter. Enable only after C freezes these
# values; the paths must be absolute and the artifact hash/size must match.
$env:AGENT_P2_TOKEN_BUDGET_ENABLED = 'true'
$env:AGENT_P2_MODEL_ARTIFACT_PATH = 'D:\models\<frozen-model-artifact>'
$env:AGENT_P2_LMSTUDIO_MODEL_PATH = '<exact path reported by the frozen LM Studio model>'
$env:AGENT_P2_MODEL_ARTIFACT_SHA256 = '<64-hex frozen artifact SHA-256>'
$env:AGENT_P2_MODEL_ARTIFACT_SIZE_BYTES = '<frozen artifact byte size>'
$env:AGENT_P2_TOKEN_COUNTER_PYTHON = 'D:\tools\lmstudio-sdk\python.exe'
```

The line that enables LM Studio remains `AGENT_P2_LMSTUDIO_ENABLED=false` until both B and C gates and an explicit operator enablement are in place. After that approval, change this setting to `true` and inject the independently frozen artifact fields. Cloud Supabase acceptance remains untested; bounded D-only local Auth/RLS results are recorded in [R2 status](R2_STATUS.md). P2 container deployment has not been tested.

The token-counter binding also checks the endpoint's normalized HTTP origin and the configured context, input, schema-margin, output and time caps. Defaults are 8192 context tokens, 6144 input tokens, 512 schema-safety tokens, 768 output tokens and a five-second counter deadline. The model artifact, model path, SDK interpreter, model key and origin must match the independently frozen C candidate; placeholders above are intentionally invalid until replaced with those approved values. The counter does not load a model or auto-discover a service. With no verified checker, generation fails closed before POST.

Additional bounded settings are `AGENT_P2_MODEL_TIMEOUT_SECONDS`, `AGENT_P2_MAX_PROMPT_BYTES`, `AGENT_P2_MAX_REQUEST_BYTES`, `AGENT_P2_MAX_RESPONSE_BYTES`, `AGENT_P2_MAX_CONTENT_BYTES`, `AGENT_P2_TURN_GRANT_LEASE_SECONDS` (30–300), `AGENT_P2_TURN_GRANT_MAX_ENTRIES`, `AGENT_P2_MAX_MODEL_CALLS` (1–6), `AGENT_P2_MAX_READ_CALLS` (1–4), and `AGENT_P2_MAX_REPAIR_CALLS` (0–1). Model concurrency is fixed at 1; admission is fixed at one running and one queued task per user, with a global queue capacity of 16.

## Optional native v3 candidate

Compatibility chat completions remain the default. The native candidate is separately disabled by `AGENT_P2_V3_NATIVE_CANDIDATE_ENABLED=false`; enabling it requires `provider_mode=p2`, the existing v3 candidate and exact token-counter gates, and a production execution manifest pinned with `--provider-wire native_candidate`. It derives `/api/v1/chat` from the configured local compatibility endpoint's same origin and never falls back to compatibility after a native failure. The native request uses `reasoning=off`, `store=false`, no tools, context 8192 and schema text in the system prompt; native LM Studio does not enforce that schema through `response_format`, so the existing strict Runtime sent guard remains authoritative.

For a native manifest, add `--provider-wire native_candidate --http-timeout-seconds 90 --max-output-tokens 1536` to the manifest CLI command below, then use matching `AGENT_P2_MODEL_TIMEOUT_SECONDS=90`, `AGENT_P2_MAX_OUTPUT_TOKENS=1536`, and `AGENT_P2_V3_NATIVE_CANDIDATE_ENABLED=true`. `AGENT_P2_V3_CANDIDATE_ENABLED=true`, P2 mode, LM Studio, and the verified token-counter gate must also already be enabled. The production compatibility HTTP limit remains 30 seconds, and the outer Runtime deadline includes the counter deadline plus a bounded grace period. The native route is an opt-in P2 v3 candidate only; frozen v1 contracts and T1 assets are unchanged, and cloud Supabase acceptance remains `USER_DEFERRED`.

### Bounded local diagnostic — 2026-10-18

The current source/config manifest is D:/AI/runs/shared-ledger/p2/native-runtime-resume-budget-20261018-02/p2-v3-execution-manifest.json (SHA-256 5df93c7fe360e8cedda27b2ca38379c031cd227768f31f7505c127bcd3dd92c6); its four AGENT_P2_V3_EXECUTION_* bindings are mirrored in the D-drive startup example with both candidate gates disabled. An isolated native read.activities App Turn under the earlier cap2s pin used model t0-cp36-20261007, context 8192, input 6144, schema margin 512, output 1536, 90-second timeout, and parallelism 1. It made two model POSTs and completed with two HTTP 200 source receipts, one QEV/fact, and one protected answer citing that QEV. The older failed Turn used parallelism 4; its internal_failure remains unreproduced and unlocated, so latency is not comparable. Local Stage B fixtures with real GoTrue JWTs and RLS completed App/Runtime/Store/QEV reads for prepayment account, refund, usage, and return shapes using a controlled provider: three turns, two scripted provider calls per Turn, six total, and zero model-generation POSTs. Their source receipts, current QEVs, typed facts, and protected answers are linked. Ordinary-activity prepayment write was denied, and same-JWT reads after member revocation returned no rows. These results are limited to the isolated local environment; cloud closure remains untested, model quality remains insufficiently sampled, and no overall Stage B/Stage D/CAP gate is claimed. The provider remains disabled by default.

Same-generation/input recovery now reuses the stored immutable query descriptor after fresh Auth and metadata admission, skips model replanning, and starts a new attempt at page 0. Actual model dispatch is charged against the persisted plus reserved call count before dispatch; an already dispatched failure does not refund that count. The focused 50-test CPU run also fixes Store reopen ordering when reserve/dispatch/settle share a timestamp. Recovery rereads page 0 and may fetch one fresh terminal second page; it does not restore an old cursor or skip directly to a later page. These checks use synthetic Auth/controlled providers and are not live Auth or model recovery evidence. See the [D-only result](D:/AI/runs/shared-ledger/p2/native-runtime-resume-budget-20261018-02/pytest-50-result.json).

This configuration does not change the public v1 contract or enable a business write route, proposal preview, or cloud Supabase acceptance. The tested local read paths remain behind the existing opt-in gates, which stay disabled by default.

### Compatibility reasoning-control limitation

LM Studio's documented [OpenAI-compatible Chat Completions API](https://lmstudio.ai/docs/developer/openai-compat/chat-completions) does not list a `reasoning` request parameter or a supported way to force reasoning off. A prior `/v1/chat/completions` sample with `max_tokens=1536` returned empty content and `finish_reason=length` after all 1,536 output tokens were consumed by reasoning; see the historical diagnostics in [R2 status](R2_STATUS.md). Do not guess an undocumented parameter or silently change the default route. The separately opt-in [native `/api/v1/chat` API](https://lmstudio.ai/docs/developer/rest/chat) documents `reasoning: "off"`; the current pinned native clarify request used that setting and reported zero reasoning output tokens. This addresses the control available on the native candidate only and does not establish model quality or replace the compatibility default.

## Generate a local V3 execution manifest

`agent.app.p2_v3_manifest_cli` creates files in a new D-drive directory and runs the existing V3 verifier against them. It binds the current application sources, migrations 001–006, the locked dependencies, exported read/event schemas, nonsecret model configuration, and the supplied LM Studio SDK `METADATA`. It records the model artifact path, size and supplied SHA-256 as configuration; it does not read or hash the model artifact. It also does not start a service, load a model, contact Supabase, or authorize the V3 route. The result is a local configuration pin, not a review or deployment approval. Older manifests without the current migration and startup-role bindings do not cover this source set.

Run from the repository root with an output directory that does not already contain these generated files:

```powershell
uv run --project agent --frozen --all-groups --python agent/.venv/Scripts/python.exe python -m agent.app.p2_v3_manifest_cli `
  --output-dir 'D:\AI\runs\shared-ledger\p2\execution-manifest-<unique-id>' `
  --model-key '<exact LM Studio model key>' `
  --artifact-path 'D:\models\<frozen-model-artifact>' `
  --artifact-sha256 '<64 lowercase hex characters>' `
  --artifact-size-bytes '<positive integer>' `
  --lmstudio-model-path '<exact loaded model path>' `
  --counter-python 'D:\tools\lmstudio-sdk\python.exe' `
  --counter-sdk-metadata 'D:\tools\lmstudio-sdk\Lib\site-packages\lmstudio-<version>.dist-info\METADATA'
```

The command prints the manifest path and digest plus the four nonsecret `AGENT_P2_V3_EXECUTION_*` environment bindings, including the JSON external-component-root map. Review those values before setting them. The V3 candidate remains disabled unless it is separately enabled and all existing gates and operator approvals are satisfied; generating a manifest does not satisfy those gates. Keep Supabase credentials out of the manifest and its output directory.
