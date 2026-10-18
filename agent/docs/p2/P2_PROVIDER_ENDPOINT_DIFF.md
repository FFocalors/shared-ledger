# P2 Provider endpoint/config version difference

This is the concrete implementation note for the endpoint-only candidate delta authorized by `ROOT_ENDPOINT_IMPLEMENTATION_DIRECTION.md` (SHA-256 `e3e93b5045000f1ca1474743495899f734970c6bbd9c7a70447493992c6e71e7`). The read-only baseline snapshot is under `D:\AI\runs\shared-ledger\p2\provider-endpoint-implementation-20261014\baseline`; all copied current files matched their source SHA-256 before this document was created.

The accepted provider candidate remains an unregistered, default-off engineering candidate. This change does not add a fifth protocol version: the existing four-version tuple, seven read operations, decision schema and request body format stay as-is. The engineering wire-config and candidate provider identifiers will advance from `p2-read-chat-completions-config-v1` / `p2-read-openai-chat-completions-candidate-v1` to `...-v2` because the frozen prepared metadata now carries a validated endpoint binding. Prompt text is unchanged; `P2_PROMPT_VERSION` remains unchanged unless its source text changes. The prepared body SHA continues to cover only the exact canonical JSON body.

## Endpoint policy

One stdlib-only helper will validate and normalize the completion URL, derive its origin and expose the SDK authority. Accepted hosts remain exactly case-insensitive `localhost`, loopback IPv4/IPv6 literals and exact `host.docker.internal`. It will not resolve DNS, follow redirects, use a proxy, accept a caller-supplied target, or fall back between names.

Accepted URLs use HTTP and exact `/v1/chat/completions`, with no credentials, control/whitespace, backslash, percent-encoded authority/path, query delimiter, fragment delimiter, or trailing/extra path. The host must be one of the allowlisted identities. Scoped/zone IPv6 is rejected. IPv6 literals must use brackets in the URL. Host case and IPv6 hex case are normalized to lowercase; IPv6 remains bracketed. An omitted port means HTTP port 80 and canonicalizes to explicit `:80`; explicit `:80` has the same identity. Other explicit ports are decimal integers 1 through 65535; empty ports, zero, out-of-range values and noncanonical decimal spellings such as `:01234` are rejected. This intentionally rejects ambiguous edge spellings while leaving the default `127.0.0.1:1234` bytes/profile unchanged. Host identities are never rewritten: `localhost`, `127.0.0.1` and `host.docker.internal` remain distinct, even if they reach the same process.

The checker-origin parser accepts only an explicit normalized HTTP origin with no route path, credentials, query or fragment. The shared helper returns the exact origin and SDK authority from the same parsed endpoint. Existing config strings may keep their supplied spelling for legacy transport compatibility; prepared metadata and checker bindings use the helper's canonical endpoint/origin. Equality is defined by these normalized parsed values, not by DNS aliasing.

## Config and request binding

`P2PromptBuildConfig` gains server-only `endpoint_url`, defaulting to the existing `http://127.0.0.1:1234/v1/chat/completions`. Strict config revalidation runs the helper. `P2PreparedRequest.endpoint_url` becomes a strict validated string, not a widened unchecked `Literal`; its validator requires canonical equality with `config.endpoint_url`. `build_p2_request` takes no untrusted endpoint and constructs a fresh prepared request from the typed context plus server config. It does not mutate a validated instance. The JSON body and its canonical serialization remain byte-identical for the same context/model/limits.

An internal fingerprint is derived from canonical endpoint, model id, wire-config version, provider version and `request_sha256`. It records route identity that is intentionally outside the OpenAI request body. It is engineering metadata, not a protocol version. The accepted four-version protocol tuple and seven operations do not change.

`P2ReadProvider` checks the wrapped provider config, selected model and prepared endpoint against the same normalized binding, then rebuilds a fresh request from the typed context and compares the full immutable prepared object. Any mismatch fails before count or HTTP. It calls the existing `_generate_bound_body` with the exact `prepared.body_bytes` and `prepared.request_sha256`. The counter's typed messages/schema/model/output cap continue to be derived from those exact bytes; the transport receives those unchanged bytes. No copied provider, replacement serializer, URL monkeypatch or second body construction is introduced.

## Shared origin and artifact invariant

Provider endpoint, prepared endpoint, checker binding, token request, measurement and POST must agree:

- `normalize(P2PreparedRequest.endpoint_url) == normalize(LMStudioOpenAIConfig.endpoint_url)`;
- the shared endpoint parser's `origin` equals `P2ModelArtifactBinding.lmstudio_api_host`, `P2TokenBudgetRequest.api_host` and `P2TokenBudgetMeasurement.api_host`;
- the server `model_id`, prepared body `model`, provider `model_key`, artifact binding `model_key`, token request model and currently loaded SDK model identity agree;
- context messages, response schema, output cap and body SHA are taken from the exact prepared bytes; a host/model/body mismatch or unverified/over-budget counter prevents POST.

`components.py` will replace its duplicated endpoint-to-origin formatting with the shared helper only. It continues assembling the legacy provider path and existing settings. No Settings field or candidate-enable flag is added. `P2ReadProvider` remains unregistered and not imported by default components. Runtime/adapter integration remains separate because current `P2Runtime.generate` consumes a legacy envelope while `P2ReadProvider.generate` consumes a typed P2 context plus prepared request.

`P2ModelArtifactBinding.artifact_path` remains the absolute local file path the counter process hashes. `lmstudio_model_path` remains the exact path string reported by the LM Studio SDK. `lmstudio_api_host` remains the explicit network origin. These are three different bindings and are not rewritten into one another.

## Targeted CPU-only coverage

A new helper suite and targeted provider/prompt/token-budget/component tests will cover:

1. Allowed defaults and `host.docker.internal`, loopback IPv4/IPv6, localhost, case normalization, IPv6 brackets, omitted/default port normalization and exact-origin equality. Assert default legacy request bytes and parser behavior remain unchanged.
2. Rejection of arbitrary DNS names, trailing-dot aliases, private/public non-loopback IPs, HTTPS, credentials, empty/invalid/noncanonical ports, zone-scoped IPv6, malformed IPv6, URL whitespace/backslash/percent escape, query/fragment even when empty, and wrong/extra paths.
3. Fake counter-to-body-to-POST identity: counter origin equals prepared/provider origin; typed model/messages/schema/output cap match the body; POST URL is the configured allowed endpoint; POST body is exactly the prepared bytes.
4. Prepared/config/provider/model/origin mismatch, tampered body/fingerprint, missing checker and fake over-budget measurement all fail before fake POST. No cross-origin count reuse.
5. Existing one-slot, close-before-dispatch, cancellation drain and fake busy/offline behavior still pass. The accepted legacy local TCP stub remains identified as a CPU simulation; it is not a live LM Studio or external HTTP call.
6. Default assembly has no `P2ReadProvider` import/registration and performs no SDK import, endpoint probe or model load.

No test in this scope may import the LM Studio SDK or make a socket request to a service. A fake injected transport and fake counter are the only candidate seams.

## Explicit limits

The accepted provider candidate and historical 129-source manifest remain intact as history; this implementation is a separately bound source delta. It does not perform an exact token count, reuse prior 13-count evidence or V6's 10 model outputs, issue a model request, or authorize generation. A fresh endpoint-bound source manifest, candidate fingerprint, exact request cohort and token-only count are required later. A source-compatible business-quality cohort needs its own fresh fixture/source binding as well.

`host.docker.internal` configuration is only a code-level allowlisted route. No container namespace, Docker networking, bind mount or artifact visibility was exercised. A future container checker must use absolute `artifact_path` and counter Python paths that exist inside its own runtime, with verified mount bytes/hash; `lmstudio_model_path` must stay the exact SDK-reported host-model path. No path translation or container readiness is inferred here.