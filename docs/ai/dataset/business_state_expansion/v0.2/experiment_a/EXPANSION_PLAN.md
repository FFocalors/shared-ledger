# Business State Expansion v0.2 — Experiment A Plan

Status: independent review complete; recommended `V0_2_EXPERIMENT_A_READY_FOR_FREEZE`. Governance has not frozen or approved the packet. No Sample is assigned a split or made training-eligible.

## Decision-state basis

The frozen train split contains 171 Samples but only 36 canonical Scenarios, 36 exact Ground Truth outputs, and 36 business-state hashes (65 Gold and 106 Teacher surfaces). Teacher surfaces therefore add expression/context forms, not distinct decision states. The existing train set already exercises candidate clarification, read routing, L1 creation, L2 deletion, L1 presentation-only update, and D4 non-executable financial update. This experiment adds boundary contrasts that those separate examples do not pair: the minimum trusted fact that changes clarification to proposal, verified lookup cardinality that changes the next action, claimed-participant binding, UI target resolution, recent-action success/entity state, allowed-vs-disabled update field semantics, and a multiple-result delete lookup that must clarify before any L2 proposal. It also adds a verified answer for the actual payer ID, distinct from the train answer about split responsibility.

Validation-only pattern summary (24 rows; no test or hard-test case inspection for design): 24/24 have structured field mismatches; 12/24 are schema-invalid; 10 have unexpected output fields; 9 have entity-resolution discrepancies; 9 have UI-context discrepancies; 5 have tool-argument and 5 tool-selection discrepancies; 4 have output-type routing mismatches; all 3 expected proposal rows route to clarification. This motivates state-level decision contrasts and explicit model-visible source paths, not copying old held-out cases.

## Planned minimum

The minimum sufficient first batch is **16 distinct business-decision states, 16 human-authored Surface Samples, and 8 new Family/split-group closures**. This is not a language-variant quota. Each state has its own Scenario and Canonical Ground Truth. Paired/triad states share a new Family and split group so that the eventual frozen splitter cannot leak contrastive states across splits. All Scenarios and Samples remain `unassigned`; no final split is assigned in this experiment.

| New Family closure | States | Contrastive decision | Output coverage |
| --- | ---: | --- | --- |
| expense currency sufficiency | 2 | Same expense request; currency absent vs explicitly supplied. Only the supplied currency turns the otherwise complete request into a proposal. | clarification, CORE L1 proposal |
| participant Supporting Lookup | 4 | Same requested payer: lookup not yet performed → read-only Supporting Lookup; zero/multiple verified results → clarify; exactly one verified candidate → proposal bound to that participant. | tool_call, clarification, proposal; unique/multiple/zero |
| current-user binding | 2 | Same “I paid / only I bear it” request; claim binding absent vs current Activity Participant explicitly claimed. | clarification, CORE L1 proposal |
| Activity UI target | 2 | Same expense read query; no unique Activity target vs one active/selected Activity. | clarification, read-only tool_call |
| recent action reference | 2 | Same request for the recent expense; failed action without entity vs succeeded action with exactly one expense entity. | clarification, read tool_call |
| verified expense read | 1 | One answer whose title and original amount/currency come from a typed, verified `get_expense` result payload visible in the frozen runtime Context serializer. | answer, one data-quality control |
| expense update semantic boundary | 2 | Same existing expense; requested presentation-only icon change vs financial amount change. This changes the requested field semantics: the former is L1-confirmable, the latter is D4 preview-only and non-executable. Both before-values come from the visible verified expense read. | L1 proposal, D4 proposal |
| gated delete | 1 | A verified lookup returns two same-title expenses and no target is selected; the model must ask which one before it can form a GATED L2 delete proposal. The old train already contains the unique selected-target L2 proposal state, so this batch does not repeat it. | clarification before L2 proposal |

The byte-level user request may be identical within a contrastive closure when the changed authoritative Context fact is the decision trigger. The samples are not duplicates of the same target: each has a different Context state and/or output. The group-level audit records exactly which single semantic fact changes and why.

## Grounding and source rules

All user-supplied amounts, dates, currency, requested field changes, titles and names are recorded as `user_input` facts. UI route/current Activity/selected entities and visible candidates are recorded as `ui_context` or `user_selected`; current-user identity is grounded only by the actual claimed Participant field. Supporting Lookup candidates and verified expense payloads use the frozen typed Tool Result envelope, matching `verified_result_ids` and exact result IDs. Recent-action decisions use only the serialized `recent_actions` status/entity/result tuple. D4 before-values are copied exactly from the recorded `get_expense` server result and the model-visible serialized Context. No hidden Scenario state or `evidence_refs` is treated as model input.

Only current Contract and Catalog paths are enabled. Primary writes remain proposals with the frozen L1/L2 confirmation fields. Supporting Lookup is read-only L0, keeps its business Intent, and never authorizes execution. `update_expense` remains D4 preview-only (`execution_allowed=false`, reason `d4_atomic_update_not_supported`); it is not injected in `enabled_tools`. FIN-002 is excluded. No settlement suggestion, Gateway, API result, or training status is fabricated.

## Governance and validation

The new records use Dataset Schema/Validator v0.1 unchanged, SILVER trust, `business_validated=false` on Scenarios, `ground_truth_locked=true` only as a Sample-to-Scenario binding, `surface_form_reviewed=false`, `draft` lifecycle, `example_only=false`, and external `training_eligible=false`. They remain draft and unassigned; the independent review is complete but governance status has not advanced. Family and split-group IDs are fresh, synthetic, and visible only in dataset metadata; they are excluded by the existing training serializer.

The independent-review packet contains Scenarios, Samples, the exact decision/state source map, expected-to-serialized-input grounding audit, contrastive-pair audit, coverage comparison against train’s 36 states, schema/Contract validation, serialization dry-run traces, and source/manifest hashes. The reviewed output distribution is 7 clarification, 5 proposal, 3 tool_call, and 1 answer after correcting the old duplicate L2 proposal into a new multiple-match clarification state. No fresh split is assigned. Future splitting must apply existing Family + split-group + semantic-state closure once, with all contrastive counterparts together.

An unresolved or ambiguous product rule will be marked as a product decision blocker and omitted from publishable candidates; Dataset rules, Contract, Scope, Catalog, serializers and schemas will not be relaxed or changed to force a target.
