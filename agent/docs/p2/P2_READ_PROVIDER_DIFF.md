# P2 Read Provider integration difference

This change implements the provider-only seam authorized by [ROOT_PROVIDER_INTEGRATION_DIRECTION.md](D:\AI\runs\shared-ledger\p2\root-provider-integration-20261014\ROOT_PROVIDER_INTEGRATION_DIRECTION.md). The direction file SHA-256 is 8545706c7528db8fd448dc4426550019e42cc8361813af24de79a6b3ae19160a. The 129-entry historical source manifest remains untouched; this adds a new, unregistered candidate source difference.

## Baseline

- Existing provider: agent/app/p2_model_provider.py, 33994 bytes, SHA-256 74fd01d0e747deb2ebdb8525c31af3eafd303dda76990ebf6cc29034a3c95384.
- Byte-identical D-only snapshot: D:\AI\runs\shared-ledger\p2\root-provider-integration-20261014\provider-candidate-0ba945413f0645c78c87df110c426688\p2_model_provider.baseline.py.
- Dependency baseline hashes: D:\AI\runs\shared-ledger\p2\root-provider-integration-20261014\provider-candidate-0ba945413f0645c78c87df110c426688\dependency-baseline-manifest.json (SHA-256 193a8a6630b198b445da287335b8049a249ad006ec2f5ae79835169d3e35e67c).
- The candidate provider, target test, and this diff document were absent at preflight. The shared agent tree already had unrelated P1/T1 changes; they are preserved.

## Authorized source delta

1. Keep LMStudioOpenAIProvider.generate's legacy prompt validation, legacy context serialization, v1 request construction, response parser, and compatibility behavior. Extract the existing body-bound admission/dispatch/parse lifecycle into one internal shared method. Both legacy and candidate calls use that method; no duplicate provider copy or global serializer patch is introduced.
2. Add agent/app/p2_read_provider.py as an opt-in, unassembled candidate. It accepts the strict P2ModelContext and P2PreparedRequest, revalidates both, verifies the prepared request against the supplied context and the provider's current model/localhost endpoint/config, and sends the exact original prepared.body_bytes after validation.
3. The shared path constructs its typed token-counter input by parsing the exact body bytes that it will POST. A missing, failed, mismatched, or over-budget real checker measurement is fail-closed and dispatches no HTTP request. A typed receipt alone is never accepted as a substitute for the injected P2TokenBudgetChecker.
4. Preserve the existing one-slot semaphore, JIT validation, cancellation drain, close-before-dispatch fence, HTTP timeout/response-size limits, response parser, and stable disabled/closed/budget/busy/offline/timeout/empty/truncated/JSON error classes. No retry, alternate endpoint, native mode, autoload, runtime registration, or service wiring is added.
5. Add agent/tests/test_p2_read_provider.py for body-to-counter-to-fake-HTTP-to-parser equivalence, no-counter and counter/body-binding refusal, budget refusal without dispatch, cancellation/close/busy/offline cases, and legacy byte/parser regression. All transport and counter fixtures are CPU fakes.
6. This first provider candidate remains restricted to http://127.0.0.1:1234/v1/chat/completions. It does not claim Docker-host configuration, Runtime/Store/API assembly, database reads, source recovery, or formal protocol acceptance.

## Implemented source delta

- `agent/app/p2_model_provider.py` now extracts `_ensure_available()` and `_generate_bound_body()`. The legacy `generate()` retains its serializer and request builder, then calls the common body-bound path. The common path validates optional body SHA-256, rebuilds the typed counter request from those exact bytes, and uses those same bytes for the existing transport. Its single-slot semaphore, JIT checker, cancellation draining, close fences, response parser, and error mapping remain in the shared method.
- `agent/app/p2_read_provider.py` is an opt-in facade around the exact existing provider type. It only accepts the fixed loopback endpoint, structured output, temperature 0, and output cap 768. Each call strictly revalidates the exact `P2ModelContext` and `P2PreparedRequest`, rebuilds the request from the server context and selected model, compares the complete rebuilt object, and sends the original validated bytes through `_generate_bound_body()` with the prepared SHA-256.
- The candidate does not construct a legacy `ModelContext` or `P2PromptEnvelope`. The original P2 version tuple, all context fields, facts, evidence, and continuation hints remain bound in the rebuilt `P2PreparedRequest`. Semantic decision parsing remains a separate `parse_p2_decision(raw, trusted_intent_context)` step; the provider returns only the raw decision content accepted by the existing OpenAI completion parser.
- The module is not imported from application assembly (`rg -n "p2_read_provider" agent/app --glob '!p2_read_provider.py'` returned no matches). This is a provider candidate only; Runtime, Store, API, Docker, database, source recovery, model loading, and formal acceptance are not implemented.

## Verification record

Pre-edit snapshot: `p2_model_provider.py` was copied before edits and matched the source byte-for-byte at 33,994 bytes, SHA-256 `74fd01d0e747deb2ebdb8525c31af3eafd303dda76990ebf6cc29034a3c95384`. Baseline manifest: `D:\AI\runs\shared-ledger\p2\root-provider-integration-20261014\provider-candidate-0ba945413f0645c78c87df110c426688\baseline-manifest.json`.

The focused CPU/fake run passed 66 tests across `test_p2_read_provider.py`, `test_p2_model_provider.py`, `test_p2_read_prompt.py`, and `test_p2_read_contracts.py`. Its captured command and output are in `D:\AI\runs\shared-ledger\p2\root-provider-integration-20261014\provider-candidate-0ba945413f0645c78c87df110c426688\cpu-test-run-002\run.json`. The earlier run is retained as failure history: 27 passed and one test assertion failed because the test treated the frozen counter-message dataclass as a Pydantic model; the assertion was corrected and not hidden or overwritten.

A separate construction-only compatibility probe reported the baseline and current legacy request body identical: 17,874 bytes, SHA-256 `96ad90ce50aa35f96ee8143920569dc8ca1f8b4befbef06e23863a33db34a447`; `sdk_imported` was false. Captured output and command are in `D:\AI\runs\shared-ledger\p2\root-provider-integration-20261014\provider-candidate-0ba945413f0645c78c87df110c426688\legacy-wire-run-001\`.

The verification runtime was Python 3.12.0, Pydantic 2.13.4, and pytest 8.4.2. The new candidate tests use only an injected fake counter and fake transport. The legacy provider regression suite also exercises its existing deadline behavior against a fake localhost TCP HTTP stub (`test_local_http_stub_obeys_one_total_deadline`); it did not contact port 1234 or another live service. No SDK, model, database, or Docker operation was invoked.

## Final source bindings

- `agent/app/p2_model_provider.py`: 35,376 bytes, SHA-256 `1523b75a933c9a4d0431fe8cf003766502ad52bbdf7a502c3fddf365404173f5`.
- `agent/app/p2_read_provider.py`: 4,434 bytes, SHA-256 `9f05e295bd413dd0b6964d74c9f38c2420a5a2e1e2ffa75427a900789e0f5077`.
- `agent/tests/test_p2_read_provider.py`: 10,533 bytes, SHA-256 `b439fdbeeb927e4608fae604903839c93bffb84944e5b991565f9a972032f560`.

The old 129-entry manifest remains historical and was not rewritten to imply source identity after the permitted provider delta. This change adds no registration, app assembly, wire contract, or business data changes.
