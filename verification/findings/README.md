# Verification Findings 索引

本页索引 `verification/findings/` 中的报告与候选快照，并指出当前 disposition。历史报告正文保留扫描当时的状态；发生冲突时，以报告开头的“复核后裁定”、结构化文件的 `post_review_resolution` 及本索引为准。这里记录验证证据，不取代 `docs/backend/BUSINESS_LOGIC.md` 作为业务规则来源。

## MASS500

| Artifact | 当前状态 / disposition |
| --- | --- |
| [MASS_VERIFICATION_500.md](MASS_VERIFICATION_500.md) | 已完成并复核。MASS500-001 已修复并有本地回归；002 为 DOCUMENTATION_AMBIGUITY / NOT_A_BUG；003、004 为可观测性/数值表示问题，无资金算法缺陷。 |
| [business_bug_candidates_500.json](business_bug_candidates_500.json) | 历史候选快照；每项最终状态以 `post_review_resolution` 为准。四项均已处置，无待确认业务 Bug。 |
| [MASS500_001_FIX.md](MASS500_001_FIX.md) | MASS500-001 修复记录；迁移 `20260925133211_fix_negative_expense_base_debt_allocation.sql`，专项测试及完整本地回归记录通过。 |
| [multi_payer_aa.md](multi_payer_aa.md) | 早期已确认业务 Bug 的历史证据；原币债务污染已由 v1.1 记录的 migration 修复并回归。旧 FAIL 保留为历史，不是当前未解决 finding。 |

## MASS2000

| Artifact | 当前状态 / disposition |
| --- | --- |
| [MASS_VERIFICATION_2000.md](MASS_VERIFICATION_2000.md) | 扫描完成且已人工/Agent 复核。001 DOCUMENTATION_AMBIGUITY；002 NOT_A_BUG；003 DOCUMENTATION_AMBIGUITY。三项均不要求业务代码修改。 |
| [business_bug_candidates_2000.json](business_bug_candidates_2000.json) | 原扫描候选快照；当前结论以每项 `post_review_resolution` 为准。无遗留已确认业务 Bug。 |
| MASS2000-N01 | JUDGE_FALSE_POSITIVE：预存账户不能抵扣 owner 对第三方债务。 |
| MASS2000-N02 | JUDGE_FALSE_POSITIVE：Final Settlement 一次执行完整建议项的规则被 Judge 误读。 |
| MASS2000-N03 | JUDGE_FALSE_POSITIVE：金额计算、退款方向及源债务/当前双边债务语义误判。 |
| MASS2000-N04 | ENVIRONMENT：Judge 响应内容被拦截；Runner 已完成，不是数据库业务失败。 |
| MASS2000-N05 | WORKFLOW，已修复：repair Loader 失败终态混入上次 attempt 状态；Loader INVALID 不再进入 Runner。对应生成/执行代码与离线回归已纳入当前冻结提交。 |
| MASS2000-N06 | WORKFLOW，已修复：小额 `multiple_repayments` plan 无法表达两次正还款；金额/份额约束与离线回归已纳入当前冻结提交。 |
| MASS2000-N07 | BAD_SCENARIO / 已知验证限制：Final Settlement plan 偶发假设服务端必有指定项目或退化；不是业务实现缺陷，尚不代表该生成器限制已修复。 |

## Workflow 建设与早期验证记录

| Artifact | 当前状态 / disposition |
| --- | --- |
| [BATCH_VERIFICATION_STAGE1.md](BATCH_VERIFICATION_STAGE1.md) | 历史 Stage 1 报告：管线可运行，但 30 个 case 只有 3 种场景且 focus 契约不合格；后续由 Coverage Framework 和 Mass Pipeline 取代，不作为当前覆盖完成证据。 |
| [COVERAGE_FRAMEWORK.md](COVERAGE_FRAMEWORK.md) | Coverage contract 阶段报告；其设计被 MASS Pipeline 使用，计数是历史快照。 |
| [MASS_PIPELINE.md](MASS_PIPELINE.md) | MASS 执行框架阶段报告；后续 MASS500/MASS2000 批次报告是实际业务扫描结果。 |
| [SMOKE_JUDGE_REVIEW.md](SMOKE_JUDGE_REVIEW.md) | v0.2 六项 Smoke Judge 的历史复核；六项在其记录的业务基线上均正常调用并 PASS，不替代 MASS500/MASS2000 裁定。 |

## 当前总 disposition

- 已确认的 `multi_payer_aa` 与 MASS500-001 数据库业务缺陷均已修复并有回归证据。
- MASS500-002/003/004 与 MASS2000-001/002/003 已完成规则裁定或可观测性分类；没有待修业务代码缺陷。
- MASS2000-N05/N06 的 Workflow 缺陷已修复；MASS2000-N07、MASS500 历史参与者漂移、MASS2000 refund-boundary 金额漂移/focus miss/投影可观测性问题保留为明确的验证限制。
- 两轮批次内唯一有效数为 456 与 1572，合计 2028；没有跨批次内容去重证据，不能声称全局唯一数为 2028。
- 详细冻结结论和范围见 [BUSINESS_LOGIC_FINAL_REVIEW.md](../../docs/backend/BUSINESS_LOGIC_FINAL_REVIEW.md) §13。
