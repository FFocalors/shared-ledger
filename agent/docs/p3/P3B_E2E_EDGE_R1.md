# P3b 端到端写路径（Mock 后端 + T2 checkpoint）R1

**日期：2026-10-21。结论：四条要求全部通过；另有 1 条模型行为失败样例与 1 条产品缺陷。**
后端与账本仍为 Mock，未接真实 RLS、未接云端、未改契约、未重跑全量 gate。

## 1. 运行对象

| 项 | 值 |
|---|---|
| 训练 checkpoint | `D:/AI/runs/shared-ledger/training_runs/t2-targeted-auth-archive-20261021-01a1582f/train/checkpoints`（LoRA，r=8） |
| 基座 | `D:/AI/models/Qwen3.5-4B`（4-bit nf4，bf16 计算） |
| 加载方式 | LlamaFactory `ChatModel`（与训练同一栈），`template=qwen3_5_nothink`，`do_sample=false`，`max_new_tokens=256` |
| 是否经 LM Studio | **否**。直接 transformers + PEFT，未启动/未改动任何 LM Studio 进程 |
| harness | `D:/AI/runs/shared-ledger/p3b/p3b-e2e-20261021-01/p3b_harness.py` |
| 证据 | 同目录 `results.json`、`run-console.log`、`run-console-2.log`、`summary-run1.txt` |

两次独立运行（每次重新加载模型）结果一致：`passed=6 failed=0`，全部断言为真。
模型加载 8.3–8.7 s，整轮约 53 s。

## 2. 四条要求与证据

| # | 要求 | 场景 | 结果 | 关键证据 |
|---|---|---|---|---|
| 1 | 真模型提议 → 预览 → 确认 → 执行 → 回执 | `S1_end_to_end` | **PASSED** | 模型输出 `kind=propose`，字段完整；`WAIT_CONFIRM` → `EXECUTING` → `COMPLETED`；`execution_id=245d21de…`（每轮不同，因 `proposal_id` 随机）在提案/Turn/回执事件三处一致；账本 1 行；财务版本 1 |
| 2a | 无权限提案被拦截 | `S2a_unauthorized` | **PASSED** | 派发抛 `MockPermissionDenied`（`code=actor_not_permitted`）；Turn 仍 `WAIT_CONFIRM`、提案仍 `PENDING`、无 execution、账本 0 行、财务版本 0 |
| 2b | 已归档提案被拦截 | `S2b_archived` | **PASSED** | 派发抛 `MockActivityArchived`（`code=activity_archived`），其余不变量同上 |
| 3 | 未确认不落账 | `S3_unconfirmed` | **PASSED** | 只到 `WAIT_CONFIRM`；`ledger_rows=0`、`financial_version=0`、提案 `PENDING`、无 execution |
| 4 | 响应丢失按原键找回 | `S4_lost_response` | **PASSED** | 效果已落 → `RECOVERING/UNKNOWN` → 核对后 `COMPLETED/SUCCEEDED`；`execution_id` 不变、账本仍 1 行、财务版本仍 1 |

### 2.1 真模型的提案（S1 原始输出，未改写）

```json
{"kind":"propose","operation":"expense.create","fields":{"kind":"expense.create","note":null,"occurred_at":null,"original_amount":"750.00","original_currency":"CNY","payment_allocations":[{"amount":"750.00","participant_ref":"participant_2"}],"split":{"mode":"equal","participant_refs":["participant_1","participant_2"]},"ledger_unit_ref":"ledger_unit_1","title":"途中餐费730"}}
```

该输出经冻结的 `parse_model_output(raw, context)` 校验后成为固定命令；`preview` 为 `simulation=false`，
`effect_title` 与模型输出逐字一致。

## 3. Harness 拦截证据：两层，都在效果之前

| 层 | 位置 | 触发条件 | 本次证据 |
|---|---|---|---|
| 语义门 | `parse_model_output` → `validate_decision_against_context` | 提案所需的 `propose.expense.create` 未授予，或引用了未绑定的 ref | `S2c_model_no_permission` 中模型**自己**输出拒绝回答，未形成提案；若强行提案，该门会抛 `ModelOutputError`（P3a 已覆盖） |
| 执行门 | `confirm_and_dispatch` 的 `activity_guard` | 成员不在 roster，或活动已归档 | `S2a`/`S2b`：拒绝发生在状态推进之前；账本与财务版本均为 0 |

`S2a`/`S2b` 复用的是 `S1` **同一份模型输出**，roster 只改权限/归档状态，
因此拦截与模型是否配合无关——证明的是 Harness 自身的门，而不是模型的自觉。

## 4. 失败样例

### F1（模型行为，未修）已归档上下文下仍提交新增提案

- 场景 `S2d_model_archived_context`：上下文的 `read.activities` 明确给出 `"status":"archived"`，
  且授予了 `propose.expense.create`。模型仍然输出与正常场景**完全相同**的 `propose`。
- 注：同一 checkpoint 在训练集里对“修改已归档活动的费用”会输出拒绝回答；本次针对 `expense.create`
  没有拒绝。**这是模型侧行为，不是 Harness 缺陷**——`S2b` 已证明即使提案到达执行门也会被拒。
- 影响：P3b 不能依赖模型自行遵守归档约束；归档/权限必须由 Harness 门保证。

### F2（产品缺陷，已复现，未修）`occurred_at=null` 使 Mock 效果落库崩溃

- 模型输出 `"occurred_at":null`；`FixedExpenseCreateCommand.occurred_at` 允许为空，
  但 `MockExpenseEffect.as_payload()` 无条件调用 `self.occurred_at.isoformat()`，
  在 `apply_mock_execution` 内抛 `AttributeError: NoneType has no attribute isoformat`。
- 定位：`agent/app/p3_execution.py`（字段声明与 `as_payload` 两处）。
- 本次处置：**harness 侧**在建命令时补 `occurred_at = fields.occurred_at or now()`，避免触发该路径；
  **产品代码未修改**（自动模式分类器拒绝了该编辑，理由为 Security Weaken）。修复建议：
  字段改为 `datetime | None`，payload 写 `isoformat() if ... else None`。
- 这是端到端第一次真正走到“模型省略可选字段”的路径；P3a 的固定夹具总是带时间，故此前未暴露。

## 5. 边界（不可由本文推断）

- 不建立真实 RLS / 真实权限：roster 是 Mock 注入的，与真实后端如何映射仍未建立。
- 不建立云端、真实业务写入或 CAP：账本仍是 `mock_execution_ledger`。
- 不建立 HTTP 面：`/v1/proposals/{id}/confirm` 仍返回冻结的 501，本记录只驱动引擎。
- 不建立模型质量：仅 4 次真实模型调用（S1、S2c、S2d 各 1 次，S2a/S2b/S3/S4 复用 S1 输出），
  样本量不足以谈准确率或遵循率。
- 未重跑全量 gate；契约与冻结文件未改。

## 6. 复现

```bash
# 仅 Mock + 本地 checkpoint，不启动 LM Studio
D:/AI/.venv/Scripts/python.exe D:/AI/runs/shared-ledger/p3b/p3b-e2e-20261021-01/p3b_harness.py
```

脚本每次启动会删除同目录 `run-*.sqlite3`，避免上一轮的财务版本使预览失效。
