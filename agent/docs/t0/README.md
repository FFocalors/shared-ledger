# T0 当前清单与阶段门

更新时间：2026-10-08（Asia/Shanghai）。T0六步部署链验收通过（2026-10-08）；步骤1–5的实测、固定输入对照及旧资产适用性标记已完成；步骤6共享文档同步、D盘运行证据与C原hold归档清理已完成，日志归档、静态适用性审核与根主审完成。步骤3/4观测到raw logits非逐位相等，严格数值等价未建立，也不代表模型质量通过。旧标签T1重标/新数据集冻结及Teacher实际availability是独立后续事项，不属于本次六步T0关闭门。

当前证据：[HF Loader与推理报告](runs/20261008-hf-loader-preparation.md)、[F16/Q4/HF三格式对照报告](runs/20261008-f16-cpu-comparison.md)、[Q4 CPU推理记录](runs/20261008-q4-cpu-inference.md)、[步骤4转换记录](runs/20261008-step4-conversion.md)、[4B LM Studio smoke报告](runs/20261008-lmstudio-q4-smoke.md)、[旧资产适用性审核](legacy-asset-applicability.md)。三格式原始结果保留在D盘run目录；F16产物身份以步骤4转换记录和三格式报告更正后的canonical hash为准。步骤4转换记录中“推理/对照尚未完成”及09:58的[步骤3–5进度快照](runs/20261008-step3-5-in-progress.md)均为较早历史状态。完整权重、运行输出和日志保留在D盘run目录，不复制进仓库。

| 步骤 | 状态 | 工作与硬门 | 未通过时的出口 |
|---|---|---|---|
| 1. P0收尾、建立T0清单 | **完成** | 按统一指南记录现状、CAP/权限映射、环境/资产证据与未决项。P0工程核查通过不等于CAP端到端或Agent产品验收。 | 保留阶段边界，不把P1/P3工程状态当CAP模型验收。 |
| 2. 资产、工具、资源预检 | **完成** | 资产、adapter/base结构、环境与工具核查见[历史预检](runs/20261007-192738-step12-aonly-cp36.md)和[资产教训](../p0/t0-assets-and-lessons.md)。adapter配置指向本地4B base，不证明训练时base权重快照相同。 | 原始checkpoint、训练资产和历史报告保持不变；不以9B替代4B。 |
| 3. HF adapter merge、builder与固定输入对照 | **固定输入对照完成；严格数值等价未建立** | attempt3 HF merge通过。combined-peft-attempt1真实builder以checkpoint1219通过，source bytes/hash保持不变。v4 base+adapter与merged对三个冻结case均完成guarded raw-logit和generation capture：输入ID与冻结prompt一致；logits均为finite float32[248320]；两路token IDs/解码文本逐例相同并均以EOS结束，生成token数为28/3/23。算术输出为42，JSON经严格解析且与expected object相等，解释样例由root审阅为正常。raw logits不是逐位相等，三例cosine分别为0.99977985/0.99984057/0.99966149，argmax相同；没有据此宣称全域数值等价或语义质量通过。v4修复及运行证据见[HF报告](runs/20261008-hf-loader-preparation.md)。 | v1语法、v2 tokenizer Mapping、v3 cached offload乱码均保留为历史失败轨迹；v4当前固定case有效，不把有限用例外推到任意prompt。 |
| 4. F16/Q4_K_M转换、推理与三格式对照 | **三格式固定输入对照完成；数值等价未建立** | F16与Q4_K_M转换、metadata/hash均通过；三case的HF/F16/Q4 raw logits均为finite float32[248320]，冻结输入hash匹配，九组pair metrics均运行成功且首token argmax全匹配。按shared_ledger_explanation / short_arithmetic / agent_answerdecision_json顺序，HF↔F16 cosine为0.99987255/0.99991644/0.99983147，generation IDs三例相同；HF↔Q4为0.99021449/0.96196024/0.97002117，算术与JSON生成匹配，解释文本有两处词语差异；F16↔Q4为0.98995339/0.96075675/0.97062416。所有raw logits均非逐位相等；未设事后阈值，不作数值等价结论。三格式原始报告路径和SHA见本页开头；转换与Q4 CPU细节见[步骤4报告](runs/20261008-step4-conversion.md)及[Q4 CPU记录](runs/20261008-q4-cpu-inference.md)。 | 对照已记录完成；若后续需要更严格的兼容结论，先定义有依据的容差和目标场景，不能仅凭相同argmax或格式检查改判等价。 |
| 5. LM Studio host/Docker短synthetic smoke | **4B双端smoke、服务恢复与生命周期复核完成** | 本轮加载model key t0-cp36-20261007、publisher shared-ledger，Q4_K_M SHA-256 acfd01df6cbd3c8e1fa4dbe144f5852290689851c4f92d4ab892707d08724b34；D盘target与批准产物为同FileID硬链接，非9B。context=512、GPU=0.5、parallel=1、MTP=false，instance为t0-cp36-step5-20261008-1421z。Host/Docker各测两case，HTTP 200、client exit 0且model instance匹配；explanation 28 tokens、JSON 23 tokens、reasoning 0，严格JSON与expected object一致。524次资源采样最低可用RAM 9.798 GiB、GPU free最低4077 MiB，无保护门越界。仅定向unload该instance后remaining=0；LM Studio server运行前后均为stopped。D日志最终稳定SHA-256 E15741505DF01B53438A75EAFDD2B68BB24EB4C78298AFC66AA387F1086BB597。运行后C日志目录快照33 files/19,214,214 bytes；全部逐文件SHA与D历史归档匹配，D归档为 `D:\AI\runtime\lmstudio\server-log-history\pre-t0-20261007-200705`；C盘plain hold已精确清理，C junction仍指向D active；主审核验后的逐项复现索引见[Step 5复现索引](assets/reproduction-index-20261008.json)。详见[正式报告](runs/20261008-lmstudio-q4-smoke.md)。 | 结果证明受控4B runtime、传输与样例格式检查通过，不证明业务语义质量、CAP端到端或数值等价。
| 6. 最终归档、共享状态同步与白名单Agent小提交 | **T0六步部署链验收通过（2026-10-08）；共享文档、D盘日志归档、C原hold清理和根主审完成** | 已更新T0清单和五份共享状态文档，并纳入步骤5正式报告。D历史日志归档到 `D:\AI\runtime\lmstudio\server-log-history\pre-t0-20261007-200705`，33个文件/7个目录/19,214,214 bytes逐文件SHA与源hold匹配；C原plain hold已清理，C junction保留并指向D active。清理证明：`D:\AI\runs\shared-ledger\t0-deploy-smoke\20261007-200705-step3-merge\evidence\server-log-history-archive-20261008T144710Z\cleanup-verification.json`（SHA-256 25e315f94c53414c57cafa0a493f5a6335a37e4f446616a40beabc90b0e92146）。 | Git提交/推送结果以agent分支与origin/agent记录为准。

## 运行与对照边界

步骤3和4比较覆盖三个冻结synthetic输入，不代表真实账本、工具调用、多轮上下文、所有runtime或所有prompt。HF/F16在本组输入上的生成ID一致，Q4在算术和JSON样例上与HF一致；这些生成结果不抹去raw logits的数值差异，也不建立模型质量认证。三格式比较指标只报告观测值，未创设事后pass阈值。

T0六步部署链验收通过（2026-10-08）；步骤1–5的运行、对照与静态资产适用性审核已完成；步骤6的文档同步、D盘日志归档、C原plain hold清理及根主审均已完成。步骤3/4只覆盖三个冻结synthetic输入，raw logits非逐位相等且严格数值等价未建立；LM smoke不证明业务语义质量或CAP端到端。T1旧标签重标、新数据集及train/validation/sealed冻结尚未完成，但不属于本次六步T0关闭门；Teacher实际availability为独立后续任务，本次未调用。

## 旧资产与旁线处置

[旧资产与标签适用性审核](legacy-asset-applicability.md)已逐行覆盖266个去重样本行、145条模型轨迹；root批准0行直接复用、187行仅作待重标素材、73行证据不足不得进入正例、6行排除，所有旧模型输出隔离。每行positive_training_eligible=false；70条缺权威tool result body的answer需要查原结果，不能以教师文本补证；3条预存proposal仍待核活动类型，不得把旧行改写为大型Activity。新版数据集及train/validation/sealed均未冻结。此项静态适用性标记已完成，后续重标和证据追溯不阻塞本次T0关闭。

新版业务基线按当前用户决策和指南：普通Activity预存preview/create/return均拒绝；CAP13为Activity级Owner/Custodian/币种资金账户路径，可在有效子活动间共用。大型子活动Scope限制仅适用于该child Expense的payer与每个Split bearer，二者可不同；历史legacy-unscoped保持原状，不伪造参与人选择。D4全局禁用是历史模型策略；可修改性按当前后端财务锁、展示字段、权限/版本重核与Harness可信确认逐条判定。AA尾差、币种/FX、历史消费锁和普通Final均以当前后端行为为准。

## 角色与边界

Root负责规划和主审；重资源步骤按固定顺序串行执行。权重、工具、缓存、日志及新产物均留在D盘；不使用真实账本数据、不写云端。Teacher实际availability为独立后续任务；P1独立推进。本README仅是状态索引，不能替代D盘原始证据或T0最终审查。
