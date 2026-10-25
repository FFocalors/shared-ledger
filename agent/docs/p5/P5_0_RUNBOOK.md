# P5.0 真机验收 Runbook（USB，不启用 LAN）

状态：**写通路与测试已完成；真机端到端被“预览来源”阻断**（见 §2）。
日期：2026-10-25
适用提交：本文件所在提交（见 `git rev-parse HEAD`）

## 1. 环境前提

| 项 | 要求 |
|---|---|
| 手机 | USB 调试已授权，只连接一台设备 |
| Agent | `D:/project/Android/shared-ledger-agent`，分支 `agent`，venv 已安装 |
| 模型 | LM Studio 已加载当前 P2 使用的模型（`AGENT_P2_LMSTUDIO_MODEL_KEY`） |
| Supabase | Agent 的 `AGENT_SUPABASE_AUTH_BASE_URL` / `AGENT_SUPABASE_API_KEY` 与 App 当前项目一致 |
| 业务数据 | 只在一个**专用测试 Activity** 中写入；不要使用真实账本 |
| 网络 | `adb reverse tcp:8765 tcp:8765`；**不运行** `dev-up.ps1 -Lan` |

## 2. 当前阻断：没有真实预览来源

P2 运行时的模型输出契约只允许 `P2ProposalRecognition`（operation + 识别文本），明确禁止生成预览字段；`P2Runtime._make_proposal` 直接抛 `CapabilityUnavailable`。

因此以下流程在选定预览来源前**无法执行**：

```
App 发消息 → Agent 生成 live proposal → App 显示确认卡 → 用户点击 → 真实 RPC
```

可选方案：

- **A（推荐先做）**：`AGENT_P5_DEV_INTENT=true` 的确定性意图桥，仅用于 P5.0 真机验收。它从当前 Activity scope 绑定参与人/账本单元，从文本提取金额、标题、付款人、分摊；不训练、不改冻结协议、默认关闭。日志与预览标记 `p5_dev`。
- **B**：新增 P5 模型 profile（结构化 propose schema + prompt + 新 execution pin）。这是产品路径，但工作量和验证面显著更大。

选定 A 或 B 后，先在 `agent/docs/p5/P5_0_SCOPE.md` §1.1 记录决定，再继续下面的步骤。

## 3. Agent 配置

在 `agent/.env`（不要提交）设置：

```dotenv
AGENT_PROVIDER_MODE=p2
AGENT_EXECUTION_ENABLED=true
AGENT_LIVE_WRITE_ENABLED=true
AGENT_AGENT_ENABLED=true
AGENT_DISABLE_REVISION=1
AGENT_SUPABASE_AUTH_BASE_URL=https://<project>.supabase.co/auth/v1
AGENT_SUPABASE_API_KEY=<publishable/anon key>
```

启动（普通 PowerShell，不要从沙箱进程启动）：

```powershell
cd D:\project\Android\shared-ledger-agent\agent\deploy\scripts
powershell -ExecutionPolicy Bypass -File .\dev-up.ps1
```

确认：

```powershell
curl.exe http://127.0.0.1:8765/health/ready
adb reverse --list
```

`health/ready` 必须报告存储、Auth 与运行时可用；`business_api_available` 必须为 `true`。

## 4. App 配置

`local.properties`：

```properties
agent.baseUrl=http://127.0.0.1:8765
agent.demo=false
```

重建 debug 并安装：

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

打开一个**专用测试 Activity**，再打开 Agent 面板。

## 5. 验收步骤与四条结果

| # | 操作 | 预期 | 证据 |
|---|---|---|---|
| 1 | 输入一条新增消费请求，等待确认卡 | 卡片显示金额、币种、付款人、分摊；业务库无新 Expense；Agent 日志没有 `create_expense_auto_rate` | 预览截图 / 卡片 JSON；`select count(*) from expenses where ...` |
| 2 | 连续点击确认 3 次 | 只有 1 次 RPC、1 条 Expense；三次返回同一 `execution_id` | Agent 日志请求计数；Expense 行；执行回执 |
| 3 | 重新生成预览后，在另一台设备/客户端修改同一 Activity 的任意财务字段，再确认 | 不发 RPC；App 显示预览失效；Proposal `closed`；Turn `CANCELLED` | Agent 日志无 RPC；`activities.financial_version` 前后值 |
| 4 | 在确认请求发出后立即断网/拔 USB（或在测试传输层注入超时） | App 只显示“正在核对结果”；Turn `RECOVERING`；重复确认不再发 RPC | 状态 JSON；日志中只有一次派发 |

补充拒绝分支（任选一条即可）：非成员账号、已归档 Activity、外币、负金额都应被拒绝且不产生写入。

## 6. 证据记录模板

```text
提交: <git rev-parse HEAD>
设备: <型号 / Android 版本>
App: <versionName> debug
Agent 启动时间:
Activity ID: <专用测试 Activity>
预览:
  proposal_id:
  command_digest:
  expected_financial_version:
执行:
  execution_id:
  expense_id:
  expense.version:
四条结果: 1 PASS / 2 PASS / 3 PASS / 4 PASS
备注:
```

## 7. 回滚

1. 将 `AGENT_LIVE_WRITE_ENABLED=false`，重启 Agent。确认接口回到冻结的 501。
2. 如果已写入测试 Expense，在专用测试 Activity 中用 App 原生删除；不要直接改业务表。
3. 不改业务 schema，因此无需数据库回滚。

## 8. Pin 提醒

本次提交修改了 `agent/app/store.py`、`api.py`、`components.py`、`settings.py`，它们都在 P2 v3 execution manifest 的 49 个 component 内。因此：

- **文档里的“当前 pin”已失效**，live P2 v3 运行会被 fail-closed。
- 需要 live 运行时，用 `python -m agent.app.p2_v3_manifest_cli` 重新生成 manifest，并在状态文档中显式记录新 pin。
- 旧的真机证据仍绑定旧源码哈希；重新生成 pin **不会**重新验证旧证据。
