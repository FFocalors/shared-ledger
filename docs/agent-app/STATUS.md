# Agent 应用端：当前状态与后续接入（2026-10-22）

分支 `feature/dev-workflow`。对应 Agent 侧契约 `shared-ledger-agent/agent/contracts/v1.1.0`（api **1.1.0**，operations / semantic 仍为 1.0.0，56 个生成文件）。两份快照并存于测试资源：`agent-contract-v1.1.0/`（当前）与 `agent-contract-v1.0.0/`（历史）。视觉与交互方案见 [UI_PLAN.md](UI_PLAN.md)。

## 已完成（只读阶段）

| 模块 | 位置 | 说明 |
|---|---|---|
| 契约数据层 | `data/agent/` | v1 全部请求/响应/事件/草稿卡片 DTO；Ktor 客户端，Bearer 取 Supabase 当前会话 token；结果统一为 `AgentApiResult`；未知枚举/事件类型降级为 `UNKNOWN`/`Unknown`，不让整次轮询失败；确认接口同时接受 202 与 501，其他 2xx 视为契约违约。 |
| 配置 | `app/build.gradle.kts`、`AgentConfig.kt` | `local.properties`：`agent.baseUrl`（https；http 只允许 debug 下的 10.0.2.2/127.0.0.1/localhost）、`agent.demo`（仅 debug 生效）。 |
| 会话逻辑 | `ui/agent/AgentAssistantViewModel.kt` | 建会话、提交回合、按 `after_seq` 轮询并按 `seq` 去重、草稿按 revision 合并、`auth_required` 自动恢复一次、澄清续答、停止、历史重建；同一请求重试复用 `client_request_id`。 |
| 确认执行 | `ui/agent/AgentAssistantViewModel.kt`、`ProposalDraftCard.kt` | 后端草稿的「确认记账」可用：按钮进入「确认中…」，202 后记录执行回执（执行 ID + 回合状态）并从返回的 `event_cursor` 继续轮询；执行中显示「正在记账」，`RECOVERING`/unknown 一律显示「正在核对结果」，绝不显示成功或失败；501 显示「执行暂不可用」；失败可重试且复用同一 `client_request_id`。演示草稿（simulation）永远不可执行。 |
| P5 预览（api 1.1.0） | `data/agent/AgentDtos.kt`、`ui/agent/ProposalPresentation.kt` | 25 个 proposal operation 均有标题与一句话摘要；9 种 preview 按 `kind` 解码（expense / management / refund / prepayment / prepayment_return / negative_adjustment / repayment / transfer_void / final_settlement），未知 kind 解码为 `UnknownPreview` 并以服务端摘要兜底，未知 operation 落为 `UNKNOWN` 并显示通用标题「变更草稿」。卡片渲染对每种 preview 都有显式分支，不会白屏。 |
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

## 本机联调：推荐流程

脚本位于 `agent/deploy/scripts/`：`dev-up.ps1` 准备 LM Studio、模型、Agent 和 USB reverse；`dev-agent-watch.ps1` 每 5 秒恢复映射（`-Once` 单次）；`install-dev-autostart.ps1` 安装当前用户登录任务（`-Uninstall` 撤销）。脚本支持 AgentRoot、Lms、Adb、LogRoot 参数；日志根必须保留在 D:。不读取或打印 .env 内容。

### 从零到真机可用

AgentRoot 默认依次检查 `AGENT_DEV_ROOT`、`D:\project\Android\shared-ledger-agent\agent`、脚本目录上两级的 `agent/`，选择包含 `.venv/Scripts/python.exe` 和 `app/main.py` 的首个目录。环境不同请给两个脚本显式传入 `-AgentRoot "E:\your-agent-repo\agent"`；Android Studio External Tool 参数也加上同一参数。显式路径无效时直接报错，不回退。登录任务保存解析后的绝对 AgentRoot；路径变更后重新运行安装脚本。卸载任务不依赖 AgentRoot 仍然存在。

1. 在普通 PowerShell 终端进入 Agent 仓库 `agent/deploy/scripts`，确认 agent/.env 已由本机配置、venv 依赖已安装、LM Studio 模型可用。不要从沙箱进程启动服务。
2. 执行 `powershell -ExecutionPolicy Bypass -File .\install-dev-autostart.ps1` 一次安装登录任务，再执行 `powershell -ExecutionPolicy Bypass -File .\dev-up.ps1` 准备当前会话。不需要提升权限；若系统策略拒绝注册，请联系管理员，不自动提权。
3. USB：手机打开 USB 调试并授权，只连接一个设备。脚本等待设备最多 30 秒，验证 `adb reverse --list`。App debug 设置 `agent.demo=false`、`agent.baseUrl=http://127.0.0.1:8765` 后重建。
4. Android Studio：Settings → Tools → External Tools → Add。Program 为 `powershell.exe`；Arguments 为 `-NoProfile -ExecutionPolicy Bypass -File "<Agent仓库>\agent\deploy\scripts\dev-up.ps1"`；Working directory 为 `<Agent仓库>\agent`。Run/Debug Configurations → Before launch → Add → Run External Tool，选择此工具。路径填本机实际值，不提交 IDE 私有配置。
5. LAN：先停止自己启动的 USB 模式 Agent，再在普通终端运行 `dev-up.ps1 -Lan`。它使用 `AGENT_LISTEN_HOST=0.0.0.0` 并列出私有 IPv4，跳过 adb。登录任务改为 `install-dev-autostart.ps1 -Uninstall` 后 `install-dev-autostart.ps1 -Lan`；External Tool 参数也加 `-Lan`。local.properties 设置 `agent.demo=false`、`agent.baseUrl=http://<局域网IP>:8765`，重新构建 debug。release 仍只允许 HTTPS。

LAN 仅限同一可信局域网，不向公网暴露 8765，不开放公用网络配置文件。以下命令仅供用户在管理员 PowerShell 手动执行（脚本不会自动执行）：

```powershell
New-NetFirewallRule -DisplayName 'SharedLedger Agent Dev' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Profile Private -RemoteAddress LocalSubnet
# Revert:
Remove-NetFirewallRule -DisplayName 'SharedLedger Agent Dev'
```

停止：先用 `install-dev-autostart.ps1 -Uninstall` 停止/删除登录任务。Agent 是独立后台进程，卸载任务不会停止它；根据 dev-up 输出的 PID，在任务管理器确认其命令行为指定 venv 的 `python.exe -m app.main` 后结束该进程。不得批量结束所有 Python。移除 USB 映射可运行 `adb reverse --remove tcp:8765`。LM Studio 模型保持加载，脚本不卸载模型、不杀无关进程。切换监听模式时不会自动重启已有 Agent。

### 验证与限制

App：`./gradlew.bat :app:testDebugUnitTest --no-configuration-cache`。新增 `AgentPrivateAddressTest` 覆盖私网、非法/公网/保留地址及 release 配置语义。本机执行受既有 Java toolchain 缺少 jlink.exe 阻断；请在 Android Studio 选择完整 JDK 后运行，不能视为测试通过。

Agent：在 Agent 仓库根运行 `agent\.venv\Scripts\python.exe -m pytest agent/tests -q`，必须整个目录一次调用，并为每轮设置全新且不同的 `P2_STORE_TEST_ROOT` 和 `P2_V3_STORE_TEST_ROOT`（D: 盘）。不要在 agent 子目录直接执行此测试命令。

PowerShell 三个脚本通过语法解析；LM Studio `server status --json` 只读检查已验证。尚未实际安装登录任务、启动模型/服务、验证真机 USB 重连或 LAN 防火墙。多设备需通过 ANDROID_SERIAL 选择设备；LAN 地址可能包含虚拟网卡，请选择手机可达的网卡。现有模型若已加载，脚本不会重载以修改其上下文参数。

Agent 测试还需同时设置模块路径。在仓库根执行：

```powershell
$env:PYTHONPATH="$PWD;$PWD\agent"
$stamp=[guid]::NewGuid().ToString('N')
$env:P2_STORE_TEST_ROOT="D:\AI\runtime\shared-ledger-agent\tests-$stamp\store"
$env:P2_V3_STORE_TEST_ROOT="D:\AI\runtime\shared-ledger-agent\tests-$stamp\v3"
New-Item -ItemType Directory -Force $env:P2_STORE_TEST_ROOT,$env:P2_V3_STORE_TEST_ROOT | Out-Null
agent\.venv\Scripts\python.exe -m pytest agent/tests -q
```

本次 Agent 全量实际结果（2026-10-23）：764 passed、7 failed、1 xfailed。整个 agent/tests 目录一次调用，两个 store 根每轮新建。7 项失败均位于 test_p2_read_backend.py，报 `candidate Turn deadline is outside the reviewed bound`；本次未修改这些业务代码或测试，不能宣称全套通过。App 单测尚未执行成功，阻断为既有 toolchain 指向缺少 jlink.exe 的 JRE。


## 开发环境 vs 正式发布

当前推荐且使用的本机流程是 USB + adb reverse。`dev-up.ps1 -Lan` 为**实验性，当前不使用**；此前 LAN 配置步骤仅作未来参考。debug-only 私有地址支持**当前未启用，保留待用**：代码保留允许能力，但本流程不配置 LAN 地址，也不启用 LAN 登录任务。它不是新增的运行时功能开关。

| 内容 | 开发用途 | 与正式发布的隔离 |
|---|---|---|
| `local.properties` | 本机 SDK、`agent.baseUrl`、`agent.demo` | 不提交；文件不会作为配置文件打包，但 URL 会进入 BuildConfig，不能仅靠 gitignore 隔离。release 构建期检查最终 URL；CI 使用正式配置或留空。 |
| Agent `.env` | 本机 Agent 配置及凭据 | 不提交、不打印、不复制到 App；正式部署独立提供配置与密钥，不能复用开发 .env。 |
| `src/debug` | 调试网络配置、预览 Activity、Demo 实现 | Android source set 隔离，不进入 release。 |
| `agent.demo` | debug 离线演示 | 仅 debug 读取此值；release 的 AGENT_DEMO 固定 false。 |
| debug-only 私有地址 | RFC1918 本机 LAN 联调能力 | 当前未启用，保留待用；只有 debug 的 allowLocalHttp 可放行 HTTP。release 运行时仍只允许 HTTPS，逻辑不变。 |
| `agent/deploy/scripts` 中 `dev-up`、`dev-agent-watch`、`install-dev-autostart` | LM Studio、本机 Agent、adb、当前用户登录任务 | 开发运维脚本不属于 APK source set，不作为正式服务部署入口；登录任务仅本机当前用户。目录中其他部署脚本按各自部署文档使用，不能将整个目录认定为开发专用。 |

正式构建新增 `:app:checkReleaseAgentEndpoint`，挂到 `preReleaseBuild` 与 `generateReleaseBuildConfig`。最终 `AGENT_BASE_URL` 为空时保留 Agent 未配置语义；非空必须为 HTTPS，拒绝 HTTP、私有 IPv4/IPv6、本地/回环/链路本地地址。错误仅说明配置来源和原因，不打印 URL。`local.properties` 的 `agent.baseUrl` 优先于环境变量，正式构建前应检查该来源。检查不进行 DNS 查询，因此域名解析到内网的情况仍由正式发布配置审核负责。此任务只在构建期拦截，不改变 release 运行时行为。

可单独执行 `./gradlew.bat :app:checkReleaseAgentEndpoint --no-configuration-cache`，不需要编译 Android Java 源码。查看 LAN 帮助：`Get-Help .\agent\deploy\scripts\dev-up.ps1 -Parameter Lan`。

本次验证：9 项地址用例通过（留空、公网 HTTPS 允许；HTTP、RFC1918、回环、IPv6 ULA/链路本地拒绝），两个 release 任务依赖检查通过。当前开发配置下直接运行检查任务按预期失败。未修改 local.properties/.env，未执行发布或改变运行时逻辑。
