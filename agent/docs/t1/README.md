# T1 数据与评估索引

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
