# P0-B Canonical Scenario Batch (v0.1)

本目录包含 39 条合成 Canonical Scenario。依据独立终审报告 [P0_FINAL_REVIEW.md](../P0_FINAL_REVIEW.md)，38 条已治理为 `GOLD`、`business_validated=true`、`reviewed`；FIN-002 保持 `SYNTHETIC_UNVERIFIED / false / draft / unassigned`。95 条 Gold Sample 保存在同级 `p0/`，其中 P0-B Family 贡献 38 条 Sample；FIN-002 配额排除。Canonical Scenario 仍是唯一 Ground Truth。

## Production method and checks

Each row was matched to the latest Coverage Matrix by `family_id`; intent, scope, task, difficulty, and challenge shape remain traceable to that row and the frozen Catalogs. Each `user_message` is a distinct business request, and every monetary/date/participant argument is captured with its stated or read source. UI, interaction, and conversation tags have corresponding state facts. Evidence references resolve to substantive frozen Business Logic or Contract passages. Supporting Lookup state records the tool, query, source, and result cardinality; the zero-result case does not invent a target entity.

### Content Authenticity Preflight

Every record also follows the seven checks in the [production method](../p0a/README.md#content-authenticity-preflight): business-utterance input; user-facing output without Family/training metadata; business titles and queries without workflow labels; scenario-specific assertions; resolvable and substantive evidence; no unused declared entities; and rule tags consistent with output and recorded context. The Validator mechanically rejects exact metadata reuse, fixed workflow terms, recognizable empty evidence lines, unused entities, duplicate assertions, and context tags without corresponding state facts. Naturalness, factual relevance, candidate sufficiency, actual Activity/permission fit, and whether the context truly supports the output remain human Preflight items.

Before acceptance, the batch was checked for Family traceability, version baseline, unique IDs, argument mirrors, entity declarations/references, recorded-fact shape/source/duplicates, tool-scope role, output protocol, evidence resolution, and proposal/execution policy. The Validator does not replace the required independent business review of Ground Truth adequacy.

## Traceability

| Coverage Matrix P0 Family | Scenario ID | Scope | Primary task | Intent(s) | Expected output | Tool path (`scope.tool_ids`) | Difficulty |
|---|---|---|---|---|---|---|---|
| `EXP-CREATE-005` | `scenario_gs_p0b_001` | CORE | `proposal_generation` | `create_expense` | `proposal` | `create_expense` | `easy` |
| `EXP-CLARIFY-002` | `scenario_gs_p0b_002` | CORE | `clarification` | `create_expense` | `clarification` | — | `normal` |
| `EXP-CLARIFY-007` | `scenario_gs_p0b_003` | CORE | `parameter_extraction` | `create_expense` | `clarification` | — | `normal` |
| `EXP-EDIT-003` | `scenario_gs_p0b_004` | CORE | `proposal_generation` | `update_expense`, `explain_error` | `proposal` | `update_expense` | `hard` |
| `EXP-EDIT-004` | `scenario_gs_p0b_005` | CORE | `proposal_generation` | `update_expense_presentation` | `proposal` | `update_expense_presentation` | `easy` |
| `EXP-READ-001` | `scenario_gs_p0b_006` | CORE | `parameter_extraction` | `find_expenses` | `tool_call` | `find_expenses` | `normal` |
| `ACT-002` | `scenario_gs_p0b_007` | CORE | `tool_call` | `query_activity` | `tool_call` | `get_activity_context` | `easy` |
| `DEBT-002` | `scenario_gs_p0b_008` | CORE | `tool_call` | `query_bilateral_debt` | `tool_call` | `get_debt` | `normal` |
| `PRE-CORE-003` | `scenario_gs_p0b_009` | CORE | `result_explanation` | `explain_prepayment`, `explain_rule` | `answer` | `lookup_business_rule` | `normal` |
| `TRF-002` | `scenario_gs_p0b_010` | SUPPORTED_BUT_GATED | `result_explanation` | `create_settlement_transfer`, `explain_error` | `answer` | `get_debt` | `normal` |
| `PRE-GATED-004` | `scenario_gs_p0b_011` | SUPPORTED_BUT_GATED | `clarification` | `create_prepayment` | `clarification` | — | `normal` |
| `REF-001` | `scenario_gs_p0b_012` | SUPPORTED_BUT_GATED | `proposal_generation` | `create_refund` | `proposal` | `create_expense` | `normal` |
| `REF-002` | `scenario_gs_p0b_013` | SUPPORTED_BUT_GATED | `clarification` | `create_refund`, `create_negative_adjustment` | `clarification` | — | `hard` |
| `FIN-001` | `scenario_gs_p0b_014` | SUPPORTED_BUT_GATED | `tool_call` | `query_final_settlement`, `explain_final_settlement` | `tool_call` | `get_final_settlement` | `easy` |
| `FIN-002` | `scenario_gs_p0b_015` | SUPPORTED_BUT_GATED | `proposal_generation` | `execute_final_settlement` | `clarification` | — | `normal` |
| `DEL-002` | `scenario_gs_p0b_016` | SUPPORTED_BUT_GATED | `result_explanation` | `delete_expense`, `explain_rule` | `answer` | `find_expenses` | `hard` |
| `UI-001` | `scenario_gs_p0b_017` | CORE | `ui_context_reasoning` | `explain_expense` | `answer` | `get_expense` | `normal` |
| `UI-002` | `scenario_gs_p0b_018` | CORE | `ui_context_reasoning` | `update_expense` | `proposal` | `update_expense` | `normal` |
| `UI-003` | `scenario_gs_p0b_019` | SUPPORTED_BUT_GATED | `ui_context_reasoning` | `delete_expense` | `proposal` | `delete_expense` | `normal` |
| `ICTX-001` | `scenario_gs_p0b_020` | CORE | `entity_resolution` | `update_expense` | `proposal` | `update_expense` | `normal` |
| `ICTX-002` | `scenario_gs_p0b_021` | CORE | `clarification` | `update_expense_presentation` | `clarification` | — | `hard` |
| `ICTX-003` | `scenario_gs_p0b_022` | CORE | `interaction_context_reasoning` | `find_expenses` | `answer` | `find_expenses` | `normal` |
| `ICTX-006` | `scenario_gs_p0b_023` | CORE | `interaction_context_reasoning` | `create_expense` | `clarification` | — | `hard` |
| `ENT-002` | `scenario_gs_p0b_024` | CORE | `entity_resolution` | `query_participant_balance`, `create_expense` | `clarification` | — | `normal` |
| `ENT-003` | `scenario_gs_p0b_025` | CORE | `entity_resolution` | `query_bilateral_debt`, `query_participant` | `clarification` | `find_participants` | `hard` |
| `CONV-001` | `scenario_gs_p0b_026` | CORE | `conversation_context_reasoning` | `create_expense` | `proposal` | `create_expense` | `hard` |
| `CONV-004` | `scenario_gs_p0b_027` | SUPPORTED_BUT_GATED | `conversation_context_reasoning` | `create_expense`, `create_settlement_transfer`, `unsupported_request` | `answer` | — | `normal` |
| `CONV-006` | `scenario_gs_p0b_028` | CORE | `conversation_context_reasoning` | `query_debt` | `tool_call` | `get_debt` | `hard` |
| `CONV-007` | `scenario_gs_p0b_029` | CORE | `result_explanation` | `create_expense` | `answer` | — | `normal` |
| `CLR-001` | `scenario_gs_p0b_030` | CORE | `clarification` | `clarify_reference` | `clarification` | — | `hard` |
| `CLR-002` | `scenario_gs_p0b_031` | CORE | `intent_classification` | `unknown` | `clarification` | — | `ood` |
| `CLR-005` | `scenario_gs_p0b_032` | CORE | `clarification` | `create_expense` | `clarification` | — | `normal` |
| `RULE-001` | `scenario_gs_p0b_033` | CORE | `rule_qa` | `explain_rule` | `answer` | `lookup_business_rule` | `normal` |
| `RULE-003` | `scenario_gs_p0b_034` | CORE | `rule_qa` | `explain_rule` | `answer` | `lookup_business_rule` | `easy` |
| `RULE-004` | `scenario_gs_p0b_035` | CORE | `rule_qa` | `explain_rule` | `answer` | `lookup_business_rule` | `normal` |
| `RULE-005` | `scenario_gs_p0b_036` | CORE | `rule_qa` | `explain_rule` | `answer` | `lookup_business_rule` | `normal` |
| `RULE-006` | `scenario_gs_p0b_037` | CORE | `error_handling` | `explain_error` | `answer` | `lookup_business_rule` | `normal` |
| `RULE-007` | `scenario_gs_p0b_038` | CORE | `error_handling` | `explain_error` | `answer` | `lookup_business_rule` | `hard` |
| `RULE-008` | `scenario_gs_p0b_039` | CORE | `error_handling` | `explain_error` | `answer` | `lookup_business_rule` | `normal` |

## Coverage summary

- Scenarios: 39; unique Family IDs: 39.
- Scope: CORE 30; SUPPORTED_BUT_GATED 9; DEFERRED 0.
- Expected outputs: answer 14, clarification 12, proposal 8, tool_call 5.
- Recorded lookup cardinalities: unique 2, multiple 1, zero 1.
- Proposal levels: L1 6, L2 2; D4 preview-only 3. All D4 proposals have complete before/after diffs and `execution_allowed=false`.
- Recorded context: 8 UI-tagged, 4 interaction-tagged (each with recent action state), and 5 conversation-tagged scenarios; one scenario has both conversation and interaction tags. Pending proposal and confirmed binding fields are populated only in the corresponding recorded turn state.
- `ICTX-003` is a genuine zero-result path: the recent Expense write is recorded as failed, then `find_expenses` finds no matching 78 CNY metro-ticket Expense; the answer does not claim it was saved.
- REF-001 uses a negative Expense and `original_expense_id` sourced from a `get_expense` result for the positive original record. FIN-002 does not invent a suggestion ID: it asks for the current server suggestion to be loaded and keeps the record `SYNTHETIC_UNVERIFIED`.
- 38 条已通过独立终审并治理为 GOLD/reviewed；FIN-002 是唯一保留的合成未验证澄清场景，未生成 Sample、不导出、不训练。

## GOLD_SEED_BLOCKER

`GOLD_SEED_BLOCKER-FIN-002`: frozen `execute_final_settlement` requires a Gateway-bound `suggestion_id` from `get_final_settlement`; the repository has no implemented Gateway or captured result containing that bound identifier. Contract and Catalog do not permit deriving the identifier from chat or recalculating a suggestion. This Scenario therefore remains the safe missing-suggestion clarification, `SYNTHETIC_UNVERIFIED`, `unassigned`, and excluded from Gold Sample eligibility. It does not block independent review or eventual Sample eligibility of other records. After Gateway implementation, add a separate FIN-002 proposal-branch Scenario backed by the real bound server suggestion; do not overwrite this clarification case.

## Validation

All 39 P0-B Scenarios pass the offline Scenario Validator with zero errors and zero warnings. The combined P0 batch now contains 54 reviewed Scenarios and 95 Samples (0 errors/0 warnings); P0-A/P0-B standalone scenario checks, 45 Validator tests, and Examples also pass. Examples retain three existing duplicate/semantic-group review warnings. Samples remain machine-validated and pending independent surface review; none is final approved. FIN-002 remains excluded from Gold Sample production.
