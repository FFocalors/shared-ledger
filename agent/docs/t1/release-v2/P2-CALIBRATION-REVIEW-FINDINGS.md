# P2 校准复核发现：T1 release-v2 attempt-02

这份短说明用于把 root 对 34 条 train-only 样本的复核结果交给并行 P2 工作会话。原只读任务、app/tests 和冻结候选均保持不变。当前 P2 baseline calibration 未完成，T1 正式准入未完成，training_eligible=false。

## 需要处理的发现

- **RBR01：空结果没有可追溯来源（阻断）。** Packet rows 21/24 are true empty tool results. Row 22 has five real read results followed by a title post-filter that returns empty; evidence must bind that filter and prove the underlying result set is complete. All three answers have correct business text but no source binding. This is an inherited known contract gap, not a new business or model regression: the P1 citation kinds support fact_activity/expense/debt and policy_fact, but not read_result_N. P2 may design a typed query result that the model can read and cite, or an equivalent trusted, versioned system renderer. Either approach must bind query completeness (including pagination/truncation), filters, scope, and result/schema version; an empty list alone does not prove no match. A typed citation or renderer contract changes canonical semantics, so version it and create a new freeze. Do not silently edit the old freeze or fabricate Fact, Policy, or mismatched citations.
- **RBR02：context 人工预置了“已读取并消费”。** 33/34 条 context.input_text 带人工追加提示，构成 teacher-forced 模拟。SFT 输入应反映 Agent 当时真实可见的上下文，不应预告工具是否已调用或消费；与 P2 的真实 context 生成规则对齐。
- **RBR03：澄清对象使用内部 expense_ref。** rows 19/20/26 业务结果正确，但澄清体验应使用已返回事实中的参与人或费用标题、日期、金额等信息来区分候选，并由 P2 校准候选展示和选择流程；不要求当前 DTO 提供额外商家字段。
- **RBR04：AA 尾差样例覆盖不足。** rows 15/16/17 的金额都能整分，不能作为最小单位分摊尾差的证据。第14/30条是手工分配/守恒样例，不能冒称AA尾差验证。增加非整分平均分配、多人小额和确定性尾差分配案例，并核对金额守恒。

## 协议与数据保全要求

1. 空结果证据不得由生成器推断或补造；不能伪造 Fact、Policy、citation，也不能把“conversation”包装成数据库查询来源。
2. 任何 canonical 协议变更都要产生新的语义/协议版本和 freeze。不得静默修改旧 P1 protocol freeze，也不得让旧 freeze 的收据绑定到新协议。
3. 已持久化的 release-v2 candidate、train review packet、旧 v1 数据和输入归档保持不变。完成修订后需重新 source-freeze、生成新版本并记录新 receipt；不能复用旧 source receipt，不能重新生成或打开既有 sealed 内容。
4. 当前 34 条业务文字、金额及范围逐条均通过；其中 31 条来源审查通过，3 条 RBR01 需修。12 项资金提案独立 Decimal 总额与 allowlist 检查通过。这不等于真实 human receipt、T1 formal admission、Student 质量或 CAP 验收。

## 证据

Root 业务复核报告 SHA-256：77ce270ee836d889f119008348caaa702781e667a61a44e4964b84e826c9f7ad。完整逐项 root_note、34 条复核表、样本范围和 packet hashes 见 [Root 业务复核记录](ROOT-BUSINESS-REVIEW.md)。
