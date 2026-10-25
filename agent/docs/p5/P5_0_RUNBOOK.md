# P5.0 真机验收 Runbook（USB，不启用 LAN）

状态：**可执行**（确定性开发桥已实现）
日期：2026-10-25
适用提交：本文件所在提交（`git rev-parse HEAD`）

## 1. 环境前提

| 项 | 要求 |
|---|---|
| 手机 | USB 调试已授权，只连接一台设备 |
| Agent | `D:/project/Android/shared-ledger-agent`，分支 `agent`，venv 已安装 |
| 模型 | 不要求可用：`记账` 桥不会调用模型 |
| Supabase | Agent 的 `AGENT_SUPABASE_AUTH_BASE_URL` / `AGENT_SUPABASE_API_KEY` 与 App 当前项目一致 |
| 业务数据 | 只在一个**专用测试 Activity** 中写入；不要使用真实账本 |
| 网络 | `adb reverse tcp:8765 tcp:8765`；**不运行** `dev-up.ps1 -Lan` |

## 2. 预览来源：p5_dev 确定性桥

P2 的非 v3 profile 支持完整的 `expense.create` 语义。开启开发桥后，Agent 对以 `记账` 开头的输入**不调用模型**，而是按当前服务端 scope 直接生成 live 预览：

```text
记账 <标题> <金额> [付款人=<名字>] [分摊=<名字1>,<名字2>] [账本=<名字>]
```

示例：

```text
记账 午餐 12.50
记账 打车 30 付款人=Rin 分摊=Alex
记账 晚餐 88 付款人=Alex 分摊=所有人
```

默认值：

- 付款人 = 当前 Activity 的第一个参与人
- 分摊 = 当前 Activity 的全部参与人（等额）
- 账本单元 = 第一个可用账本单元
- 币种 = Activity 基础币种

限制：

- 只支持基础币种；出现 `USD/美元/$/EUR/欧元/JPY/日元` 会拒绝走桥，交给普通路径。
- 只支持等额分摊；手动分摊留给后续切片。
- 名字必须与当前 scope 的显示名精确或唯一匹配；匹配不到或多义时拒绝走桥。
- 预览摘要带 `【P5 开发验证】`，`policy_version=p5-dev-intent-v1`。它不是产品模型输出，只用于验证写通路。

## 3. Agent 配置

在 `agent/.env`（不要提交）设置：

```dotenv
AGENT_PROVIDER_MODE=p2
AGENT_AGENT_ENABLED=true
AGENT_DISABLE_REVISION=1
AGENT_EXECUTION_ENABLED=true
AGENT_LIVE_WRITE_ENABLED=true
AGENT_P5_DEV_INTENT_ENABLED=true
AGENT_P2_V3_CANDIDATE_ENABLED=false
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
| 1 | 输入 `记账 午餐 12.50`，等待确认卡 | 卡片显示金额、币种、付款人、分摊，摘要以 `【P5 开发验证】` 开头；业务库无新 Expense；Agent 日志没有 `create_expense_auto_rate` | 卡片截图；`select count(*) from expenses ...` |
| 2 | 连续点击确认 3 次 | 只有 1 次 RPC、1 条 Expense；三次返回同一 `execution_id` | Agent 日志请求计数；Expense 行；执行回执 |
| 3 | 重新发一条 `记账 ...`，在另一台设备/客户端修改同一 Activity 的任意财务字段，再确认 | 不发 RPC；App 显示预览失效；Proposal `closed`；Turn `CANCELLED` | Agent 日志无 RPC；`activities.financial_version` 前后值 |
| 4 | 确认请求发出后立即断网/拔 USB（或在测试传输层注入超时） | App 只显示“正在核对结果”；Turn `RECOVERING`；重复确认不再发 RPC | 状态 JSON；日志中只有一次派发 |

补充拒绝分支（任选一条）：非成员账号、已归档 Activity、外币命令、负金额都应被拒绝且不产生写入。

## 6. 证据记录模板

```text
提交: <git rev-parse HEAD>
设备: <型号 / Android 版本>
App: <versionName> debug
Agent 启动时间:
Activity ID: <专用测试 Activity>
命令: 记账 <标题> <金额> [付款人=...] [分摊=...]
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

1. 将 `AGENT_P5_DEV_INTENT_ENABLED=false`，`AGENT_LIVE_WRITE_ENABLED=false`，重启 Agent。确认接口回到冻结的 501，`记账` 输入回到普通路径。
2. 如果已写入测试 Expense，在专用测试 Activity 中用 App 原生删除；不要直接改业务表。
3. 不改业务 schema，因此无需数据库回滚。

## 8. Pin 提醒

本次提交修改了 `agent/app/store.py`、`api.py`、`components.py`、`settings.py`、`p2_runtime.py`，它们都在 P2 v3 execution manifest 的 49 个 component 内。因此：

- **文档里的“当前 pin”已失效**，live P2 v3 运行会被 fail-closed。
- 需要 live 运行时，用 `python -m agent.app.p2_v3_manifest_cli` 重新生成 manifest，并在状态文档中显式记录新 pin。
- 旧的真机证据仍绑定旧源码哈希；重新生成 pin **不会**重新验证旧证据。
