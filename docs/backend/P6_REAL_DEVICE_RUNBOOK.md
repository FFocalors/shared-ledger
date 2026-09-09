# P6 真机联调 Runbook

本 Runbook 用于在不暴露凭据的前提下执行 SharedLedger 的本地 Supabase 与真机双账号验收。当前状态为 `Integration Phase 4 COMPLETE / E2E Acceptance NOT READY`；本地核心服务和 migration 已验证，真机与双账号 E2E 仍待执行。

## 1. 本地环境检查

在仓库根目录执行以下检查。命令输出、截图和日志不得包含 publishable key、access token、refresh token、service role key、数据库密码或其他密钥。

```powershell
$supabaseCli = 'D:\computer\Hermes\tools\supabase\2.116.0\supabase.exe'
docker version
docker ps --format "NAME={{.Names}} STATUS={{.Status}} PORTS={{.Ports}}"
& $supabaseCli status > "$env:TEMP\shared-ledger-supabase-status.log" 2>&1
```

确认 DB、Kong、Auth、REST、Storage、Realtime 和 Studio 容器已启动；`vector` 是日志辅助服务，异常不等同于核心 API 失败。使用本地 HTTP 状态码检查核心入口：

```powershell
curl.exe --noproxy "*" --silent --show-error --output NUL --write-out "%{http_code}`n" http://127.0.0.1:54321/auth/v1/health
curl.exe --noproxy "*" --silent --show-error --output NUL --write-out "%{http_code}`n" http://127.0.0.1:54321/rest/v1/
curl.exe --noproxy "*" --silent --show-error --output NUL --write-out "%{http_code}`n" http://127.0.0.1:54321/storage/v1/status
curl.exe --noproxy "*" --silent --show-error --output NUL --write-out "%{http_code}`n" http://127.0.0.1:54321/realtime/v1/websocket
curl.exe --noproxy "*" --silent --show-error --output NUL --write-out "%{http_code}`n" http://127.0.0.1:54323/
```

只检查本地 migration：

```powershell
& $supabaseCli migration list --local
```

### 1.1 本地双账号 API/RLS 前置 smoke

在确认本地核心服务健康后，可运行仅使用用户 Session 的 Activity/Participant API smoke：

```powershell
.\scripts\run-local-dual-account-api-smoke.ps1
```

2026-09-08 已实际运行通过：18/18 项 PASS，覆盖 A/B 注册、Activity 创建、Participant 创建、加入码加入、Participant Claim、A/B RLS 事实读取、非成员不可见和 Member 执行 Creator-only 设置被拒绝。脚本只连接 `127.0.0.1:54321`，不使用 service role、数据库直连或 hosted 项目；本次生成的两个本地测试账号及 Activity/Participant 记录会保留，执行本地 Supabase reset 后清理。该结果是本地 API/RLS 前置证据，不等于真机、双客户端 Realtime 或完整 E2E 验收。

### 1.2 本地双账号 Realtime 前置 smoke

Realtime 协议依据 Supabase 官方 [Realtime Protocol](https://supabase.com/docs/guides/realtime/protocol)：本地连接使用 JSON `1.0.0`、`phx_join`、`config.postgres_changes` 和用户 Session 的 `access_token`；Join reply、订阅 ID、schema/table/event、过滤后的 `record` 均须逐项匹配。运行：

```powershell
.\scripts\run-local-dual-account-realtime-smoke.ps1
```

2026-09-08 本地双账号 Realtime smoke 已实际通过：11/11 项 PASS，确认 A 的 `participant_claims INSERT` 订阅在 B Claim 后收到匹配的 Activity/Participant/User UUID，且 B 的 `activities UPDATE` 订阅在 A 修改设置后收到匹配的 Activity UUID 与新名称。脚本校验了 Join reply、订阅 ID、schema/table/event、过滤条件和事件 record；只连接 `127.0.0.1:54321`，不输出原始帧或凭据。该结果是本地 Realtime 前置证据，不代表 Android Coordinator、前后台、断网、DELETE/RLS 补读或完整 P3/真机 E2E 验收。本轮及前序运行产生的本地测试账号及业务记录保留，执行本地 Supabase reset 后清理。

### 1.3 本地双账号 Storage 前置 smoke

Storage 验证脚本为 `scripts/run-local-dual-account-storage-smoke.ps1`，按冻结的 pending metadata → object upload → complete 流程执行，且只使用本地普通用户 Session。2026-09-08 已完成针对性响应字节读取修复并实际通过：17/17 项 PASS，覆盖 A/B/C 注册、Activity/LedgerUnit/Participant 准备、A 创建 pending metadata、PNG 对象上传、complete、A/B metadata 读取与对象字节校验，以及 C 非成员 metadata 不可见和对象下载 4xx 拒绝。该结果是本地 Storage REST/RLS 前置证据，不代表真机 Storage、上传中断或完整 E2E 验收。生成的本地账号、metadata 和对象保留，执行本地 Supabase reset 后清理。

### 1.4 单真机 Realtime companion

当真机账号 A 已在 Activity 内创建至少一个尚未 Claim 的 Participant 时，可让桌面脚本账号 B 加入同一 Activity，反向触发 A 页面观察成员/Claim 更新，再由真机 A 修改 Activity 名称，验证桌面 B 的同 Activity `activities UPDATE` 订阅和 REST 最终重读。脚本只创建本地普通账号 B；加入码通过隐藏的 SecureString 交互输入，既不回显也不写入日志。

```powershell
# 只有一个未 Claim Participant 时自动选择
.\scripts\run-local-device-realtime-companion.ps1

# 有多个可 Claim Participant 时指定显示名称（必须精确匹配）
.\scripts\run-local-device-realtime-companion.ps1 -ParticipantName "待 Claim 的 Participant 名称"
```

执行顺序：确认 `adb devices -l` 中真机为 `device`，使用 [connect-local-supabase-device.ps1](../../scripts/connect-local-supabase-device.ps1) 完成 `adb reverse tcp:54321 tcp:54321`；在真机 A 页面准备 Activity 和未 Claim Participant；桌面执行 companion，在隐藏输入提示中输入加入码；确认 A 页面收到 B 加入/Claim 后，再在 A 编辑 Activity 名称。脚本最多等待配置的时长（默认 30 秒），会校验 B 收到的 `phx_reply`、订阅 ID、`public.activities`、`UPDATE`、Activity UUID 和名称变化，并通过 REST 重读最终名称，只输出名称 hash/长度。

观察证据应同时记录：A 页面成员/Participant Claim 变化、B 脚本的 HTTP/Realtime PASS、Activity UUID、最终名称 hash/长度，以及双方时间线。该工具补充一台真机与桌面普通用户的并发观察，不能证明两台 Android UI、Android Coordinator 前后台恢复、断网重连、DELETE/RLS 补读或完整 P3/E2E。

## 2. 真机连接与本地 URL

在真机启用 Developer options 和 USB debugging，首次连接时在设备上确认 RSA 调试授权。确认：

```powershell
adb devices -l
```

设备状态必须为 `device`。本项目 Debug 配置允许 loopback 明文访问；`local.properties` 只需要存在以下键名，值不要写入文档、提交或日志：

```properties
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_PUBLISHABLE_KEY=<本机安全配置，不写入文档>
```

推荐使用连接脚本完成环境检查、设备选择、端口映射和可选的构建/安装/启动。没有传入 serial 时，脚本只会自动选择唯一一台 `device` 状态的设备；`offline`、`unauthorized` 不会被选择。多台授权设备时必须显式指定：

```powershell
# 自动选择唯一授权真机，并执行构建、安装、启动
.\scripts\connect-local-supabase-device.ps1

# 多台授权设备时显式指定 serial
.\scripts\connect-local-supabase-device.ps1 -DeviceSerial <serial>
```

脚本在核心容器缺失或停止时会调用固定路径的 Supabase CLI 尝试启动本地栈，然后重新检查最终容器状态；核心容器已完整运行时不会重启。脚本不会清除应用数据、创建账号、修改 `local.properties` 或移除 reverse 映射；错误会区分无设备、未授权/离线设备、多设备、Docker/核心容器、URL 配置、构建、安装和启动失败。

通过 USB 将真机的 loopback 端口映射到主机本地 Supabase：

```powershell
adb reverse tcp:54321 tcp:54321
```

`adb reverse` 的语法是 `adb reverse [--no-rebind] REMOTE LOCAL`；`adb reverse --help` 本身不是有效帮助参数。映射完成后，真机使用 `http://127.0.0.1:54321`，不使用模拟器专用的 `10.0.2.2`。

## 3. 构建与安装

```powershell
.\gradlew.bat :app:assembleDebug --console=plain
adb -d install -r .\app\build\outputs\apk\debug\app-debug.apk
```

当前 Debug 构建门禁已通过；APK 位于 `app/build/outputs/apk/debug/app-debug.apk`。用户后续可在 Android Studio 中同步、构建、安装并运行，本文档不将该构建结果视为真机或完整 E2E 验收。

如果连接了多台设备，使用 `adb -s <serial>` 替代 `-d`，serial 只记录在本地验收材料中。

## 4. 双账号策略

账号 A 使用 Creator 角色，账号 B 使用 Member 角色；两者必须是独立认证 Session。账号标识可以记录，密码、token 和 key 不得记录。按 [E2E_ACCEPTANCE_CHECKLIST.md](./E2E_ACCEPTANCE_CHECKLIST.md) 从活动创建、加入/Claim、Expense、资金流、附件、争议、归档到恢复执行。

只有一台真机时，账号 B 可以使用受控的本地 API harness 辅助验证 REST/RPC 结果，但在设备上顺序退出再切换账号不算完整双端验收。Realtime 双向同步必须同时存在第二个并发客户端，例如第二台真机、模拟器或受控 harness；否则只能记录为部分验收。

## 5. 证据记录

记录日期及时区、commit、APK 路径与 hash、设备型号/Android 版本、A/B 账号标识、核心容器健康状态、migration 数量、客户端页面结果、数据库事实和 Realtime 刷新证据。截图和日志统一脱敏；不要复制 `supabase status` 的完整输出。

## 6. 清理

验收结束后移除本次 USB 端口映射：

```powershell
adb reverse --remove tcp:54321
```

仅在确认设备没有其他任务使用 reverse 映射时，才使用 `adb reverse --remove-all`。本地 Supabase 的停止、重置和数据清理必须另行确认，不属于真机验收必需步骤。
