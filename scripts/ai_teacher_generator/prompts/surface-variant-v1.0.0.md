# Shared Ledger Surface Variant Prompt v1.0.0

You generate one candidate language Surface Form for an already frozen synthetic business scenario. You are not allowed to create or revise any business truth.

## Immutable anchors

- `locked_business_facts`, `locked_expected_output`, execution policy, result references, and supplied conversation/context are read-only anchors. They are provided only so the wording remains semantically faithful.
- Do not calculate, infer, round, split, convert currency, resolve an entity beyond the supplied anchors, or change any amount, title, person, date, currency, split, entity, intent, tool, result, evidence, proposal, diff, confirmation, authorization, or execution state.
- Do not add entities, server/tool results, result IDs, UI facts, bindings, recent actions, turns, or confirmation events. Do not invent missing information.
- Preserve the supplied conversation turn count, order, IDs, and roles. You may rephrase turn content only when it retains exactly the same meaning. Preserve ambiguity and clarification needs.
- Respect the locked output type: proposal remains a preview-only proposal with the same diff/confirmation semantics; clarification stays clarification; tool_call, answer, and unsupported remain their same branch. You are generating wording only, not a model output.
- Keep the requested difficulty and context profile. Vary expression through register, ASR-like wording, pronoun/ellipsis, or an existing multi-turn continuation as requested. Never create variety by merely swapping a person, amount, date, or title.
- Never mention or emit Dataset, Gold Seed, Family, Scenario, Sample, training, evaluation, prompt, teacher, run, or other production metadata. Do not echo IDs or the locked output.

## Output contract

Return exactly one JSON object with exactly one top-level property named `surface_form`. Its value must have exactly these keys: `language`, `register`, `conversation`, `context_turn_count`, `user_message`. Use `language="zh-CN"`; register must be `neutral`, `colloquial`, `asr_like`, or `mixed`; preserve the seed conversation turn IDs and roles; `context_turn_count` must equal its length. Do not return explanations, business facts, expected output, tools, IDs, or extra keys.
