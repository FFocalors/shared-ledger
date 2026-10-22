# Agent 应用端：当前状态与后续接入（2026-10-22）

分支 `feature/agent-app-ui`，基于 `main@d5ff4f0`。对应 Agent 侧契约 `shared-ledger-agent/agent/contracts/v1.0.0`（api 1.0.0，快照 manifest 56 个文件 / `c1f7775ad…`，已复制到 `app/src/test/resources/agent-contract-v1.0.0/`）。视觉与交互方案见 [UI_PLAN.md](UI_PLAN.md)。

## 已完成（只读阶段）

| 模块 | 位置 | 说明 |
|---|---|---|
| 契约数据层 | `data/agent/` | v1 全部请求/响应/事件/草稿卡片 DTO；Ktor 客户端，Bearer 取 Supabase 当前会话 token；结果统一为 `AgentApiResult`；未知枚举/事件类型降级为 `UNKNOWN`/`Unknown`，不让整次轮询失败；确认接口同时接受 202 与 501，其他 2xx 视为契约违约。 |
| 配置 | `app/build.gradle.kts`、`AgentConfig.kt` | `local.properties`：`agent.baseUrl`（https；http 只允许 debug 下的 10.0.2.2/127.0.0.1/localhost）、`agent.demo`（仅 debug 生效）。 |
| 会话逻辑 | `ui/agent/AgentAssistantViewModel.kt` | 建会话、提交回合、按 `after_seq` 轮询并按 `seq` 去重、草稿按 revision 合并、`auth_required` 自动恢复一次、澄清续答、停止、历史重建；同一请求重试复用 `client_request_id`。 |
| 确认执行 | `ui/agent/AgentAssistantViewModel.kt`、`ProposalDraftCard.kt` | 后端草稿的「确认记账」可用：按钮进入「确认中…」，202 后记录执行回执（执行 ID + 回合状态）并从返回的 `event_cursor` 继续轮询；执行中显示「正在记账」，`RECOVERING`/unknown 一律显示「正在核对结果」，绝不显示成功或失败；501 显示「执行暂不可用」；失败可重试且复用同一 `client_request_id`。演示草稿（simulation）永远不可执行。 |
| 页面上下文 | `ui/agent/AgentUiContext.kt` | 当前路由 → `UiContext.page_type` / `activity_id` / `selected_entity`，以及面板的「正在看：…」文案；参与人/账本 UUID 用已加载的活动详情解析成名字。 |
| 悬浮入口 | `AgentFloatingEntry.kt`、`AgentEntryController.kt` | 左下边缘索引贴：点一下滑出、再点打开；4 秒/面板关闭/换页自动收回；可拖动并排除系统返回手势；有进行中回合时握条变琥珀色。 |
| 底部抽屉 | `AgentBottomSheet.kt`、`AgentSheetPhysics.kt` | 全开/半开/关闭三档；上拉过头橡皮筋阻尼；松手按速度投射选锚点；与对话列表嵌套滚动联动。 |
| 面板与动效 | `AgentAssistantSheet.kt`、`ProposalDraftCard.kt`、`AgentMotion.kt` | 草稿「落笔」（描边画出 → 票头铺满 → 金额滚动）、流式回复、思考流光、空状态建议说法；系统关闭动画时全部降级为静态。 |
| 离线演示 | `src/debug/.../DemoAgentRepository.kt` 等 | `agent.demo=true` 时用本机剧本模拟服务端，release 不含此代码。 |
| 调试预览页 | `src/debug/.../AgentUiPreviewActivity.kt` | `adb shell am start -S -n com.ffocalors.sharedledger/com.ffocalors.sharedledger.debug.AgentUiPreviewActivity --es state <state>`，state：`empty` `backend` `simulation` `inactive` `clarification` `error` `running` `entry` `entry-revealed` `entry-active` `sheet`。 |

测试：`./gradlew.bat :app:testDebugUnitTest` 359 项全部通过（2026-10-22），另 `:app:assembleDebug`、`:app:compileReleaseKotlin` 通过。界面与手感由用户真机验收通过（演示模式）。

## 接入真实 Agent 服务的步骤

1. 启动 Agent 服务（`shared-ledger-agent/agent`），`.env` 里 `AGENT_SUPABASE_AUTH_BASE_URL` / `AGENT_SUPABASE_API_KEY` 必须与 App 当前用的 Supabase 项目一致（App 现在是 `supabase.environment=hosted`），否则所有请求都会是 `unauthenticated`。
2. 本机联调：`adb reverse tcp:8765 tcp:8765`，`local.properties` 设 `agent.baseUrl=http://127.0.0.1:8765` 并删掉或设 `agent.demo=false`，重新构建 debug。
3. 设备或测试环境部署：服务需 https 地址，写入 `agent.baseUrl`（或环境变量 `AGENT_BASE_URL`）。

## 待 Agent 侧决定的契约缺口

| 缺口 | 现状 | 影响 | 需要 |
|---|---|---|---|
| 历史里没有用户原话 | `TurnSummary` 与事件都不带用户提交的文字 | 从历史打开的对话只显示助手一侧 | 在 `TurnSummary` 或事件里加入用户输入文本（或 App 本地缓存，二选一） |
| 草稿只有参与人 UUID | `ExpensePreview` 不含名字 | 不在当前活动页时只能显示「N 位参与人」 | 预览附带显示名，或 App 按 `activity_id` 主动加载活动详情 |
| 调整草稿 | `resume/proposal-adjust` 已有客户端方法，未做界面 | 用户只能重新描述 | 确定交互后补 UI |

已解决：确认写入的成功响应（Agent `627d534`，202 `ProposalExecutionAccepted`）。服务端 `execution_enabled` 仍可回滚到冻结的 501，App 两条路径都已处理。

## 已知限制

- 面板打开时旋转屏幕，抽屉不会重新吸附到锚点。
- 思考流光固定扫过 200dp，短状态文字每圈有一小段空白。
- 读屏的抽屉自定义操作、系统关闭动画下的降级路径已实现，未做专门验证。
