# T1 Teacher availability probe

**Measured status (2026-10-11, Asia/Shanghai):** the configured Teacher route passed one constrained protocol canary. A second, three-case language pilot received HTTP 200 but produced an empty completion at the 256-token output ceiling, so it yielded no usable candidate. Teacher dataset quality remains **NOT_ASSESSED**; Student model quality remains **DEFERRED_NOT_TESTED**.

The probe used the existing OpenCode configuration from `D:/project/Android/shared-ledger/scripts/ai_teacher_generator/.env`, loaded in memory only: provider `opencode`, configured model `deepseek-v4.1-flash`, route `https://opencode.ai/zen/go/v1/chat/completions`, and a credential-presence flag. The key was not copied, printed, hashed, or saved. Authorization and response headers were not recorded. A post-run scan found no credential bytes in the external evidence files. The configured route/model and the `TEACHER_STATUS-T1-v1.md` freeze were left unchanged.

The preregistration froze the prompts, non-secret configuration fingerprint, source hashes, session identity policy, and a maximum of two serial POSTs. Each request had a 60-second timeout, `max_tokens=256` (within the 1,024-token ceiling), JSON response mode, the probe's own User-Agent, and one stable `x-opencode-session` value. There were no retries or fallbacks.

| Request | Observation | Result |
|---|---|---|
| 1. Contract sanity | HTTP 200 in 1.594 s; returned model label `deepseek-v4.1-flash`; `finish_reason=stop`; usage 129 prompt / 53 completion / 182 total tokens; server request ID `chatcmpl-b9170975`; exact expected JSON object passed strict parsing. | Protocol/authenticated route canary passed. The model label is provider-reported metadata, not independent proof of model identity. |
| 2. Three-case language pilot | HTTP 200 in 2.781 s; returned model label `deepseek-v4.1-flash`; `finish_reason=length`; usage 428 prompt / 256 completion / 684 total tokens, including 256 reasoning tokens; server request ID `chatcmpl-cb70471a9ca54500822bbbd93b233550`; visible completion content was empty. The response envelope had a `reasoning_content` field; its value was not inspected or copied into the analysis. | No parseable candidate and no semantic result. The reasoning-token count reached the configured output ceiling before visible completion text was returned. This records output-budget behavior and is not a model-quality judgment. The two-request budget was exhausted, so no retry was sent. |

The first response demonstrates that the configured endpoint accepted the request and returned usable JSON, finish metadata, usage, and request identity. It does not establish quota, future availability, general model identity, Teacher data quality, or model behavior beyond this canary. Request 2 returned transport metadata but no completion text, so its business semantics were not assessed. No Teacher batch, Student inference, database access, or business write occurred.

The original run manifest records request 2's content-parse failure but omits its outer-envelope metadata because the parser stops when the completion content is empty. The offline envelope review binds to the raw response SHA-256 and records only status metadata, token counts, empty-content length, and whether the `reasoning_content` field exists. It does not inspect or copy that field's value or retain visible completion text. Both records and the raw responses are preserved for review.

Preregistration SHA-256: `745d636051726935fcc697d46783dbebf203ba623e73b05abcd8fb7e7359d8ba`.

Evidence directory: `D:/AI/runs/shared-ledger/t1-teacher-probe-20261011/`. The in-repository evidence index is `agent/evaluation/t1_teacher_probe/evidence/summary.json`; the raw-hash-bound metadata-only supplement is `agent/evaluation/t1_teacher_probe/evidence/offline_response_analysis.json`. Eight fake-HTTP tests passed before the live requests; they do not make network calls.
