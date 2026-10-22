# P3a 确认路由的成功响应：契约差异提案（已实施）

> **已批准（2026-10-22，所有者）并已实施。** 新增 `ProposalExecutionAccepted`（HTTP 202）与 `RequestReceiptKind.EXECUTION_DISPATCHED`；`501 ConfirmationUnavailableResponse` 保留，由 `execution_enabled` 配置开关控制（默认 false，即回滚到冻结行为）。新契约快照 `agent/contracts/v1.0.0/manifest.json` 文件 SHA-256：`c1f7775add9cf1e66986d3a56d4358c4f263d083fd518317539a545f5650f864`（本机工作树字节；干净 checkout 因行尾不同会得到不同哈希，见 P2 复核 R1-1）。实施细节与测试见文末「实施记录」。

**历史状态（提案阶段）：** 冻结的 v1 契约里 `/v1/proposals/{proposal_id}/confirm` **没有成功响应**，只有 `400/401/403/404/409/422/429/501/503`；因此 P3a 的引擎虽然已能真实执行，HTTP 面当时仍返回冻结的 501。要让确认在 HTTP 上"打通"，必须先批准一份响应契约——本提案即是该契约。

## 现状证据

`agent/contracts/v1.0.0/openapi.json` 中该路由的 responses 为：
`400, 401, 403, 404, 409, 422, 429, 501 (ConfirmationUnavailableResponse), 503`。没有 `2xx`。

`ConfirmationUnavailableResponse` 的字段是 `api_version / business_write_performed / code / execution_enabled / message` —— 它是"执行不可用"的冻结表达，不是成功回执。

## 建议的新增（additive，不改任何既有字段语义）

1. **新响应模型** `ProposalExecutionAccepted`（HTTP 202）：
   - `api_version`
   - `turn: TurnPublicStatus`（既有模型，含 `execution_assigned` 与 `execution_resolution`）
   - `execution: ExecutionReference`（既有模型：`execution_id / proposal_id / proposal_revision / operations_version`）
   - `event_cursor`（int，与既有 `TurnMutationAccepted` 语义一致）
2. **新增一个 receipt kind**，例如 `RequestReceiptKind.EXECUTION_DISPATCHED`，使同一 `client_request_id` 的重放返回原始 202 而不是重新执行（当前 `CONFIRMATION_UNAVAILABLE` 承载不了成功回执）。
3. **路由新增 202 响应**；`501 ConfirmationUnavailableResponse` **保留**，在 `execution_enabled=false` 时继续返回，作为回滚开关。

## 为什么不能"顺手加"

- OpenAPI 与 `agent/contracts/v1.0.0/` 是冻结导出；新增响应码与新 schema 会改变 canonical 快照与 manifest 哈希。
- 既有客户端把"非 2xx"一律当作"执行不可用"；一旦出现 202，行为面改变，必须由契约所有者确认。
- 若 v3 candidate 或 T1 需要引用该响应，还需同步 prereg/协议版本判断。

## 影响面与回滚

| 项 | 影响 |
|---|---|
| canonical 导出 | `openapi.json`、新增 schema 文件、`manifest.json` 哈希变化（需随批准一起重导出并重新 freeze） |
| 客户端 | 需要处理 202；未升级客户端仍可只把 501 当"不可用" |
| 服务端 | 需要 `execution_enabled` 开关、receipt kind、以及把 API 处理器接到已实现的 store 方法 |
| T1 | 若引用，需要协议版本与新 freeze；本提案不改 T1 任何文件 |
| 回滚 | `execution_enabled=false` → 继续返回 501；测试与引擎不受影响 |

## 实施时 API 处理器要做什么（等批准后）

1. 认证、scope 校验、幂等 receipt 查找（沿用现有顺序）。
2. 调 `store.confirm_and_dispatch(...)`（已实现：校验 nonce/digest/revision/前置条件 → 分配由 `(actor, proposal_id, revision)` 派生的 `execution_id` → Turn 进入 `EXECUTING/DISPATCH`）。
3. 调 `store.apply_mock_execution(...)`（P3a 为 Mock；P3b 换真实后端）。
4. 调 `store.settle_mock_execution(...)` 并返回 202 + 该 receipt。
5. 任一步出现"效果可能已落但结果未知"→ **不得**返回成功，也不得换键重试：`store.mark_execution_unknown(...)` 后由运行时恢复路径按原键结算。

## 明确不做

不修改 `ConfirmProposalRequest`、`ExecutionResultPayload`、状态转移表、严格 sent guard 或 P2 v3 相关任何契约；不在本提案里新增业务 operation。

## 与 P3a 引擎的关系

引擎与四条验收条件**不依赖**本提案：它们已在 `agent/app/store.py` 的 P3a 方法上实现并有测试（`agent/tests/test_p3a_mock_write.py`）。本提案只解锁"HTTP 上把确认当作成功返回"这一层。

## 实施记录（2026-10-22）

| 项 | 内容 |
|---|---|
| 开关 | `Settings.execution_enabled`（默认 `False`）→ `AppComponents.execution_enabled`；`False` 时路由原样返回冻结的 501 |
| 新响应模型 | `ProposalExecutionAccepted`：`api_version / turn: TurnPublicStatus / execution: ExecutionReference / event_cursor`；校验器要求 Turn 已分配执行身份且不处于规划态 |
| 新 receipt kind | `RequestReceiptKind.EXECUTION_DISPATCHED`；`RequestReceipt` 联合与 `response_kind_matches_snapshot` 均已允许该组合（`PROPOSAL_CONFIRM` 现在允许 501 或 202 两种 receipt） |
| store | 新 `record_execution_dispatch(...)`：提案必须已 `CONFIRMED` 且带 execution；同 `client_request_id` 重放返回原 202；CAS 限定 `status='confirmed'` |
| API 处理器 | 校验通过后：`confirm_and_dispatch` → `apply_mock_execution` → `settle_mock_execution` → 202 + receipt |
| 重复确认 | 同一 `client_request_id` 走 receipt 重放；不同 id 但提案已派发时，校验 `command_digest` 后返回同一个 execution，不再次派发 |
| 未知结果 | `apply`/`settle` 任一步失败 → `mark_execution_unknown`，仍返回 202 但 `turn.state=RECOVERING`、`execution_resolution=unknown`；**不声称成功**，由运行时按原键结算 |
| 契约导出 | `openapi.json` 新增 202；新增 `schemas/ProposalExecutionAccepted.schema.json`；`manifest.json` 56 个生成文件（原 55） |
| 测试 | 新增 `agent/tests/test_p3b_confirm_api.py` 6 条；`test_protocol_contracts.py` 改为断言 202 与 501 并存 |

明确未做：未接真实后端（仍写 Mock 账本）、未接云端、未改 `ConfirmProposalRequest`/`ExecutionResultPayload`/状态转移表、未改 P2 v3 契约。
