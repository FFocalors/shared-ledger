# P2 与 T1 授权、指纹和质量口径兼容审查

状态：只读兼容审查与后续 P2 诊断同步记录；本文不改 frozen T1 文件，也不表示 P2 quality pass。最初审查时未打开 sealed 样本正文、未运行 T1 evaluation、未连接 LM Studio。随后用户仅释放指定 T0 模型资源并批准独立 P2 诊断，root 在两份新 P2 prereg/候选冻结后批准了 17 次合成 fixture 请求；这不是 T1 evaluation，也没有打开 sealed 数据或连接 Supabase。

## 审查边界与输入指纹

审查工作区为 `D:\project\Android\shared-ledger-agent`，branch `agent`，HEAD `1a80a0f29e1ea432a60b95e7437af23d51182938`。Agent checkout 在审查前已有共享 P1/T1 未提交状态；原始审查阶段只新增本文件，后来为同步 C 诊断状态又更新了本文件与 Provider Engineering 文档。业务 checkout `D:\project\Android\shared-ledger` 为 `main`，保持 clean。本轮没有执行 checkout/reset/clean/stash/commit/push。

本审查直接读取的 P2 设计输入：

| 文件 | SHA-256 |
|---|---|
| `agent/docs/p2/CONTRACT-VERSION-DIFF.md` | `4f997a033b4cd7391b55b6970b9d43d8cf3ede396f905611be5c51c8159b1eeb` |
| `agent/docs/p2/IMPLEMENTATION_PLAN.md` | `ae86e10012e9c8662de55a7f612a16ca39c91aff135113f61f83125c143d80d1` |
| `agent/docs/p2/PROVIDER_ENGINEERING.md` | Original review snapshot SHA-256 `e971f9990ac75fcd77709286a466730e2bbc1bfb6b99622bbe2b053ef31117cd`; final C-synchronized note SHA-256 `582D7E1B5C2CB13AD769ADB8889D8F417B9AD7889D240F1134E3E99AC03EF35B`. |
| `agent/app/p2_model_provider.py` | `084611302bb5edb2c29fff986c2e50dd3824c4527b3b2b99ab7f895aeb64beb1` |

T1 审查输入及冻结绑定：

| 文件 / artifact | SHA-256 或绑定值 |
|---|---|
| `agent/docs/t1/README.md` | `fe0c7c4eb3ce5dad8b485feaf370b7cd4b4a71be94846c488d13758e553ce991` |
| `agent/docs/t1/COVERAGE-T1.md` | `46b62b116ce21702fea3f30b8197ab568a7583d287bb70287ddfdc769fb4905a` |
| `agent/docs/t1/MODEL_PREPARATION-T1-v1.md` | `3e0084942cb5662687c2a6ed8cc5e1e9e938e2d88ff1542fab76563281195842` |
| `agent/docs/t1/MODEL_PREREG-T1-v1.json` | `e5699fe99bf9b97f4c52e8ac188ee35256b6f1588c13761baa3013204e3ead08` |
| `agent/docs/t1/FREEZE-T1.md` | `fc3ca21eae1f8fbc10c9180abc4641219b80c9e51705935fb2d09d4a20917c35` |
| `agent/docs/t1/ACCEPTANCE_CRITERIA-T1-v1.json` | `d72ea879b2023a883832f6ffbe181537bfc5d32ff6b8a79a4cb5ec062082f957` |
| `agent/dataset_contracts/t1/protocol-fingerprint.json` | `089fc318d503cff7995ea8fead876c99b97351e334e270c3de17e3d1ee452f50` |
| T1 manifest | `f87eae34f7d77632701ed3fcf1090e1e6a5adedcbe5e39342241a44448f0dddf` |
| T1 root diagnostic approval | `8b5f94329a3c2e7f1c008152ebc440fcb2434c6af32d05da8775307583ae7188` |

Only the above metadata, schema/criteria and documentation were read. The dataset index, manifest and preregistration contain hashes/aggregate metadata; no train, validation, or sealed JSONL sample body was opened.

## Authorization and current T1 status

The T1 root artifact is `APPROVED_DIAGNOSTIC_FREEZE` with `scope=diagnostic_only`; it explicitly says `sealed_consumed=false`, `sealed_one_shot_authorized=false`, and `training_eligible=false`. T1 README and model preparation record model evaluation as `NOT_TESTED_USER_DEFERRED`, no model output, and no evaluator parsing of validation/sealed sample semantics. At the time of the original read-only review, the user had deferred real inference. On 2026-10-11 the user later released resources for the explicitly identified, already-loaded T0 artifact. Root separately approved two new P2-only candidate registrations and exactly 17 synthetic-fixture calls through the OpenAI-compatible route. This later authorization did not alter T1 authority: the T1 diagnostic freeze still has `sealed_one_shot_authorized=false`, and no T1 dataset/evaluation or Supabase/Auth/RLS was used. The 17 P2 outputs are reported in the independent D-only record; the P2 semantic diagnostic gate failed.

T1 contains 111 synthetic envelopes, 37 per split. The diagnostic freeze has at least five fixture-only state families per enabled operation/split, but the formal release floor is at least 20 independent families per enabled operation in both validation and sealed. Current formal status is `INSUFFICIENT_SAMPLE`; 15 potential prompt near-duplicate pairs remain, `human_review_pending=true`, and `training_eligible=false`. This is diagnostic material, not training evidence or a representative user distribution.

The T1 preregistration is frozen before outputs and records `outputs_or_inference=NONE`. Its scope is `diagnostic_baseline_only_no_training`, and its model API is specifically **LM Studio native v1 REST** (`POST /api/v1/chat`, `GET /api/v1/models`), not OpenAI-compatible acceptance. It binds the T0-carried Q4_K_M artifact hash `acfd01df6cbd3c8e1fa4dbe144f5852290689851c4f92d4ab892707d08724b34`, while its exact base snapshot lineage and loaded-key-to-file binding remain unconfirmed. T1 parameters include context length 8,192, output cap 768, temperature 0, reasoning off, parallelism 1, one repair, and timeout 120 seconds. These are specific to that frozen native-route candidate; they do not establish the actual P2 model, API path, context budget, or quality.

The P2 adapter posts to OpenAI-compatible `/v1/chat/completions` and uses the unchanged v1 semantic JSON schema. It, the typed P2 prompt/provenance envelope, Harness, and token-budget adapter are outside the frozen T1 source fingerprint. The T1 preregistration remains a different frozen native-REST (`/api/v1/chat`) candidate and cannot be relabelled as P2 or used to report P2 outputs. P2 now has its own root-approved base and extension fingerprints; 17 synthetic-fixture calls completed and are recorded separately. None of these calls exercised real Runtime/backend reads or Supabase.

## P2 authorization update and finite diagnostic result

The user later authorized only the identified T0 Q4_K_M artifact (SHA-256 `acfd01df6cbd3c8e1fa4dbe144f5852290689851c4f92d4ab892707d08724b34`) to be loaded at context 8,192, then explicitly released the model resource gate. Root reviewed and approved two P2-only candidate bundles before generation: base preregistration SHA-256 `D06B609BB75BC6B7CAE78C983040C48B427D70F4A2D4F1426D27256A0B017F82` with cap64/768/1536 candidate fingerprints, and a separately frozen extension preregistration SHA-256 `13F6C1AA03D610024663CF878622E530DAE161AA1DFDAD52A6EE90F77B44490E` at cap768. They generated exactly 12 + 5 synthetic fixture calls, without retry, repair, prompt adjustment, or backend access.

C finite gate result is **`FAIL_SEMANTIC_DIAGNOSTIC`**: 17/17 HTTP200, 13 nonempty `stop` responses, 4 cap64 empty `length`; 10/17 schema-valid and Harness-accepted; exact expected fixture outcome 0/17; exact operation 0/10 operation-bearing attempts. All six covered operation categories had zero exact selections. The clarify fixture got kind 1/1 but required slots 0/1. Among 13 nonempty outputs, no invented amount/currency, debt direction/settlement, participant, citation, or write-success claim was observed; four length outputs are unassessable, so this is not a safety pass. The false refusals, context contradiction, and unsupported debt-voucher absence assertion are tracked separately. The create-intent fixture omitted fields such as split/allocation/time; its class comparison is diagnostic only and is not evidence of a complete create-task benchmark. Final rendering and Runtime/backend closed loop were not exercised. Exact per-case outcomes, Wilson intervals, hashes, and source snapshots are in `D:\AI\runs\shared-ledger\p2\final-diagnostic-review-20261011-720e9be3b7854e96a8fe31ad7aabfc0d\p2-c-diagnostic-review.md`.

The former sentence that current user instructions still defer all real model inference is historical and no longer describes the C diagnostic authorization. It does **not** release T1 sealed data or Supabase: T1 one-shot authorization remains false and D/Supabase remains `NOT_RUN_USER_DEFERRED`. Root also later observed external T1-file drift (`docs/t1/release-v2/.guide-text.tmp` absent and `evaluation/t1_teacher_probe/probe.py` hash changed); this worker did not create, restore, or modify those files.

## Compatibility with frozen v1

The proposed internal envelope is compatible in principle if it remains a provider/runtime-private Pydantic wrapper around the existing `ModelPrompt`: `context` remains the unchanged `c.ModelContext`, `repair_feedback` remains a bounded string or null, and P2 provenance/supplements are declared typed Pydantic fields. The provider accepts Pydantic envelopes, rejects raw mappings and extra fields, and serializes typed metadata alongside the existing context. Existing `ModelContext.read_results` already carries typed result bodies with result ref, operation, observation time, context version, and simulation marker. The dynamic output schema remains `c.SEMANTIC_DECISION_ADAPTER.json_schema()`, and the Harness remains the semantic parser/repair authority.

That boundary does not change the frozen v1 OpenAPI or the six registered operations **provided that** P2 does not add fields to canonical `ModelContext`, `SemanticDecision`, `ReadOperation`, request/response DTOs, event/checkpoint schemas, or exported contract files. Internal `P2Provenance`/expense supplements can attach opaque fingerprints and richer typed read detail, but UUIDs, token, owner/Turn identity, and raw cursor must remain in the private server resolver. Citation and currency/amount rendering must still be checked against current typed bindings by Harness. Any behavior that requires a new public wait reason, operation, semantic field, persisted continuation token, or canonical response field is a versioned-contract change and needs root/T1 synchronization before export or production wiring.

`p2_model_provider.py` exposes a structural prompt boundary (`context`, `repair_feedback`) and accepts the Runtime/Harness typed `P2PromptEnvelope` with typed provenance and references; it rejects arbitrary mappings. It is assembled through P2 settings/components, while `provider_mode=disabled`, `p2_lmstudio_enabled=false`, and `p2_token_budget_enabled=false` are defaults. Generation fails closed without a configured token-budget checker. `P2ProviderHealth` remains distinct from frozen P1 `ProviderHealth.inference_available: Literal[False]`; provider `ready` follows successful provider completion and is not semantic quality or backend readiness. Root approved its internal Runtime/API mapping; the frozen canonical OpenAPI and frozen v1 provider/contract models were not changed.

## Frozen T1 quality criteria and limits

T1 criteria are a useful **reference vocabulary**, not an existing P2 result. The frozen v1 criteria require exact numerator/denominator and stratification, overall macro and per-operation results, Wilson 95% intervals, and no pooling that hides a weak operation. Their thresholds are:

| T1 metric | Frozen threshold / denominator boundary |
|---|---|
| Schema validity | At least 0.95 over every attempted semantic completion, including invalid outputs and timeouts. |
| Operation choice exact | At least 0.90 for fully specified supported tasks with a non-null expected operation among the six enabled operations; score the first parsed read/propose decision. |
| Required parameters exact | At least 0.90; report each applicable field separately. |
| Typed reference binding exact | At least 0.90 with type, Turn, source, version, and scope binding; separately report missing-reference detection. |
| Supported complete task success | At least 0.90 overall and per operation; requires exact decision/fields, deterministic result consumption, correct final response, and no false refusal. A correct final answer after a successful read does not prove the model selected the read. |
| False refusal | At most 0.05 over fully specified requests supported by frozen v1. |
| Critical errors | Exactly zero; report model attempts separately from Harness blocks. A Harness block is not a model task pass. |
| Duplicate business effects | Exactly zero, applicable only to isolated backend acceptance; T1 simulated replay is `NOT_TESTED`. |
| Single-concurrency P95 | At most 60 seconds under the frozen local Student + LM Studio + Harness config. |
| Timeout rate | At most 0.05 over all attempted generations under frozen single concurrency. |

The T1 evaluator is explicitly teacher-forced stepwise semantic diagnosis: later tool results and contexts are already stored in the trajectory. Its `supported_complete_task_success` is `NOT_EVALUATED` because replay cannot establish model-driven tool use or a complete real backend loop. P2 must not reuse those scores as evidence of backend read selection, result consumption, pagination handling, or answer grounding. The current frozen evaluator and criteria were hashed before any output, but they cover the prior T1 candidate only.

## Required independent P2 fingerprint and diagnostic registration

The first P2 diagnostic outputs were preceded by two separate, versioned P2 candidate registrations under `D:\AI\runs\shared-ledger\p2\`; their independent candidate/source/request/fixture/token-counter bindings and outcomes are listed in the final diagnostic record. The old T1 prereg was not reused. Any future P2 output requires a new approved registration if any bound source, prompt, schema, model, request fixture, or budget changes. At minimum such a record binds:

1. Agent HEAD/branch/dirty-state snapshot and every P2 implementation source that affects the result: provider, Runtime, Harness/envelope/provenance schemas, backend DTO/read implementation, relevant settings and component assembly, and parser/repair code. Record unchanged v1 contract and operation-registry hashes separately as the compatibility baseline.
2. Exact effective system/developer/user prompt template version and hash; typed P2 envelope/supplement schema hash; semantic output schema hash; provider/API mode (`/v1/chat/completions`), structured-output request shape, response parser and repair rules. A change after output creates a new candidate fingerprint.
3. Selected model key plus actual artifact hash/size/quantization and verified loaded-model binding or explicit unverified status; model/context-window limits, endpoint configuration, output cap, temperature, reasoning settings, tokenizer/counting method, timeout, concurrency, and all request/read/repair budgets. Never infer that T1’s 8,192 context value applies to a different endpoint or loaded model.
4. P2 evaluator/scorer source and metric-definition hash, diagnostics’ split and fixture generator/source hashes, the D-only P2 bundle manifest hash and explicit approval scope. Freeze all of this before the first output. The P2 diagnostic trajectory set must independently include the actual tool-selection/result-return/follow-on-turn path and P2-specific scope, pagination, and failure cases.

An existing validation sample can be diagnostic-only only under its stated approval and with the exact old candidate provenance recorded. Once inspected for prompt/schema adjustment it is development evidence, not an untouched P2 validation result. Do not tune against or reopen T1 sealed; its one-shot authorization remains false. If a later P2 sealed evaluation is needed, create a separately frozen P2 bundle and obtain a separate explicit one-shot authorization and atomic consumption ledger before opening it. Do not modify the T1 manifest, preregistration, protocol fingerprint, acceptance criteria, dataset bundles, or evaluation code to retrofit P2.

For meaningful continuity, P2 may copy the T1 metric definitions into a new preregistered P2 criteria version with the same denominators where the semantics truly match, while adding separate end-to-end measures sourced from runtime traces: supported read selected, authenticated read succeeded, actual typed result returned, subsequent call consumed the right complete/fresh result, answer facts/citations grounded to the result, cross-scope/stale refs rejected, and no duplicate read side effects after cancellation/recovery. Report capability limits and sample floors explicitly. Do not label T1 metric thresholds as achieved by CPU tests or by a different candidate/provider route.

## P2 coverage gaps that remain explicit

| Area | Current proposal / frozen coverage | Compatibility gap and required decision |
|---|---|---|
| Continuation and pagination | Root approved and Runtime implements a bounded single-call safe subset: consume all fixed pages, verify stable ordering/range/count/version fences, and expose only a complete bounded result. It does not send cursor to model/Store or return partial data. | Cross-request/restart continuation remains unimplemented and cannot be inferred from the current v1 schema. Any future continuation needs a versioned typed cursor/completeness contract or separately approved private CAS-bound state. Add independent trajectories for page cap, truncation, stale version, and recovery. T1 replay and the provider/Harness probe do not demonstrate backend continuation. |
| Prepayment | T1 records ordinary-activity prepayment as a refusal and large-activity prepayment as unavailable; no frozen v1 read operation covers large-activity accounts/usages. P2 supplement proposal covers payment/split details only. | Do not infer prepayment account balance, usable currency, owner/custodian relation, or usage from `read.debts` or expense facts. If P2 must support prepayment reading, first define authoritative read DTO/operation and version diff with root/T1; otherwise label it unavailable and exclude positive support from P2 quality denominators. |
| Linked refunds | T1 lists restoring actual prepayment usage without mutating the transfer as a future business boundary. Frozen `ModelContext`/ReadOperation does not express a refund/usage ledger or its binding. | No P2 positive answer/coverage may claim linked refund or negative-expense semantics from current v1 reads or a payment supplement. Add exact backend fact shape, provenance, and independently approved P2/T1 coverage before supporting it. |
| Multi-activity scope | v1 `ModelActivityScope` carries one `activity_ref`; no-activity scope can list activity refs but cannot safely represent arbitrary combined activity facts. Current T1 CAP01 simulated reads do not prove a live multi-activity scope-switch loop. | P2 must make the user-selected scope explicit, revalidate membership on each read, fingerprint each scope/query and invalidate prior evidence after switching. Add negative/positive scope-switch fixtures and trace checks; never merge facts across activities by title or similar ref. |
| Input token/context budget | P2 settings bind the selected artifact, loaded model key/path, API origin, context 8,192, max input 6,144, schema count and 512-token margin. An optional SDK 1.5.0 checker uses the loaded model prompt template/tokenizer and fails closed before POST if unverified, over-budget, timed out, or mismatched. It never loads a model. | The checker produced successful count-only preflights for both frozen P2 bundles. This is conservative admission accounting, not proof that endpoint structured-schema grammar overhead or endpoint usage exactly matches the separately counted schema plus margin. Settings are disabled by default; changing model/tokenizer/artifact/origin/window requires a new binding and approved candidate. The T1 context value is not the source of this P2 binding. |

## Root/T1 decisions before any P2 quality claim

1. Preserve the fingerprint method distinction documented below without editing frozen artifacts: the canonical exporter uses normalized source text, while the preregistration records a raw-byte source hash. The read-only snapshot check passes.
2. Preserve the two executed P2 preregistrations and their immutable evidence as a failed semantic diagnostic. Any new P2 output requires a new root-reviewed fingerprint and authorization; no further model call is authorized by this review.
3. Preserve the approved bounded in-call pagination subset as current behavior. A future cross-request/restart continuation remains a separate versioned design decision. Keep prepayment/refund out of claimed support until typed authoritative coverage is approved, and require explicit multi-activity scope fixtures.
4. The selected P2 artifact/window/input/output binding now has a fail-closed SDK token-count admission seam and was verified count-only for the two diagnostic bundles. Keep it disabled by default; do not reuse T1’s native-route fingerprint or silently increase the 768 production output cap. The SDK admission estimate does not establish full runtime/backend acceptance.
5. Keep the root-approved internal P2 health mapping distinct from frozen P1 health and semantic-quality status. Any future AUTH_REQUIRED change remains explicit and must not change v1 exports.

### Fingerprint hashing layers and canonical export check

The frozen T1 protocol-fingerprint.json records app/contracts.py as 4da745eeb218cbd75cff2d30b62b0d895ceb8920c54f463cfa7dce35a1ef5130; the canonical v1 manifest.json records the same value in source_fingerprints. The T1 preregistration separately records agent/app/contracts.py as 9fd214d9d8eb43c6f5b03b1d7e95b2bef274dbf9e8be495f536f495b48a5bf2d, which is the current file's raw-byte SHA-256. A read-only check confirmed the current file's SHA-256 after CRLF/CR-to-LF normalization is 4da745eeb218cbd75cff2d30b62b0d895ceb8920c54f463cfa7dce35a1ef5130. The values therefore reflect different hashing methods, not different source content.

The documented check ran from D:/project/Android/shared-ledger-agent with PYTHONDONTWRITEBYTECODE=1 and agent/.venv/Scripts/python.exe:

    python -m agent.app.export_contracts --check
    contract snapshot matches manifest: D:/project/Android/shared-ledger-agent/agent/contracts/v1.0.0
    exit code: 0

The check compared all 55 generated files and the manifest; it found no generated schema/body drift and no manifest drift. It did not write exports. Stored agent/contracts/v1.0.0/manifest.json raw SHA-256: 9d2d5938373681ab60ccdeb42a10190dd5b136615bce2026e29c94864a9dbca3. Evidence, including command, output, exit code, metadata probe, and hashes, is at D:/AI/runs/shared-ledger/p2/compat-export-check-20261011-7c2e49d9793b4da4a8f40f4d43019ca5; stdout.log SHA-256 is bbaa6b601b509b2670dab8d0893dcd70e095bdf2bcd33d85ec96fa848999ff52.

Keep the frozen raw-byte preregistration hash and normalized protocol/export fingerprint as recorded; do not rewrite either frozen artifact. Future P2 source fingerprints must state their normalization method explicitly. This compatibility check does not establish P2 model behavior or quality.
Review action remains read-only with respect to frozen T1, contracts, exports, datasets, and evaluation; only this owned review file and D-only evidence were updated. The root-owned read-only canonical export `--check` passed with exit 0, and the root/Runtime unified Agent suite passed 248 tests. No sealed body, T1 evaluation, or Supabase request was made. The current conclusion is: **the typed P2 provider overlay preserves the frozen v1 schema boundary, but the separate finite C semantic diagnostic failed (`FAIL_SEMANTIC_DIAGNOSTIC`) and is `INSUFFICIENT_SAMPLE` for general model-quality claims. T1’s old native prereg remains frozen and unused as P2 evidence. Supabase/Auth/RLS acceptance remains `NOT_RUN_USER_DEFERRED`.** The fingerprint-layer difference remains raw-byte versus normalized-text hashing, not a generated contract drift.
