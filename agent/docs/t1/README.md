# T1 数据与评估索引

**release-v3 候选（2026-10-19）：**四个 RBR 项已全部落到新版本并跑完可跑的 gate。新 source freeze（27 文件，含 git head、快照与 v1.1 manifest 绑定）；新候选 417 条（train/validation/sealed = 143/137/137，即 v2 形状 + 12 条原币 RBR04 覆盖行 + 12 条 base 币覆盖行）；RBR01 3 条、RBR02 414 条、RBR03 56 条、RBR04 24 条。RBR01——三条空结果读样本的回答改由冻结的可信 renderer 生成并引用 `query_1`，两条 `backend_zero`、一条 `post_filter_zero`（后端确返回 5 条、被 title 后置筛选清空），两者不会再混淆；证据的四个绑定轴全部走冻结 v1.1 字段，信封把 `page_complete`/`range_contiguous`/`stable_total_verified`/`source_version_fenced`/`unique_items_verified` 钉成 `true`、`has_more`/`truncated` 钉成 `false`，任何行都无法在不完整覆盖下声称「无匹配」。RBR03——56 条歧义澄清改用已返回事实列候选、用日期+金额选择，不再出现裸 `expense_ref`，提案与目标 ref 不变。RBR04——按「覆盖缺失而非算法缺陷」补 24 条案例。**AA 量子裁定（已按后端源码写入版本记录）：原币 `splits.amount` = 0.0001 量子（`p_original_amount * 10000`），base 币 `splits.base_amount` = 0.1 量子（`base_amount * 10`），两者是不同列、不是二选一；生成器保留原币 0.0001 分摊，base 列另行补齐。**base 案例覆盖 B01 原例 100.0/3 → 33.4/33.3/33.3、10.0/6 → 1.7×4/1.6×2，以及「原币有尾差、base 无」（150.01/6：原币 25.0017×4/25.0016×2，base 25.0×6）与「外币两列都有尾差」（100.00 EUR @7.10 → 原币 33.3334/33.3333/33.3333，base 236.7/236.7/236.6）；每列按各自量子核对守恒。**落库语义**：创建时 base 尾差给最后一人，但每次 create/update/delete/restore 与修复路径都会调用 `redistribute_aa_split_base_amounts` 覆盖为「前 N 人各 +1」，训练数据存的是后者，转换器会拒绝「最后一人兜底」形状；`payments.base_amount` 仍保留最后一人补差（该迁移只重分 splits）。RBR02——所有已转换行的模型输入与原始用户请求逐字相同。验证：417 行全部通过 release-v3 信封；写入的 414 个工具观测全部逐字节重放一致；family 计数 18 项恰为 20、read.expenses 为 24（新增 4 个 base family/split）；`pytest agent/evaluation/t1_release_v3/tests -q` = 40 passed、既有 `t1_release/tests` = 122 passed 不变；改生成器后全量可读候选仍与冻结 v2 零 mismatch（135/129），三份 v2 载荷哈希不变。近似项分析已覆盖全部三个 split（5,429 组，按区分维度分类：55 组跨 operation、5,374 组独立 state family）；该版本初次标注为 `assistant_technical_review`，**2026-10-20 已由独立 root 会话 01a1582f 复核确认（5,429 组确认、0 组修正）并重签为 `root_agent`**，详见下方更新。新 train-only packet 34 条已建（覆盖全部 RBR 项，pending receipt 模板已写好）。两次准备各用独立 run root（2026-10-19 保留为历史、不复用；本次为 `t1-release-v3-20261020`），新 freeze 不复用旧 receipt。两个交接包已生成：`review/handoff/independent-near-pair-review/`（5,429 组分析，已脱敏、附 re-issue 流程，明确标注非 `root_agent` 裁定）与 `review/handoff/human-receipt/`（packet + pending receipt + 签名校验脚本）。P2 已记录 `ACCEPTED_LIMITED_P2_READONLY_ENGINEERING_BASELINE`（2026-10-19，只读工程基线，明确未做独立复核），可作为准入输入但仍需 T1/root 记录。

**仍未准入：**collection gate 仍不通过（near-pair 已由独立 root 确认，剩余阻塞为 boundary-gold 运行时错误与 genuine human receipt）；`human_reviewed=false`、`human_review_pending=true`、sealed 未写出、`training_eligible=false`。三项外部门本工作做不到也不需要假装做到：genuine human receipt 需真人，P2 baseline calibration 属 P2 验收，T2 授权是你的决定。另有一项待你裁定的语义问题：生成器按 0.0001 量子分摊，而记录的**后端**规则按 0.1 最小单位顺序分配（100.0/3 → 33.4/33.3/33.3），新版本应采用哪套会改变所有行的份额值。旧 393 候选与全部旧 receipt 保持字节不变。详见 [release-v3 转换记录](release-v3/README.md)。

**near-pair 复核更新（2026-10-20）：**独立 root 会话 01a1582f 重建全部 417 行、校验 5,429 组的四条哈希绑定并抽查 103 组，确认 5,429 组、修正 0 组。`near_pairs.py` 的审阅身份已改为 `root_agent`，据此重建的 run root 为 `D:\AI\runs\shared-ledger\t1-release-v3-20261020-root-01a1582f\`；候选内容与载荷哈希未变。collection gate 仍未通过，阻塞项为 boundary-gold 的 `BaselineError`（`untrusted preloaded module blocks pinned baseline import: agent.app`）与 genuine human receipt；`training_eligible=false`、sealed 未写出。交接包中的 `assistant_technical_review` 标签是其生成时点的状态记录，不再代表当前审阅身份。

**协议状态（2026-10-12）：**protocol v1.1.0 离线合成协议冻结已批准；25 PF、22 package tests、46 root probes、17 independent export checks、10 schemas、5 examples、36 outputs。Root receipt SHA-256 352dcba6cce50c249709be37ba96fd2427b43958406ec570fb5cd2a183ea2036，manifest SHA-256 5665565eb503c16e5e8c8ca6cb207743ee52e5add1b0b27c7aeca8cc3a6a80c3；见[协议](protocol-v1.1.0/PROTOCOL.md)、[root review](protocol-v1.1.0/ROOT_REVIEW.md)和[最终receipt](file:///D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-review-20261012/ROOT-FREEZE-APPROVAL.json)。这是离线协议门，CAP01–CAP17执行与外部写入仍关闭，T1数据准入和训练未完成；genuine human review、P2 calibration、T2授权pending，Student评估延期，training_eligible=false。下一步须fresh source freeze和新candidate，修复RBR01–04并重跑Gold/replay/near/split及人审；旧111/393候选和receipt不改、不复用。

**当前状态（2026-10-11）：**旧版t1-synth-1.0.1仍是独立获批的111条合成诊断集，仅用于诊断。新版release-v2候选已写入D盘，共393条（train/validation/sealed为135/129/129）；schema、Gold/replay检查零失败，exact duplicate/state leakage为零，18个operation×split family counts均为20，root对4,984组near findings均有技术处分。Root最终复核34条train-only包：业务文字、金额、范围34/34正确，输出来源31/34通过；第21/22/24条空结果缺来源绑定，结论REQUIRES_TRAINING_DATA_REVISION；12项资金提案Decimal总额与allowlist检查通过。另有RBR02—04质量待办，见[逐项复核](release-v2/ROOT-BUSINESS-REVIEW.md)和[P2校准发现](release-v2/P2-CALIBRATION-REVIEW-FINDINGS.md)。Root复核不等于genuine human receipt，human_reviewed=false、human_review_pending=true。候选和sealed保持原样；P2 baseline calibration、T2授权仍pending，Student评估延期，sealed模型评测授权false，training_eligible=false。未来修订须新版本和fresh source freeze；不复用旧收据。

## 记录与验收依据

- [T1 freeze 记录](FREEZE-T1.md)：冻结范围、split 规则、合成数据和密封集处理状态。
- [CAP 覆盖要求](COVERAGE-T1.md)：v1 可用语义和未来 CAP 覆盖边界；模拟轨迹不能证明真实后端执行。
- [v1预登记验收标准（历史）](ACCEPTANCE_CRITERIA-T1-v1.json)：记录旧版阈值及 sealed-set 策略；当前release-v2 candidate gate口径以[v2验收标准](release-v2/ACCEPTANCE_CRITERIA-T1-v2.json)为准。
- [后端业务验收](BUSINESS_ACCEPTANCE.md)：B01–B14 与现有 SQL assertions 的对应关系、CAP01–17 当前真实 Agent 接入情况，以及本轮数据库验收未运行的记录。
- [模型准备说明](MODEL_PREPARATION-T1-v1.md)：数据校验、受限语义评分和本地 Student 请求的计划边界；本次未运行模型。
- [模型评估预登记](MODEL_PREREG-T1-v1.json)：状态 `FROZEN_BEFORE_MODEL_OUTPUTS`，64 项来源指纹匹配。此为运行前方案冻结，不表示已经推理；实际模型评估按用户选择延期，sealed one-shot 授权为 false。以链接文件中的当前 hash 为准。
- [Teacher v1路由状态（历史）](TEACHER_STATUS-T1-v1.md)：仅记录当时核对本地配置、未发送请求的状态，不代表当前Teacher状态。最新release-v2有限检查见[Teacher availability](release-v2/TEACHER-AVAILABILITY.md)和[Teacher readiness](release-v2/TEACHER-READINESS.md)：一次请求、3个合成短文本案例，root review 3/3；Teacher data quality仍NOT_ASSESSED。
- [root freeze review 元数据](evidence/ROOT_FREEZE_REVIEW-T1-v1.json)：诊断审批与 manifest 的绑定证据；reviewer 检查 sealed 原始字节哈希和行数，未解析/查看 sealed 语义内容，也未消费 sealed。
- [release-v2 候选状态](release-v2/README.md)和[候选准备/写入记录](release-v2/CANDIDATE_PREPARATION.md)：393 条新候选、自动collection gate、root near-pair技术审阅、写入身份及尚待完成的人审/P2/T2门槛。它们不修改 v1 冻结。
- [数据集非正文索引](../../dataset_contracts/t1/dataset-index.json)和[数据封套 schema](../../dataset_contracts/t1/dataset-envelope.schema.json)：split 汇总、bundle hashes 与字段契约，不含样本正文。
- [模型评估状态](#model-evaluation)：用户延期，未进行模型推理。

## 当前评估状态

<a id="model-evaluation"></a>
### 模型评估

状态：`NOT_TESTED_USER_DEFERRED`。用户选择将实际模型推理延期；当前无模型输出、质量 PASS、阈值达标或训练准入结论。预登记已在任何模型输出前冻结，绑定 manifest、审批、protocol fingerprint 和 validation/sealed bundle hashes。sealed 单次评测仍需另行的 root one-shot authorization；当前该授权为 false。预登记当前 hash 见链接文件。

### 后端与真实 CAP

本轮后端验收状态为 `NOT_RUN_RESOURCE`。当前真实 Agent CAP01–CAP17 为 0/17 可验收；有限 P1 通过只覆盖工程骨架、Mock Runtime、身份隔离和 Docker 恢复，不等价于真实业务工具、模型调用质量或财务写入验证。后续本地后端验收按已登记的隔离方案执行；本次数据冻结不包含新增云端写入。详见 [后端业务验收](BUSINESS_ACCEPTANCE.md)。

### 数据与授权边界

仅使用合成模拟业务事实。v2 candidate的模拟tool result标记simulated，不能标作backend_verified。393条技术gate通过不等于模型或真实后端验收。34-row train-only包通过hash/anchor/coverage完整性核验；root业务逐项审查结果为34/34文字、金额、范围正确，31/34输出来源通过，rows 21/22/24需修（见[Root业务复核](release-v2/ROOT-BUSINESS-REVIEW.md)）。RBR02—04还要求移除人工预置已消费context、改善自然对象澄清并补AA尾差覆盖；P2接续内容见[P2校准发现](release-v2/P2-CALIBRATION-REVIEW-FINDINGS.md)。Root审查不代表genuine human receipt，human_reviewed=false且human_review_pending=true。sealed语义内容未读；sealed模型评测授权为false。P2 baseline calibration、T2授权与新版本修订均pending；training_eligible=false。未来修订须fresh source freeze和新receipt，不复用当前receipt，也不打开既有sealed。
