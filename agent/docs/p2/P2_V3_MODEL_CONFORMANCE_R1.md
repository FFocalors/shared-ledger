# P2 v3 模型协议不遵循：差异说明与建议的提示词修订（R1）

**状态：待 root 评审，未实施。** 本文不改任何契约、schema、parser 或提示词源码；它记录一次实测到的模型侧协议不遵循，并提出一个**候选**提示词修订供评审。在 root 裁决前，严格 sent guard 与 `P2AnswerDecision` 契约保持原样。

## 实测

在当前 pin（manifest SHA-256 `5df93c7fe360e8cedda27b2ca38379c031cd227768f31f7505c127bcd3dd92c6`）上，用本机隔离 Supabase + 本地 `t0-cp36-20261007`（native `/api/v1/chat`、`reasoning=off`）跑了 3 次真实 Turn。3 次都自主选出了正确的 `read.activities` 并完成真实读取；**2 次**在答案阶段被严格 sent guard 拒绝，回合 `FAILED`。被拒的两份原始输出（`model-response-02.json`）之一：

```json
{"kind":"answer","basis":"fresh_read_receipts","citations":["qev_bLavUnk1JLdv-hstdJ6XCgf0Fno"],
 "text":"当前活动列表包含 1 条记录。",
 "source_query_complete":true,"model_projection_complete":true,"has_more":false}
```

- `kind`、`basis`、`citations`（是本次新铸且正确的新 QEV）、`text` 全部正确
- 多出 3 个**契约未声明**的根字段：`source_query_complete`、`model_projection_complete`、`has_more`；失败样本中另有一次出现 4 个

`P2AnswerDecision`（`agent/app/p2_read_contracts_v3.py:1601`）只声明 `kind`/`basis`/`text`/`citations`，`basis="fresh_read_receipts"` 时 `citations` 非空——该输出的业务内容是对的，违反的只是「根对象不得含未声明字段」。

## 性质判定：模型侧不遵循，不是契约或实现缺陷

- 契约与严格 guard 是**安全属性**：受保护答案只能声明契约内的字段，否则「模型不能创建 UUID、权限或业务事实」这条边界就无从守住
- 这不是第一次：R2 记录过 answer 多出根字段 `"type":"application/json"`。`direct-decision-hint-r3`（`agent/app/p2_read_native_provider_v3.py:42`）已经点名禁止 `type`、`candidates`、`arguments`、`content`、`reason`、`evidence_refs`、`intent_id` 等**旧协议/MIME 字段名**
- 本次多出的字段**不在 r3 的禁止清单里**：它们是从上下文 page-summary 的词汇（`source_query_complete`、`model_projection_complete`、`has_more` 都出现在 `P2PageSummary` 与 QEV 的公开投影中）**新造**的。即 r3 用「枚举黑名单」压制，而模型会从当前上下文里捡词自造字段

因此**不应**通过放宽 guard、改契约或给 `P2AnswerDecision` 加 `extra="allow"` 来"修好"这件事。可选路径只有两条：改提示词（下文候选），或接受该模型在此契约下不可靠（质量结论）。

## 候选修订（未实施，供评审）

在 `_DIRECT_DECISION_HINT_R3` 的 answer 规则处，把「枚举禁止」升级为「白名单 + 显式禁止复制上下文词汇」：

1. 明确写出 `kind=answer` 时根对象**恰好**为 `kind`、`basis`、`text`、`citations` 四个字段（r3 已有此句，但只针对 MIME 情形）
2. 增加一句：**不得把上下文、query evidence 或 page summary 里的任何字段名（如 `source_query_complete`、`model_projection_complete`、`has_more`、`range_contiguous`、`expected_total` 等）复制到答案根对象或任何决策对象中**；这些信息属于服务端投影，不是模型可回述的字段
3. 措辞上不改变任何 kind 的授权边界，也不扩大 financial read/source 授权

若采纳，建议同步把该约束同时写入兼容路径与 native 路径的共享提示词片段，避免两条 wire 的约束漂移。

## 影响面（评审时必须一并决定）

| 项 | 影响 |
|---|---|
| 提示词字节 | 变化。`agent/tests/test_p2_read_prompt_provider_v3.py` 的 `GOLDEN_NORMAL_REQUEST_SHA256` / `GOLDEN_REPAIR_REQUEST_SHA256` / `GOLDEN_SCHEMA_SHA256` 必须按**已评审**的改动重新基准化（该文件已写明：只可为已评审的提示词/schema 改动重基准，不得为消错而重基准） |
| native 装配 pin | native 候选要求经生产 verifier 的 execution cohort pin。提示词源码在 manifest 的 component 绑定范围内，因此**需要重新生成 manifest 并换 pin**；旧 pin 下不得声称新提示词已验收 |
| 契约 | 不变。不改 `P2AnswerDecision`、不改 sent guard、不改 schema |
| T1 | v3 是独立候选 profile；若该 profile 要参与 T1 数据集/评测，提示词版本属 prereg 输入，须由 root 判定是否触发新 prereg |
| 回滚 | 保持现有 r3 提示词即可；本修订不引入新状态、不迁移持久数据 |

## 证据

- `D:/AI/runs/shared-ledger/p2/current-postfix-live-20261018-01/run-4fd9813a7d-live/`（通过的一次）
- `D:/AI/runs/shared-ledger/p2/current-postfix-live-20261018-01/run-a83b909b56-live/`（被拒的一次，含 `model-response-01.json` / `model-response-02.json` 原始响应）
- 汇总、边界与样本量声明见同目录 `P2_LIVE_CLOSE_LOOP_R1.md`

**样本量：3 次 Turn、2 次同因失败、1 次通过。这不是通过率结论，也不改变 `INSUFFICIENT_SAMPLE`。**
