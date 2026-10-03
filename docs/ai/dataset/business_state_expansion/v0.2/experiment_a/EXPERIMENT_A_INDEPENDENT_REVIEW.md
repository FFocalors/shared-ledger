# Experiment A Independent Review

**Verdict: `V0_2_EXPERIMENT_A_READY_FOR_FREEZE`.** This review leaves the packet `draft` and `unassigned`; it does not itself freeze or approve the data. Frozen v0.1 files were not modified.

Initial issue-level findings: **0 BLOCKER, 4 MAJOR, 3 MINOR**. The MAJOR findings were H's old train duplicate and hidden creator fact, G's incorrect object binding, Catalog intent misclassification in B/E/F, and the insufficient literal-only grounding claim. The MINOR findings were indistinguishable B candidates, D's stale proposal boundary/relative date, and incomplete holdout wording. All seven are fixed; unresolved findings: **0**.

All 16 Scenarios were independently re-derived from frozen Business Logic, AI Contract, Intent Catalog, Scope and Schema. Each adds a decision boundary or a missing fact combination; identity, amount and wording changes alone did not count. H previously repeated the unique selected-target L2 proposal already present in frozen train (`scenario_gs_p0a_012`, `scenario_gs_p0b_019`). It now presents two complete verified `find_expenses` rows with no selected target and requires clarification before a delete proposal. Distribution is **7 clarification, 5 proposal, 3 tool_call, 1 answer**.

Six contrastive groups form 11 pairs: currency sufficiency (1), participant lookup/cardinality (6), payer binding (1), Activity target (1), recent-action reference (1), and L1-vs-D4 field semantics (1). Each expected decision follows from model-visible input. B's Context is equal after removing only its typed lookup result and verification IDs; C changes only `claimed_participant_id`; E's input is identical except `recent_actions`.

All six `NORMALIZED_DUPLICATE` warnings are **intentional reviewed contrasts and retained**: B multiple/zero/unique (3), C payer binding (1), D current Activity (1), E recent-action state (1). Their visible result/UI/claim/action facts are sufficient; no hidden metadata supplies the distinction.

Grounding was recomputed from actual `export_record(sample)` input-only messages: **102/102 Expected external facts have visible sources; missing source = 0**. Complete typed result bodies are present. Object-bound checks confirm B result Participant→proposal ID, E recent entity→`get_expense` arguments, F verified DTO→actual payer answer, G selected UI ID→DTO→write target, and H result rows→clarification candidates.

Clarification, proposal and tool boundaries are stable. Missing values and unresolved identity clarify; Supporting Lookup is read-only and preserves business intent; writes produce proposals; L1 icon update carries its confirmation requirement; D4 carries complete before/after and `execution_allowed=false`; a multiple-match L2 delete cannot be proposed before selection. The 16 Chinese surfaces are natural, avoid contract language and answer leakage, and preserve intended ambiguity.

The future policy closes family, split-group and semantic-state counterparts; assigns once at future freeze; uses validation only for scheme selection; seals fresh test/hard_test until the scheme is fixed; and treats v0.1 test/hard_test as historical diagnostic/regression only. No product decision is unresolved.

Final verification: frozen Schema Validator **valid**, 16 Scenarios, 16 Samples, 8 Families, 0 errors, 6 reviewed warnings; metadata leakage **0**, serialization round-trip **16/16**, duplicate full model inputs **0**. All 30 source hashes and 4 manifest artifact hashes match. Machine-readable decisions and pair details are in `independent_review.json`.
