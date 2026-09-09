# Android × Supabase 联调收口计划

> 状态：`执行计划`
>
> 基线：`8bbfa11`（Integration Phase 4）
>
> 当前结论：`Integration Phase 4 COMPLETE`；`E2E Acceptance NOT READY`

## 1. 目标与范围

本计划承接已经完成的 Phase 1–4 Android 真实接线，负责完成以下收口：

1. 修复已经识别出的账务可靠性问题和业务入口缺口。
2. 接入冻结契约中的 Storage 图片附件。
3. 建立 Activity-scoped Realtime Coordinator。
4. 补齐 Phase 2–4 遗留的双账号、权限、并发与异常验收。
5. 清除正式运行路径中的 Demo/Fake 数据和静默空操作。
6. 以双账号完整 E2E 证据将项目升级为 `E2E Acceptance READY`。

争议审批/仲裁、历史版本比较与恢复、非图片附件、第三方汇率抓取任务和自定义事件总线继续保持延期，不纳入本轮收口。

## 2. 状态口径

| 范围 | 实现状态 | 验收状态 |
| --- | --- | --- |
| Phase 1 Auth | 完成 | 已完成真机主链验收 |
| Phase 2 Activity / Identity | 完成 | 双账号主链通过，负向与管理操作待补齐 |
| Phase 3 Expense | 完成 | 双账号、并发和服务端投影待验收 |
| Phase 4 Financial | 完成 | 真机资金链、争议、作废和 Final Settlement 待验收 |
| Phase 5 Storage / Realtime / E2E | P2/P3 Android 代码接线完成 | 真实环境未验收 |

“完成”只表示代码已经接入真实 Supabase，不自动代表权限、异常、双端一致性和运行环境验收通过。

## 3. 不可破坏的基线

- 后端契约以当前 `supabase/migrations/`、`BACKEND_INTEGRATION_READINESS.md` 和数据库测试为准。
- 不修改已经应用的 migration。发现真实契约缺口时，先记录决策，再新增 migration、数据库测试和契约文档修订。
- Android 只使用 publishable/兼容 anon key 和用户 Session，不引入 `service_role`、secret key 或数据库密码。
- 金额事实使用 `BigDecimal`/PostgreSQL `numeric`；Android 不计算或持久化服务端债务投影。
- Realtime 只负责通知数据失效，事件到达后重新读取服务端事实与投影。
- `@Preview` 和纯 UI 测试可以保留 Sample Data；正式导航、Repository Factory 和运行时错误回退不得返回 Demo/Fake 业务数据。
- 对结果未知的资金写入不得直接再次提交，必须先重新读取服务端确认是否已落账。

## 4. 开发流程总览

```text
P0 基线与验收设施
  → P1 Phase 4 收尾与业务补口
  → P2 Storage
  → P3 Realtime Coordinator
  → P4 异常、权限与并发矩阵
  → P5 Runtime Demo/Fake 清零
  → P6 双账号完整 E2E 与发布门禁
```

每个阶段独立提交、独立验收。前一阶段的阻塞问题处理完成后再进入下一阶段；不以最终大批量测试代替阶段性验证。

## 5. P0：基线与验收设施

### 开发内容

- 固定基线提交、Android/Supabase 版本、测试设备和两个测试账号角色。
- 建立可重复的本地环境准备与数据清理步骤；不在文档、脚本输出或截图中记录 key、token、密码。
- 建立无歧义的数据库测试入口：为应由 `pg_prove` 执行的脚本补齐 TAP plan，其他 SQL 验证脚本从该入口显式排除并单独执行。
- 为双账号验收准备证据模板，记录 Android 操作、另一端结果、数据库事实和最终投影。

### 退出门槛

- [ ] `git status` clean，基线提交可追溯。
- [ ] Android 单元测试全绿；当前参考基线为 105 项。
- [ ] 空本地数据库可应用当前 17 条 migration。
- [ ] 数据库测试统一入口全绿，不再混有“断言通过但脚本解析失败”。
- [ ] A（Creator）与 B（Member）账号、设备及环境已固定。

## 6. P1：Phase 4 收尾与业务补口

### 6.1 资金写入结果状态

将资金写入结果明确区分为：

```text
明确失败
已保存且刷新成功
已保存但刷新失败
请求结果未知，需重新读取确认
```

预存、预存返还、作废、争议和 Final Settlement 不再把“RPC 成功后的详情读取失败”显示为普通写入失败。结果未知时冻结重复提交入口，以 transfer ID、Activity 数据刷新或资金记录查询确认最终状态。

### 6.2 已识别缺陷

- 将 `SupabaseClient` 收敛为应用级共享实例，Auth、Activity、Expense、Transfer、Financial、Storage 和 Realtime Repository 复用同一 Session 生命周期；禁止各 Factory 独立创建互不协调的客户端。
- 多币种开关必须保留当前 Activity 的真实 `base_currency`，不能固定回传 CNY。
- 未结债务提示必须依据结构化金额/服务端状态，不能比较格式化字符串。
- 归档状态、当前角色和记录归属共同决定页面写入口；服务端拒绝仍是最终保障。
- 将 `participants_locked_at` 接入 Activity DTO/domain/UI；名单锁定后解释为什么不能新增/删除 Participant，同时仍允许 Claim 已有 Participant。
- 资金详情优先按 transfer ID 精确读取，避免每次加载整个 Activity 的资金历史。

### 6.2.1 P1a 实际进展（2026-09-07）

本轮已完成 P1a 的客户端基础收敛与相关 UI 防护：

- `SupabaseClientProvider.createOrNull()` 在相同有效配置下复用应用级共享 `SupabaseClient`，并保持 Auth、Activity、Expense、Transfer、Financial 等现有 Repository Factory 调用兼容；无效配置不写入缓存。
- 资金写入结果已结构化区分为 `SUCCEEDED`、`FAILED`、`COMMITTED_REFRESH_FAILED` 和 `UNKNOWN`，为后续按 transfer ID 确认落账及冻结重复提交提供状态基础。
- 资金写入成功后的详情刷新改为按 transfer ID 精确读取，避免通过加载整个 Activity 资金列表判断本次写入结果。
- 多币种设置保留 Activity 当前真实 `baseCurrency`，不再固定回传 CNY。
- 未结债务提示改用结构化金额/状态判断，不再比较格式化金额字符串。
- `participants_locked_at` 已接入 UI；锁定后拦截新增和删除 Participant 操作。

本轮 Android 单元测试共 115 项通过，`compileDebugKotlin` 通过。尚未执行真机验收或真实 Supabase API 验证，因此 P1 整体状态及本节对应的退出门槛仍保持未勾选；P1b 的实际进展见下节。

### 6.2.2 P1b 实际进展（2026-09-07）

本轮已完成 P1b 业务入口和表单收口：

- Creator 代记已覆盖 Transfer、Prepayment、Prepayment Return 和 Final Settlement 四类资金流，提交 `on_behalf_of_participant_id` 并按参与人权限校验。
- Refund 同时支持关联退款和独立退款；关联退款保留 `original_expense_id`，独立退款明确提交 `original_expense_id = null`，金额、付款和分摊统一转换为负数。
- 取消归档入口已接通；归档状态下页面隐藏/禁用写入口，取消归档后由 ViewModel 刷新当前详情和首页。
- 活动名称编辑、复制加入码和删除 Participant 已接入正式管理页面，并保留名单锁定及历史引用限制。
- 忘记密码 recovery 已接入回跳流程；需在 Supabase Dashboard 配置 `sharedledger://auth/reset`，并完成冷启动/热启动 deep link 验收。
- Expense 发生时间改用 UTC+8 日期和时间选择器，内部继续生成合法 `Instant` 字符串，编辑和退款兼容已有 `occurredAt`。
- 资金记录列表已支持按时间正序和倒序查看，刷新后排序状态与服务端记录时间一致。

本轮 `compileDebugKotlin` 和 Expense/Activity/Routes 定向测试通过，但尚未执行真实 Supabase API、真机或双账号验收。因此 P1 退出门槛仍保持未勾选；上述完成项必须在真实环境中补充证据后才能计入发布门禁。

### 6.3 已有业务能力补口

- Creator 代记：Transfer、Prepayment、Prepayment Return 和 Final Settlement 提供代记对象选择，并提交 `on_behalf_of_participant_id`。
- Activity 管理：接入取消归档、删除 Participant、活动资料编辑、复制加入码和已有权限管理操作。
- Refund：同时支持关联退款与独立退款；关联退款保留 `original_expense_id`。
- 忘记密码：接入 Supabase 密码重置流程，并验证回跳/重新登录。
- Expense 发生时间使用日期/时间选择器生成合法时间值，不要求普通用户手输 ISO-8601。
- 资金记录排序按钮必须实现或移除，正式 UI 不保留静默空操作。

### 6.4 契约决策门

以下两项必须在编码前形成明确结论：

| 决策 | 当前事实 | 建议结论 |
| --- | --- | --- |
| LedgerUnit 文字备注 | 业务规格要求支持，当前冻结表与 Android 模型未提供字段 | 作为 V0.1 缺口新增 migration、RPC/DTO 和测试 |
| Final Settlement 旧预览 | Android 保存 `source_financial_version`，执行 RPC 按锁内当前方案方向和金额重新匹配 | V0.1 接受“当前方案仍有效即可执行”；修正文案并增加并发测试。若要求任何版本变化都拒绝，则另行新增契约参数与 migration |

汇率缓存本轮接入已有 `get_exchange_rate` 读取和失效提示；第三方定时抓取继续延期。审计日志先提供最小只读入口，版本比较与历史恢复不进入 V0.1。

### 退出门槛

- [ ] 所有资金写操作都能正确区分写入失败与刷新失败。
- [ ] 代记、取消归档、删除 Participant、独立退款和活动资料编辑可从正式页面完成。
- [ ] 归档、权限不足及成员移除后，客户端不再暴露可执行的写入口。
- [ ] Phase 2–4 相关单元测试和本地真实 API 验证通过。

## 7. P2：Storage 图片附件（代码接线完成，真实 Storage/设备/双账号验收待完成）

P2 当前已完成 Android 侧代码接线，但尚未完成目标 Supabase Storage 的真实上传、设备相机/相册操作和双账号验收。因此本节的退出门槛全部保持未勾选，项目仍为 `Integration Phase 4 COMPLETE` / `E2E Acceptance NOT READY`。

### 7.1 客户端结构

新增并固定 Supabase Kotlin `storage-kt` 依赖，保持以下分层：

```text
Compose 图片选择/拍照
  → Attachment ViewModel
  → Attachment Repository
  → Supabase RPC + Storage API
```

### 7.2 写入协议

```text
选择或拍照
→ 客户端解码与压缩
→ 校验 JPEG/PNG/WebP、10 MiB 和数量上限
→ create_attachment 创建 pending metadata
→ 上传到 activity-attachments 私有 bucket 的服务端返回路径
→ complete_attachment
→ 重新读取附件列表
```

不自行拼接 Activity 路径，不保存永久公开 URL，不绕过 metadata RPC 直接上传。需要替换对象时，必须同时满足 Storage upsert 所需的 INSERT、SELECT、UPDATE 权限；V0.1 优先使用不可变路径和新建上传，减少覆盖语义。

### 7.3 页面范围

- Expense：新增/编辑页选择图片，详情页查看和删除。
- LedgerUnit：独立附件列表、查看和删除。
- Android 直接拍照，同时支持系统图片选择器。
- 归档 Activity 只读；成员可读，上传者或 Creator 在可写状态下删除。

### 7.4 失败与恢复

- metadata 创建失败：不上传对象。
- 上传失败：保留可识别的 pending 状态并允许安全重试/清理。
- `create_attachment` 已返回 `attachmentId` 和服务端 metadata 后，pending/complete 响应未知可以复用同一条 metadata 继续确认、完成或清理；`create_attachment` 请求本身响应丢失时，冻结 RPC 没有客户端幂等键，无法可靠对账，不能笼统承诺不会创建重复 metadata。真实中断验收必须记录并评估该结果。
- 删除操作分别处理 metadata 和对象结果，页面不得在远端失败时静默消失。
- 图片解码、压缩、旋转和大图处理不得阻塞主线程。

### 7.5 P2 实际进展（2026-09-07）

以下能力已按冻结契约完成 Android 代码接线，真实环境仍待验收：

- `AttachmentRepository` 已覆盖附件列表读取、按 Expense/LedgerUnit 读取、下载、创建 metadata、Storage 上传、`complete_attachment`、pending 重试/清理和删除；三步协议为 `create_attachment` → 上传私有 `activity-attachments` 对象 → `complete_attachment`，并保留 metadata/对象部分失败结果。
- `AttachmentViewModel` 已提供 Expense 与 LedgerUnit 的附件加载、图片准备、pending 上传、完成确认、失败重试和删除状态；上传结果不会把 pending 或未知状态静默显示为成功。
- `AttachmentImageProcessor` 已在 IO 线程执行 bounds 读取、采样解码、旋转兼容和压缩，支持 JPEG/PNG/WebP，拒绝空文件、伪 MIME/不支持类型和最终结果超过 10 MiB。
- 系统图片来源已接入可复用基础设施：Photo Picker 按剩余 10 个名额限制，相机使用私有 FileProvider 临时 URI；取消、launcher 异常和回调交付后的临时文件清理均有处理，并解析稳定显示文件名。
- Compose 附件输入控制器已统一相册/拍照 launcher、来源选择对话框、URI+文件名回调和错误回调；图片预览使用 bounds/sample 安全解码，并在生命周期结束时回收 Bitmap。
- Expense 新增/编辑链路和 LedgerUnit 独立附件链路已具备接线入口；详情页具备查看/下载/删除入口，归档状态和删除权限由当前页面与 ViewModel 共同拦截，服务端 RLS/RPC 仍是最终保障。
- 已返回 metadata/`attachmentId` 后，pending 上传、complete 响应丢失、对象上传未知和 metadata/Storage 删除部分失败均保留同一 metadata 的确认、重试或清理路径；若 `create_attachment` 请求本身响应丢失，则因冻结 RPC 无客户端幂等键无法可靠对账，真实中断验收必须单独记录并评估，不能预先断言不会产生重复 metadata。

以上是代码状态记录，不代表真实 Storage、真机或双账号已经通过；JPEG/PNG/WebP、相册/相机、>10 MiB、伪 MIME、第 11 张、上传中断、归档和成员角色验收必须按 E2E 清单执行。

### 退出门槛

- [ ] JPEG、PNG、WebP 上传、读取和删除通过。
- [ ] 超过 10 MiB、类型错误、数量超过十张、跨 Activity 路径和非成员访问均被拒绝。
- [ ] Expense 与 LedgerUnit 两类附件均通过双账号验证。
- [ ] 归档后可读不可写；上传中断后没有无法解释的 UI 成功状态。

## 8. P3：Activity-scoped Realtime Coordinator（代码接线完成，真实验收待完成）

P3 Android 代码接线已完成，但尚未完成真实 Supabase Realtime、网络切换、前后台、双账号和 DELETE/RLS 遗漏恢复验收。因此 P3 exit gate 保持未勾选，项目仍为 `Integration Phase 4 COMPLETE` / `E2E Acceptance NOT READY`。

### 8.1 设计

新增并固定 Supabase Kotlin `realtime-kt`，通过共享 SupabaseClient 使用 OkHttp WebSocket。每个前台 Activity 只由一个 Coordinator 管理订阅，不让 16 张表各自控制 UI 生命周期。

Coordinator 将表事件归并为以下失效域：

| 事件域 | 主要表 | 重新读取内容 |
| --- | --- | --- |
| 活动与身份 | `activities`、`activity_members`、`ledger_units`、`participants`、`participant_claims` | Home、Activity Detail、成员和账本单元 |
| Expense | `expenses`、`expense_debts`、`bilateral_debts` | Expense 列表/详情、债务和完成状态 |
| 资金 | `transfers`、`transfer_allocations`、`transfer_components`、`prepayment_accounts`、`prepayment_usages`、`final_settlement_paths`、`transfer_disputes` | 资金记录、预存余额、结算预览和状态 |
| 附件 | `attachments` | 当前 Expense/LedgerUnit 附件列表 |

事件只携带“需要刷新”的含义。Coordinator 使用短 debounce 合并连续事件，并保证同一失效域同一时刻最多一个刷新任务；刷新期间的新事件触发下一轮读取。

### 8.2 生命周期与权限

- 进入 Activity 后订阅，离开 Activity、退出登录或切换账号时取消订阅并释放 Channel。
- App 回到前台、WebSocket 重连和 Session 刷新后执行一次全量 Activity 刷新，补齐离线期间事件。
- Postgres Changes 继续依赖业务表 RLS；`SUBSCRIBED` 只代表连接建立，验收必须确认当前账号能读取对应行。
- 不依赖 DELETE 事件中的完整旧行做授权或账务计算；删除事件统一触发 Activity 范围重新读取。

### 8.3 P3 实际进展（2026-09-07）

- 已使用共享 `SupabaseClient`、`realtime-kt` 和支持 WebSocket 的 OkHttp/Ktor 配置接入真实 Realtime adapter；每个 Activity 由单一 Coordinator 管理一个 Channel。
- 16 张 publication 表已按 ActivityIdentity、Expense、Financial、Attachment 四域映射；15 张表按 `id`/`activity_id` 过滤，`expenses` 先在 RLS 下读取当前 Activity 的有效 `ledger_unit` ID，再按 `ledger_unit_id` 建立监听范围。
- Coordinator 已具备 250ms 域去抖、single-flight/trailing 刷新、Activity 切换/stop 的迟到事件隔离、动态 scope rebuild、前台/重连四域补读以及统一 Channel 清理。
- activity、expense、financial、attachment 页面已接入 ViewModel revision 刷新；NewExpense 保留草稿保护，Realtime 事件不会覆盖未提交输入。
- 以上是代码接线状态，不代表真实 Supabase Realtime 已通过；网络切换、前后台恢复、双账号四域同步、DELETE/RLS 遗漏恢复和无全表监听必须按 E2E 清单补证。

### 退出门槛

- [ ] A 写入后，B 停留在当前页面可在合理时间内看到服务端最终状态。
- [ ] 短时间连续事件只触发合并刷新，不造成刷新风暴或重复导航。
- [ ] 断网重连、切换账号、退出登录后没有遗留 Channel 或跨账号数据。
- [ ] 所有资金余额和 Final Settlement 仍来自重新读取，未在客户端按事件累加。

## 9. P4：异常、权限与并发矩阵

按 [E2E_ACCEPTANCE_CHECKLIST.md](./E2E_ACCEPTANCE_CHECKLIST.md) 执行以下矩阵：

- 网络：离线、连接超时、上传中断、写入响应丢失、恢复联网。
- Session：access token 刷新、Session 过期、杀进程恢复、退出和账号切换。
- 权限：非成员读取、Member 执行 Creator 操作、跨 Activity ID、成员被移除。
- 生命周期：Activity 归档后所有写入拒绝，取消归档后按权限恢复。
- 重复操作：快速双击、系统返回后重复提交、网络重试。
- 并发：Expense Last Write Wins 的最终版本与审计；资金 RPC 的锁、上限和投影；Final Settlement 旧预览。

每个用例同时记录客户端提示、A/B 最终页面、数据库原始事实和服务端投影。只验证 Snackbar 或页面跳转不算通过。

### P4 实际代码进展（2026-09-07，代码完成，真实矩阵待执行）

- Session/网络错误、UNKNOWN/COMMITTED_REFRESH_FAILED 写入、Activity 权限/移除成员旧缓存、归档写入口和刷新确认路径已完成代码收口。
- 代码已覆盖重复提交保护、已提交但刷新失败的精确记录继续读取，以及明确权限/不存在错误清除旧详情；真实 Session 过期、响应丢失、并发、双账号和归档矩阵仍未验收。
- `compileDebugKotlin`、`compileReleaseKotlin` 通过；`RoutesTest`、`FinalSettlementRequestTest`、`LedgerUnitTest`、`FinancialRecordsTest` 定向测试通过。

## 10. P5：Runtime Demo/Fake 清零

### 扫描范围

- `DemoRouteIds` 不得作为正式路由缺参的默认值；缺参必须进入明确错误状态。
- `DemoData`、`demo*` 构造器和 `FakeFinancialRecordRepository` 只能由 Preview、截图测试或单元测试引用。
- Repository Factory 配置失败时返回明确不可用状态，不返回演示数据。
- 所有可见按钮必须接入真实行为、明确禁用或删除。

### P5 实际代码进展（2026-09-07，运行时清零代码完成）

- `FakeFinancialRecordRepository`、仅测试的 `demo*` 构造器和资金 fixture 已移到 `src/test`；正式运行时 Factory 未配置时仍返回明确 Unavailable。
- 正式组件的 Demo ID、DemoData、Fake 默认值已移除或改为安全空值；Preview 通过私有 `@Preview` 显式传入 fixture，纯单元测试 fixture 保留在测试源集。
- `LargeActivitySmokeTestScreen` 仅保留私有 Preview 用途；所有四个定向测试和 Debug/Release Kotlin 编译均已通过。
- 运行时清零代码已完成，但 Release APK、真实 Supabase、真机和双账号验收仍未完成。

### 退出门槛

- [ ] 全局 Runtime Demo/Fake 搜索结果逐项分类完成。
- [ ] Release 构建不包含可达的演示业务链或假写入。
- [ ] 未配置、路由缺参、网络失败均显示真实错误状态。
- [ ] Preview 和测试数据保留在清晰边界内。

### P6 本地环境预检（2026-09-08）

- Docker Engine 29.7.2 已恢复可达；本地 Supabase DB、Kong、Auth、REST、Storage、Realtime 和 Studio 核心容器已启动并通过健康检查，核心 HTTP 探针可达。
- 当前仓库 17/17 migration 已在本地应用。8 个有 TAP plan 的脚本共 94 项 pgTAP assertion 通过；5 个 plain SQL assert 脚本经本地容器 `psql -v ON_ERROR_STOP=1` 逐个通过，13/13 脚本按各自 runner 通过，plain SQL assert 数不计入 pgTAP 总数。
- `vector` 日志采集辅助容器仍有重启/网络异常，`imgproxy` 和 `pooler` 停止；这些是环境备注，不阻塞当前应用核心链，也不代表完整本地栈全绿。
- 本轮已通过 `gradlew.bat :app:assembleDebug --console=plain` 构建门禁（38 项任务均为 up-to-date）。Debug APK 为 `app/build/outputs/apk/debug/app-debug.apk`，大小 78,074,373 bytes，SHA-256 为 `02A25F20232DAFD196E7AD4A204FEAFD77B081109EACF7D3D32F25CCBE4952BF`；未安装或启动。后续真机安装与运行由用户在 Android Studio 执行。
- 真机尚未接入，USB debugging/RSA、`adb reverse`、APK 安装、双账号和 Realtime 并发验收尚未执行；P6 真机/E2E 退出门槛保持未勾选。操作步骤见 [P6_REAL_DEVICE_RUNBOOK.md](./P6_REAL_DEVICE_RUNBOOK.md)。

## 11. P6：双账号完整 E2E 与发布门禁

使用固定 A/B 账号从可控初始状态执行：

```text
注册/登录/Session 恢复
→ A 创建大型活动与 Participant
→ B 加入并 Claim
→ A 创建子活动
→ 多付款人、多币种 Expense
→ 修改/删除/恢复/关联退款/独立退款
→ 部分 Settlement
→ Prepayment/自动抵扣/返还
→ Final Settlement 预览与执行
→ 图片附件
→ 争议/取消争议/作废
→ 归档只读/取消归档
→ 双端 Realtime 与断网补读
```

### 最终门禁

- [ ] [E2E_ACCEPTANCE_CHECKLIST.md](./E2E_ACCEPTANCE_CHECKLIST.md) 中所有 P0/P1 用例通过，无未解释结果。
- [ ] Android 单元测试、必要的 instrumentation 测试和数据库测试全绿。
- [ ] 本地与目标 Supabase migration inventory 一致；如本轮有 migration，部署前 dry-run 只包含预期项且无 seeds/roles 意外变化。
- [ ] RLS、Storage、Realtime 和安全检查无未处理高风险项。
- [ ] APK、源码、日志、验收材料和 Git diff 无敏感密钥。
- [ ] Runtime Demo/Fake = 0，工作区 clean，最终提交可追溯。
- [ ] 更新 `ANDROID_SUPABASE_INTEGRATION_PLAN.md`，将状态标记为 `E2E Acceptance READY`。

## 12. 建议提交序列

| 顺序 | 建议提交范围 |
| --- | --- |
| 1 | `fix(android): harden financial mutation outcomes` |
| 2 | `feat(android): close activity and financial workflow gaps` |
| 3 | `feat(android): integrate activity attachments` |
| 4 | `feat(android): add activity realtime coordinator` |
| 5 | `test(integration): cover dual-account resilience matrix` |
| 6 | `refactor(android): remove runtime demo and fake paths` |
| 7 | `docs(integration): record e2e acceptance evidence` |

若 P1 的 LedgerUnit 备注或严格 Final Settlement 版本语义需要后端变化，应独立提交 migration、数据库测试和契约文档，不与 Android 大批量改动混在同一提交。

## 13. 当前参考资料

- [Android × Supabase 联调路线](./ANDROID_SUPABASE_INTEGRATION_PLAN.md)
- [后端集成契约](./BACKEND_INTEGRATION_READINESS.md)
- [业务逻辑规格](./BUSINESS_LOGIC.md)
- [Supabase Kotlin 安装说明](https://supabase.com/docs/reference/kotlin/installing)
- [Supabase Kotlin Realtime 订阅](https://supabase.com/docs/reference/kotlin/subscribe)
- [Supabase Postgres Changes](https://supabase.com/docs/guides/realtime/postgres-changes)
