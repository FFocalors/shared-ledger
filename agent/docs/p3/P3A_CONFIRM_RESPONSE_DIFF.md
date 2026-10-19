# P3a 确认路由的成功响应：契约差异提案（未实施）

**状态：提案，待 root 评审；未实施。** 冻结的 v1 契约里 `/v1/proposals/{proposal_id}/confirm` **没有成功响应**，只有 `400/401/403/404/409/422/429/501/503`。因此 P3a 的引擎虽然已能真实执行，HTTP 面**仍返回冻结的 501**。要让确认在 HTTP 上"打通"，必须先批准一份响应契约。

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
