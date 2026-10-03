# P0 Gold Sample Production v0.1 — 最终独立审核与修复报告

> 状态：**FINAL INDEPENDENT REVIEW + IN-PLACE FIX**。本轮完整审核 95 Samples / 53 Family，**直接修复**了发现的普通数据问题并重新全量复验。未生成新 Sample，未调用 Teacher 或任何模型 API，未开始 SFT/QLoRA，未提交 Git。
> 对象：`docs/ai/dataset/gold_seed/v0.1/p0/`（`samples.json` 95 条、`scenarios.json` 54 条、`dataset_manifest.json`、`README.md`），并回溯 `p0a/`、`p0b/` 权威 Scenario 与 `P0_FINAL_REVIEW.md`。
> 基线：BUSINESS LOGIC `1.2` / AI Contract `0.1.2` / AI Scope `0.1` / Dataset `0.1`；SHA `55fb28a7c0660462e5842e2eb5c71cfa763e5801`。

## 1. 初审发现（修复前）

结构层先全量复测了一遍，**全部通过**：traceability（0 条缺 scenario）、Ground Truth 逐字节一致、`expected_diff` / execution / evidence 与 Scenario 一致、`surface_form.user_message == input.user_message`、`context_turn_count` 与 conversation 长度一致、exact/normalized duplicate 均为 0、42 个多样本 Family 的表述互不相同、13 个 Task 类型齐全、`page_type`/`form_mode` 均在冻结枚举内、`enabled_tools` 对 8 条 D4 Sample 正确排除 `update_expense`、pending-policy 两条保持 `unassigned` 且 `execution_allowed=false`、FIN-002 无 Sample。

业务与上下文层发现 **2 项 MAJOR + 4 项 MINOR**：

| # | 级别 | 发现 |
| --- | --- | --- |
| **F1** | **MAJOR** | **`user_context` 在 95 条中全部为空**（`claimed_participant_id=null`、`role_hint=unknown`），而其中 **26 条**的 Ground Truth 把"我"解析为 Participant `…103`。即：**"我→participant_id"的绑定无法从输入推出**，且与 P5／Validation Rules §9（"我"必须映射到已认领 Participant）冲突——照此训练会教出"无认领也自行认定我是谁"的错误行为 |
| **F2** | **MAJOR** | **数据集生产标识出现在模型可见输入中**：`client_context.app_version="gold-seed-synthetic-fixture-0.1"`（95 条）、`ui_context.screen_instance_id="screen-sample_gs_p0_NNN"`（88 条）、`conversation_context.conversation_id="conversation-scenario_gs_p0a_NNN"`（95 条）、`page_state.draft.draft_id="draft-sample_gs_p0_NNN"`/`"draft-ictx-006-1"`（5 条）。属训练元文本/夹具溯源泄漏 |
| F3 | MINOR | Sample 094 的表述畸形：`"请直接把张三欠我的500 CNY改成500。"`（500 改成 500） |
| F4 | MINOR | 契约/指令语体混入用户话语：033 `"…按读取结果解释。"`、087 `"…写入之前还缺哪一步授权？"`、091 `"…财务版本不一致…不会覆盖新状态？"` |
| F5 | MINOR | Sample 065 的用户话语自带系统侧的消歧提示（`"活动里的林和周都可能指得上"`），把本应由模型推理的候选集写进了输入，削弱该 Family 的代词测试 |
| F6 | MINOR | Sample 060/061 打了 `missing_payer` 标签，但付款人姓名在 Scenario 中已明确给出（真正的难点是**同名实体**歧义） |

**未发现**：Ground Truth 漂移、Tool Path 错误、proposal/diff 错误、弱 Evidence、幽灵实体、模型自行计算账务、split leakage、训练元文本出现在 `model_output` 中。

## 2. 已执行的修复

| 修复 | 内容 | 影响条数 |
| --- | --- | --- |
| **R-F1** | 为 Scenario 中确实存在"我"Participant 的记录绑定 `user_context.claimed_participant_id`，并置 `role_hint="member"`；`user_id` 仅在 Scenario 声明了 user 实体或 `current_user_id` 时填写。**`scenario_gs_p0b_024`（ENT-002，"未认领的我"）按家族语义保持 `claimed_participant_id=null`**，仅补 `user_id` 与 `role_hint` | 40 条绑定 + 2 条按语义保持未认领 |
| **R-F2** | `app_version` → `"1.4.0"`；`screen_instance_id` → 优先采用 Scenario 已记录的值，否则用由 sample_id 决定的稳定 UUID；`conversation_id` / `draft_id` → 稳定 UUID。全部去标识化，不含任何 dataset 名称 | 95 + 88 + 95 + 5 |
| **R-F3** | 094 改为 `"请直接把张三欠我的钱改成 500 CNY，别走正常记账流程。"` | 1 |
| **R-F4** | 033/087/091 改写为自然用户语体（保留原意与业务参数） | 3 |
| **R-F5** | 065 改为 `"帮我看看他欠我的那部分现在还剩多少。"`（保留代词歧义，删除系统侧提示） | 1 |
| **R-F6** | 060/061 移除不准确的 `missing_payer` 标签，保留 `same_name_entity`/`multiple_candidates`/`colloquial` | 2 |
| — | 同步更新 `dataset_manifest.json` 的 `samples.json` SHA-256（`ce570de7…` → `0a90794f…`），使 Manifest 与实际文件一致 | 1 |

**未改动**：任何 Scenario、任何 `expected.model_output` / `expected_diff` / execution / evidence 绑定、任何 Tool 参数与 diff、任何 Validator 逻辑。修复全部落在 Sample 的输入侧字段与表述，**Ground Truth 一字未动**（复验：95 条 GT 与 Scenario 逐字节一致）。

**未采用"削弱校验"的做法**：没有为了让数据通过而放宽 Validator；F1/F2 是修数据，不是改规则。

## 3. 修复后全量复验（本轮自跑）

| 检查 | 结果 |
| --- | --- |
| Dataset Validator（`validate dataset docs/ai/dataset/gold_seed/v0.1/p0`） | **54 scenarios / 95 samples / 54 families；0 errors / 0 warnings** ✓ |
| Validator 单测 | **45/45 OK** ✓ |
| Examples 回归 | **PASS**（3 条既有 duplicate/semantic-group warning） ✓ |
| `git diff --check` | 干净（仅 LF/CRLF 提示，非错误） ✓ |
| Ground Truth fidelity（95 条 vs Scenario） | 0 处不一致 ✓ |
| `expected_diff` / execution / evidence 绑定 | 0 处不一致 ✓ |
| `surface_form.user_message == input.user_message` | 0 处不一致 ✓ |
| duplicate（exact + normalized） | **0** ✓ |
| 我→Participant 绑定 | GT 用到"我"的 26 条**全部已绑定**，0 条悬空 ✓ |
| 模型可见输入中的 dataset 标识 | **0**（仅余业务结果 id，见 §5 R-1） ✓ |
| `page_type` / `form_mode` 冻结枚举 | 0 违规 ✓ |
| `verified_result_ids` 接地 | 0 处无来源 ✓ |
| Manifest 计数与 SHA-256 | 与记录和文件一致 ✓ |

## 4. 逐条覆盖情况

95 条按 Family 分组逐条审读（Surface Form 全文、Context Envelope、Expected Output、challenge_tags、register、多轮与 ASR/typo 变体均逐条核对），分布：proposal 23 / clarification 30 / tool_call 12 / answer 28 / unsupported 2；CORE 83 / GATED 12；difficulty easy 12 / normal 53 / hard 28 / ood 2；13 个 Task 类型全部有覆盖；register 含 32 条 colloquial、2 条 asr_like，其余 neutral；10 条携带多轮对话、8 条携带 recent action、50 条使用具体页面上下文。

**同 Family 多样本差异**：42 个多样本 Family 中，第二表达均为**句式/指代/语序/口语化**的真实改写（如 `"山野午餐 90 CNY，我在 2026-09-12 12:30 付款，和李四 AA。"` ↔ `"中午那顿山野午餐记90元，我先付，和李四一人一半，时间是9月12日12点半。"`），无一处仅替换姓名或金额；ASR/typo 变体（014 `"桌油"`、077 `"呃……就按那个，那个来吧。"`）保持原意与歧义强度。

## 5. 残留观察（不阻塞，属 Scenario 层或设计选择）

| # | 观察 | 判断 |
| --- | --- | --- |
| R-1 | 模型可见输入中仍可见 `result-exp-edit-003-read`、`result-ictx-003-verified` 等**业务结果 id**，其命名含 Family 代码 | **不改**：这些 id 由 Canonical Scenario 记录、并被 Ground Truth 的 `evidence_result_ids` 引用；改名会切断 Scenario↔Sample 追溯与证据绑定。它们是业务世界的合成服务端标识，不是数据集生产溯源。建议留待未来 Scenario 修订时统一 |
| R-2 | 39 条 `claimed_participant_id` 已绑定但 `user_id` 仍为 null（对应 P0-B Scenario 未声明 user 实体） | **合规**：Validation Rules §9 要求的是 *Participant* 绑定，且明确"User ID 不能替代 Participant ID"；`user_id` 只是提示、由 Gateway 按 JWT 复核 |
| R-3 | `scenario_gs_p0a_013` 自身记录的 user_message 即 F3 的畸形表述（Sample 层已改，Scenario 未动） | 不影响其 `unsupported` Ground Truth；建议未来 Scenario 修订时一并顺句 |
| R-4 | 068/069/072/073 的 answer 不引用 result id | **正确**：这四条回答的是"待确认方案是否已保存"，本身无需读取服务端结果 |
| R-5 | 058/059 标 `interaction_context` 但不带 `recent_actions`，而是携带 `page_state.draft`（旧草稿失效正是该 Family 的交互证据） | **正确**：交互证据是草稿与屏幕实例变化，不是最近动作 |

## 6. FIN-002 状态（确认保持）

- **无 FIN-002 Sample** ✓（95 条中 `scenario_id=scenario_gs_p0b_015` 的记录数为 0；未为凑成 96 而制造数据）。
- `scenario_gs_p0b_015` 维持 `SYNTHETIC_UNVERIFIED / business_validated=false / draft / unassigned`，无 GOLD 治理，不导出、不训练 ✓。
- 未伪造 `suggestion_id`，未虚构 Gateway 结果 ✓；安全澄清分支（"没有可核对的服务端结算建议时只澄清"）保留，Gateway 落地后另增真实建议支撑的 proposal 分支 ✓。

## 7. 结论

### 7.1 统计

| 项 | 数量 |
| --- | ---: |
| 审核 Sample | **95 / 95**（逐条，另回溯 54 Scenario） |
| 修复前 | 0 BLOCKER ／ 2 MAJOR ／ 4 MINOR |
| 修复后 | **0 BLOCKER ／ 0 MAJOR ／ 0 MINOR**（5 项残留观察见 §5，均不阻塞） |
| 实际修改文件 | `p0/samples.json`（95 条中的 40+95+88+5+5+2 处字段）、`p0/dataset_manifest.json`（1 处 SHA-256） |
| 修改的 Ground Truth | **0** |

### 7.2 系统性问题判定

**不存在系统性生产问题，本轮不需要退回上游。** 修复前发现的两项 MAJOR 都是**字段级/夹具级**问题（一个缺失的上下文绑定、一组带生产标识的夹具字段），可在 Sample 层就地修复，不涉及 Ground Truth、不涉及生产方法、不需要产品决策；其余 93 项机器检查与全部业务语义检查一次通过。生产方法的判别力也被反向证明：Validator 的 45 项检查与 3 条 examples warning 都按预期工作，未出现"为了让数据通过而需要放宽规则"的情形。

### 7.3 治理建议

- **可治理为 `reviewed`**：95 条已通过本轮独立审核（含逐条 Surface Form、Context、Expected Output 与变体核对），且发现的问题已就地修复并复验。建议由维护者将 `trust.surface_form_reviewed` 置为 `true`、`lifecycle_status` 由 `validated` 推进为 `reviewed`。
- **`approved` 建议暂缓一步**：`approved` 在 Dataset Schema 中要求"人工业务审核或被认可的确定性来源"，而 Surface Form 的自然度属人工判断，且本轮"审核"与"修复"由同一执行者完成。建议由维护者或第二名审阅者对 **Surface Form 自然度**做一次签认后再置 `approved`；这不影响数据本身的可用性。
- Scenario 侧维持现状（53 条 `GOLD/reviewed`，FIN-002 除外）。

### 7.4 最终裁决

```text
READY_FOR_P0_GOLD_SEED_FREEZE
```

依据：95 Samples / 53 Family 全部通过独立业务审核与机器复验（0 errors / 0 warnings，单测 45/45，examples PASS，`git diff --check` 干净）；Ground Truth 与 Scenario 逐字节一致；Context / Evidence / Tool Path / Proposal / D4 / Clarification 全部稳定；Surface Form 自然度与 Family 内多样性合格；无 duplicate、无 leakage、无训练元文本（模型可见输入中无 dataset 标识）；FIN-002 按要求保持排除。本轮无任何未解决的 BLOCKER/MAJOR/MINOR。

## 8. 本轮边界

未生成任何 Sample；未调用 Teacher、DeepSeek、OpenCode 或任何模型 API；未开始 SFT/QLoRA；未修改任何 Scenario 的 Ground Truth、Contract、AI Scope、Catalog、Model Output Schema、Dataset Schema、Validation Rules、Coverage Matrix 或 Validator 逻辑；未提交 Git。本轮唯一新增文件是本报告，另有上述 2 个数据文件的就地修复。
