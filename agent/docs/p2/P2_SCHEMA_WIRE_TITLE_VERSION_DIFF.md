# P2 title-only schema wire candidate: version difference and compatibility boundary

Status: **READY_CPU_PROTOTYPE_PENDING_ROOT_INTEGRATION_REVIEW**. This document describes a proposed, opt-in P2 provider wire renderer. It does not activate that renderer and does not authorize application integration.

## Decision boundary

The proposal is narrowly limited to removing `title` annotations from recognized JSON Schema nodes in the provider's P2 typed-envelope `response_format`. It preserves the canonical contract, its validation semantics, exports, parsers, registry, and the six existing operations (three read operations and three proposal operations). It does not change prompt instructions or business facts. The byte reduction is measured; token savings are unknown, and no model behavior equivalence is claimed.

The existing canonical P2 schema remains the default. P1 `ModelPrompt` remains canonical even when a P2 wire selection is configured. The P2 title projection is a separately versioned, explicit opt-in candidate. The default prompt version remains `shared-ledger-p2-routing-r2`.

This proposal does not adopt or activate the separately reviewed T1 v1.1 offline profile. That profile remains disabled. No T1 dataset body or evaluation was read or run for this prototype. The receipt and review records below are provenance bindings supplied and previously verified by root; this document does not claim a new full receipt or evidence verification.

## Version boundary

| Surface | Existing behavior | Proposed candidate behavior |
| --- | --- | --- |
| Canonical schema/adapter and semantic validation | v1 in `agent/app/contracts.py` | unchanged; renderer makes a provider-wire copy only |
| Exports, parsers, registry, six read/proposal operations | current canonical v1 | unchanged |
| P1 `ModelPrompt` | canonical schema | canonical schema regardless of P2 selection |
| P2 typed envelope | canonical schema; no renderer opt-in | projected schema only when explicit `P2SchemaWireSelection` is configured |
| Wire selection/config | implicit canonical behavior | proposed `p2-wire-config-v2`; `schema_wire_selection: P2SchemaWireSelection | None = None` means canonical by default |
| Schema renderer | canonical v1 | `p2-json-schema-title-strip-v1` |
| Provider version | `p2-lmstudio-openai-v1` | candidate `p2-lmstudio-openai-v2-schema-renderer-v1` |
| Prompt version | `shared-ledger-p2-routing-r2` | candidate `shared-ledger-p2-routing-r3-schema-title-v1`; instructions and business facts remain byte-for-byte unchanged |
| Response format name | `shared_ledger_semantic_decision_v1` | retain canonical name; selected tuple and candidate fingerprint identify the renderer |

The proposed candidate identifiers are not active settings. With canonical selection (`None`), existing canonical custom provider/prompt labels and previously valid canonical configuration values must retain their existing compatibility. Do not impose the candidate tuple's strict allowlist on the canonical path. With the title renderer selected, validate the complete approved wire-config, renderer, provider, and prompt tuple together; reject unknown or mixed tuples before constructing or sending a provider request.

The provider must choose projection based on the actual typed `P2PromptEnvelope` passed to `generate`, never on dictionary shape, prompt text, or a heuristic. P1 `ModelPrompt` must use canonical bytes in every configuration. Keep `_build_request`'s private default canonical so existing callers remain compatible. Construct one request body and use its exact `response_format` both for token-budget counting and HTTP dispatch; no separate accounting renderer may drift from the dispatched body.

## Prototype evidence and limits

The D-only CPU package is `D:\AI\runs\shared-ledger\p2\schema-wire-title-prototype-20261012T1419Z-9575090a72ad42398f4652d5d4db54cc`. Its candidate fingerprint is `5c79686c250fdb2db9cf0e831e7b2aa07b6b92621b7e75927e47a591602375a2`. The canonical source `contracts.py` hash bound by that run is `9fd214d9d8eb43c6f5b03b1d7e95b2bef274dbf9e8be495f536f495b48a5bf2d`.

The run preserved all validator keywords, references, required fields, four semantic branches, three read operations, and three proposal operations. It tested 19 fresh synthetic fixtures: 8 positive, 8 schema-negative, and 3 Pydantic-only cross-field negatives. It recorded 38 JSON Schema decisions, 19 Pydantic adapter decisions, 17 resolved references, and 3 adversarial walker fixtures. This establishes CPU projection parity for those fixtures only.

The bare schema measured 14,018 bytes before and 12,292 bytes after projection. The complete response-format wrapper measured 14,124 and 12,398 bytes, respectively, a decrease of 1,726 bytes. Seventy-eight schema-node titles were removed. Token count, budget fit, API/provider schema acceptance, P2 model behavior, and T1 compatibility remain unverified.

A first byte-accounting attempt failed because the runner compared the bare-schema serialization against response-format wrapper sizes (exit code 1; assertion reported expected 14,124/12,398 but observed 14,018/12,292). The original source snapshot, raw log, and timestamp for that failed attempt are unavailable; the observed failure is documented in the D-only append-only clarification and is not reconstructed as a separately captured run. The later recorded CPU attempt passed with exit code 0. No retry of the earlier token-budget failure and no model/provider generation occurred.

The prototype's statement that frozen T1 v1 sources were hash-checked is bounded: it refers to the supplied 126-entry checkout input inventory, whose before/after aggregate digest matched. It is not a new full T1 v1/v1.1 receipt, source-set, preregistration, or evidence-bundle verification. The frozen inventory input SHA-256 was `d2cc8f6f20ea3f6726200208527e1276592e59faad7e36ea5008c3c2de120201`, and the before/after aggregate was `83b61d8e4887206f2a435dadf1e3468f9d61a128dcd8d62cad437bafa38d3bf0`.

## T1 and canonical provenance

The following hashes are supplied review bindings. Root previously verified the T1 freeze receipt; this version note does not reread or reverify its full contents:

| Record | SHA-256 | Scope of this reference |
| --- | --- | --- |
| T1 freeze approval receipt `ROOT-FREEZE-APPROVAL.json` | `352dcba6cce50c249709be37ba96fd2427b43958406ec570fb5cd2a183ea2036` | Root-verified historical receipt binding only; no new receipt claim |
| `T1_V1_1_P2_ADOPTION_REVIEW.md` | `003c3229027dbd6b532806459a88dad90b6f7e4dddbffcc3f27b799a1374a549` | Existing adoption review; offline profile remains disabled |
| `P2_V1_1_PROFILE_VERSION_DIFF.md` | `b0a1c8dea83c6f0f1f87934cedbf968b7b2bdce5b9c4e34f385d0e73bf2c57c7` | Existing profile/version review; not adopted by this proposal |
| Current canonical `contracts.py` source | `9fd214d9d8eb43c6f5b03b1d7e95b2bef274dbf9e8be495f536f495b48a5bf2d` | Source bound by CPU prototype |

Any future T1 impact review may use schema metadata and a read-only canonical export comparison, without opening T1 dataset bodies. A P2-backed T1 fixture, if separately authorized later, must bind the selected version tuple and receive its own parity review. Nothing here claims T1 v1.1 profile compatibility or changes the separate profile's disabled state.

## Required future integration boundary

No application or test file has been edited for this candidate. Integration remains blocked pending both the container synthetic diagnostic/source-freeze checkpoint and generation-runner current-source CPU evidence checkpoint, followed by a separate root integration decision. The present status is prototype readiness only.

If separately approved, the implementation should be limited to a new helper, P2 provider/config wiring, narrowly scoped P2 tests, and version documentation. It must leave canonical `contracts.py`, exports, P1 request serialization, prompt instructions, business facts, and default versions unchanged. Request counters and dispatch must consume the same serialized request body. Rollback is to set `schema_wire_selection=None` and use the existing canonical P2 schema path and prior canonical versions; no contract migration, registry change, export rewrite, or prompt repair is part of rollback.


## Approved CPU implementation checkpoint — 2026-10-12

This append supersedes the preceding “no application or test file has been edited” status as of the timestamp below. Root's limited implementation authorization is `D:\AI\runs\shared-ledger\p2\schema-wire-title-prototype-20261012T1419Z-9575090a72ad42398f4652d5d4db54cc\ROOT-SCHEMA-INTEGRATION-DECISION.json` (SHA-256 `7a1001cd9a048831fe61d00e7666d5e3da741f4dfabf3810fdc8cb19780d9a03`). It binds the approved prototype helper (`cdf5e731a76d7bd97789a20b5a3dc612e8602b023250d067b7b85a387550e631`), integration plan (`a079fee7939fa2874bc5a6e156173de52e9482c6ed88258df39abd1affbc2551`), and prior version document hash (`b5c82de75914ed054baa66478e77802696cfb3cac8a630381029ba3b166579e2`). This document's pre-append bytes are retained in the D-only implementation package; its prior SHA remains available for prefix comparison.

The CPU implementation adds `agent/app/p2_schema_wire.py`, adds the optional `schema_wire_selection: P2SchemaWireSelection | None = None` to the P2 provider configuration, wires projection only for an actual `P2PromptEnvelope`, and adds `agent/tests/test_p2_schema_wire.py`. The new config field follows the existing positional `api_token` parameter to preserve existing positional construction. `_build_request(..., schema_wire_selection=None)` remains canonical by default. The selected tuple must match the wire-config, renderer, provider, and prompt versions above; mixed or unknown selected versions fail closed. Canonical `None` continues to accept existing custom canonical provider/prompt labels. Even with the P2 selection configured, a P1 `ModelPrompt` uses the canonical schema. The system instruction string, business facts, response-format name, contract, parser, registry, exports, and six operations are unchanged. The provider creates one serialized body; the token budget request is extracted from that body and HTTP dispatch receives the same body bytes.

The final synthetic CPU tests cover all four semantic branches, all three read operations, all three proposal operations, required/extra fields, enum/reference-pattern/bounds/union negatives, `$ref` validation, Pydantic-only cross-field rejection, wrapper/property/`$defs` title-key traps, unknown extension/default payloads, input non-mutation, mixed-version rejection, P1/P2 selection, positional config compatibility, and exact response-format parity between budget accounting and dispatch. On 2026-10-12, the new/focused command passed 76 tests (exit 0), the full Agent suite passed 309 tests (exit 0), and `python -B -X utf8 -m agent.app.export_contracts --check` passed with “contract snapshot matches manifest” (exit 0). Full commands, timestamps, interpreter/dependency versions, stdout, and hashes are bound in the D-only implementation evidence package `D:\AI\runs\shared-ledger\p2\schema-wire-title-integration-20261012T150842Z-46b4310dad9745e086c6c460d76657dd`.

The first full-suite invocation omitted the checkout root from `PYTHONPATH` and failed collection with eight `ModuleNotFoundError: No module named 'agent'` errors (exit 2). That attempt is preserved as-is; the corrected invocation set `PYTHONPATH=..` from `agent/` and passed. The earlier response-format byte-accounting failure and historical token-gate failure remain preserved. Neither was retried or relabeled by this implementation. No token counter candidate, SDK, LM Studio/model, API, Docker, Supabase, Teacher, training, or T1 evaluation was run. Token savings and budget fit remain unknown; model behavior equivalence, provider/API schema acceptance, and T1 compatibility remain unverified.

The pre-change source inventory still has 126 entries. Within that bounded inventory, only `agent/app/p2_model_provider.py` is intended to change; the helper, focused test, and this appended version checkpoint are separately declared additions/updates. This 126-entry frozen-source binding is not new full T1 v1/v1.1 receipt or evidence verification. The separately reviewed T1 v1.1 offline profile remains disabled; no T1 dataset/evaluation body was read or executed. The current canonical v1, P1 serialization, contract output, parsers, registry, and six operations remain the rollback baseline. Rollback is to construct the provider with `schema_wire_selection=None`; no contract or prompt-source rollback is required.

Status: **IMPLEMENTED_FOR_CPU_REVIEW; MODEL/TOKEN/T1/API ACCEPTANCE NOT TESTED; ROOT INTEGRATION REVIEW REQUIRED BEFORE ANY NEW TOKEN CANDIDATE.**
