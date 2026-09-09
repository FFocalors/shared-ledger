# Android Supabase 配置说明

Phase 1 只启用 Supabase Auth、PostgREST 和 Android Ktor 网络引擎。Compose
页面不直接依赖 Supabase SDK，调用链为：

```text
AuthScreen -> AuthViewModel -> AuthRepository -> SupabaseAuthRepository -> SupabaseClient
```

## 本地配置

在未提交的 `local.properties` 中添加：

```properties
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_your-key
```

旧项目也可以暂时使用 `SUPABASE_ANON_KEY` 作为兼容变量名。只使用
publishable/anon key；`service_role`、`sb_secret_`、数据库密码和 Storage
管理凭据禁止进入 Android 工程、APK 或日志。`local.properties` 已被 Git
忽略，环境变量可作为同名配置的后备来源。

缺少或格式不合法的配置会安全降级到 Auth 错误状态，不会启动带假账号的
DemoAuth，也不会绕过认证进入 Home。

## Auth 密码恢复回跳

在 Supabase Dashboard 的 `Authentication → URL Configuration → Redirect URLs`
中必须加入以下精确地址：

```text
sharedledger://auth/reset
```

该地址必须与 Android App 注册的 deep link scheme、host 和 path 完全一致；不要用
`http://localhost` 或带额外路径的地址替代。配置完成后，使用真实测试账号验证：

1. 在 Auth 页面请求忘记密码邮件，打开 recovery link 并确认 App 能进入重置密码流程。
2. 冷启动验证：先 force-stop App，再从邮件打开 link，完成新密码设置，返回 App 后重新登录并确认进入 Home。
3. 热启动验证：保持 App 在前台或后台，从邮件打开 link，完成新密码设置，确认当前页面正确回到 Auth/Recovery 状态，重新登录后不会复用旧账号数据。

每次验证都记录设备、构建变体、回跳结果和最终 Session 状态；不记录邮件中的 token 或密码。

## 版本冻结

- Supabase Kotlin BOM、core、Auth、PostgREST：`3.8.0`，Maven Central 稳定版；
- Ktor Android engine：`3.5.1`，与 supabase-kt 3.8.0 的发布依赖一致；
- Kotlin/serialization：`2.4.0` / `1.11.0`；
- coroutines：`1.11.0`。

选择依据：Supabase 官方 Kotlin 文档当前使用 `createSupabaseClient`、
`install(Auth)`、`install(Postgrest)`，并以 `sessionStatus`、
`currentSessionOrNull`、`signUpWith(Email)` 和 `signInWith(Email)` 为当前 API；
supabase-kt 官方仓库的最新稳定发布为 3.8.0，Maven Central 已提供对应的
Android 模块。3.8.0 发布依赖 Kotlin stdlib 2.4.0 和 Ktor 3.5.1，因此项目
同步到这些固定版本，未引入 Storage 或 Realtime。

## Session 与 Profile

Auth 插件使用默认持久化 Session Manager，并在启动时等待 SDK 初始化完成。
`sessionStatus` 的 `Initializing`、`Authenticated`、`NotAuthenticated` 和
`RefreshFailure` 分别映射到统一 Auth 状态。注册把昵称写入 Auth metadata 的
`display_name` 字段；当前冻结 migration 的 `on_auth_user_created` trigger
据此创建 `public.profiles.display_name`，登录/恢复后通过受 RLS 保护的
`profiles` 查询读取昵称。

## 当前验收状态

Docker Engine 29.7.2 与 Supabase CLI 2.116.0 已验证。2026-09-08 本地空库已应用
当前全部 17 条 migration；8 个 pgTAP 脚本共 94 项 assertion 通过，5 个 plain SQL
assert 脚本经本地 `psql -v ON_ERROR_STOP=1` 通过，共 13/13。plain SQL assert
数量不计入 pgTAP 统计。
本地 API URL 和 publishable key 已写入 Git 忽略的 `local.properties`。Android
模拟器可通过 `10.0.2.2:54321` 访问宿主服务；真机不能使用该模拟器专用地址，
Debug 配置应使用 `http://127.0.0.1:54321`。推荐在 USB 调试并确认 RSA 后使用连接脚本：

```powershell
# 仅有一台授权真机时自动选择
.\scripts\connect-local-supabase-device.ps1

# 多台授权真机时显式指定 serial
.\scripts\connect-local-supabase-device.ps1 -DeviceSerial <serial>
```

脚本会先检查 Docker 和本地 Supabase 核心容器，再建立 `adb reverse tcp:54321 tcp:54321`、
验证真机端口可达，并执行 Debug 构建、安装和启动。手机或电脑重启、USB 重连后需要
重新执行；该方案不会把本地 Supabase 暴露到局域网。Release 仍不允许本地 HTTP。
核心容器缺失或停止时，脚本会使用固定 Supabase CLI 路径尝试启动本地栈并重新检查最终状态；
核心容器完整运行时不会重启本地栈。

完整的本地健康检查、设备选择、双账号策略、证据记录和 reverse 清理步骤见
[P6_REAL_DEVICE_RUNBOOK.md](./P6_REAL_DEVICE_RUNBOOK.md)。

代码单元测试、Debug APK 和 Release Kotlin 编译已通过。Auth API 已完成“注册 →
登录 → 当前用户/session → Profile → 退出”的真实本地链路；真机已完成“进入 Home →
force-stop → 重启恢复 Session → 退出回 AuthScreen → 重新登录进入 Home”的完整验收。
`adb reverse` 仅用于 Debug 本地联调，手机或电脑重启、USB 重连后需要重新建立。
Supabase `vector` 日志服务重启属于已知非阻塞技术债，不影响 Auth、DB、Kong、REST
等核心服务。Phase 1–4 Android 真实接线已完成；Phase 2–4 完整验收及 Phase 5 Storage、Realtime 与双账号 E2E 仍待执行。后续步骤见 [ANDROID_INTEGRATION_COMPLETION_PLAN.md](./ANDROID_INTEGRATION_COMPLETION_PLAN.md)。
