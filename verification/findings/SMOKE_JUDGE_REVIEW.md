# v0.2 六项 Smoke Judge 结果核查

模型：`deepseek-v4.1-flash`，通过 OpenCode Go 调用。业务规则提交：`54270927dfd058f7f42ae8c330d7396634657b41`。本轮复用已在隔离 Supabase（41/41 migrations）执行成功的六个 run；未修改 Scenario、最终状态或冻结业务实现。

## 结果及解释

| Scenario | run_id | Judge | 核查说明 |
| --- | --- | --- | --- |
| basic_single_payment | 20260923T103209Z-9801c60b | PASS | A 支付、B 承担 100 CNY，B→A 当前债务 100，活动 active。 |
| multi_payer_aa | 20260923T103210Z-560a671e | FAIL | 已核实原币债务被归一函数覆盖；正确净额 26.6666 / 6.6667 被改为 26.7000 / 6.6333。Base 尾差 26.7 / 6.6 本身不构成独立失败。 |
| multiple_repayments | 20260923T103210Z-4ceb6dbd | PASS | FIFO 30+20+50 清偿 100；来源 ExpenseDebt 与分配历史保留，当前双边债务归零，活动 completed。 |
| prepayment_before_debt | 20260923T103211Z-b6c1ad6e | PASS | B 向 A 预存 200，后续消费使用 100；当前债务为零，仍有预存 100，所以活动 active。 |
| targeted_partial_repayment | 20260923T103211Z-a961708d | PASS | TARGETED 40 分配至指定 100 账单；来源债务保留，当前双边债务 60，账单财务锁定。 |
| linked_refund_after_settlement | 20260923T103209Z-c763a31d | PASS | 原账单 B→A 100 已由历史付款清偿；退款由 B 收到、A 受益，新增 B→A 100。历史付款不撤销，活动回到 active。 |

最终：**PASS 5 / FAIL 1 / UNCERTAIN 0 / JUDGE_ERROR 0**。全部结果可解释不等于业务全部通过；AA 的实现缺陷仍未修复。详见 [multi_payer_aa.md](multi_payer_aa.md)。

## linked refund 重试证据与边界

旧结果为 `JUDGE_ERROR / API_ERROR`，错误类型此前未保存，无法事后认定每次旧失败均为超时。旧结果保留在该 run 的 `judge.previous_error.json`。

本轮保持相同模型、完整业务规则、Scenario 和最终状态，使用 240 秒超时、零网络重试执行一次定向请求。实际收到 HTTP 200，耗时 116.5 秒，`finish_reason=stop`，有效最终内容 2550 字符，结构化 verdict 为 PASS。没有缩减规则、切换模型或为获得 PASS 改写输入。未保存或展示模型内部推理内容。

接口能够返回正确端点的完整结果；长响应时间说明此前较短超时存在风险，但单次成功不证明上游永久稳定。新增 `DEEPSEEK_TIMEOUT_SECONDS` 支持可配置超时；请求失败现在保存安全的 `timeout/network/http/invalid_response` 分类和可用 HTTP 状态，以便下次有依据地处理。重试仍有界，不无限重试或重复运行已有可解释的业务判定。

## 验证与范围

本轮可靠性修改通过 31 项本地单测，单测不访问真实模型。各 run 的 `judge.json` 保存原始结构化业务判定；AA 模型对 base 尾差的过度判断仅在核查报告纠正，未篡改 Judge 输出。

冻结的 migrations、RPC、Android 代码与 BUSINESS_LOGIC.md 均未修改，未进入 v0.3。后续 AA 修复应作为独立业务修复处理。
