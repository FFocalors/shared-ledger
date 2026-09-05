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

Docker Engine 29.7.2 与 Supabase CLI 2.116.0 已验证。本地栈已启动，空库已
顺序应用全部 16 条 migration，migration 文件未被修改。`supabase test db --local`
执行结果为 7 个脚本的 78 项断言通过；5 个历史脚本因缺少 TAP plan 被 pg_prove
报告解析失败，属于现有数据库测试脚本兼容性问题。
本地 API URL 和 publishable key 已写入 Git 忽略的 `local.properties`。Android
模拟器可通过 `10.0.2.2:54321` 访问宿主服务；真机不能使用该模拟器专用地址，
Debug 配置应改为 `http://127.0.0.1:54321`，并在 USB 调试连接后执行：

```powershell
.\scripts\connect-local-supabase-device.ps1 -Install
```

脚本会建立 `adb reverse tcp:54321 tcp:54321`、验证真机端口可达，并可选安装
最新 Debug APK。手机或电脑重启、USB 重连后需要重新执行；该方案不会把本地
Supabase 暴露到局域网。Release 仍不允许本地 HTTP。

代码单元测试、Debug APK 和 Release Kotlin 编译已通过。Auth API 已完成“注册 →
登录 → 当前用户/session → Profile → 退出”的真实本地链路；真机已完成“进入 Home →
force-stop → 重启恢复 Session → 退出回 AuthScreen → 重新登录进入 Home”的完整验收。
`adb reverse` 仅用于 Debug 本地联调，手机或电脑重启、USB 重连后需要重新建立。
Supabase `vector` 日志服务重启属于已知非阻塞技术债，不影响 Auth、DB、Kong、REST
等本阶段核心服务。Phase 1 已完成，未修改 migration，Phase 2 尚未开始。
