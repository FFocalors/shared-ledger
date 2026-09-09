# SharedLedger 双账号 E2E 验收清单

> 状态：`P4/P5 代码收口完成 / 真实 E2E 待执行`
>
> 目标：为 `E2E Acceptance READY` 提供可重复、可审查的验收证据。

当前 P4 异常/权限/未知写入硬化和 P5 Runtime Demo/Fake 运行时清零代码已完成；本清单仍未执行真机、真实 Supabase、Storage、Realtime 或双账号异常矩阵。Debug/Release Kotlin 编译及 `RoutesTest`、`FinalSettlementRequestTest`、`LedgerUnitTest`、`FinancialRecordsTest` 定向测试已通过，不构成 E2E 通过证据。下一阶段为 P6 双账号完整 E2E，需补做 P2 Storage、P3 Realtime、P4 异常/并发/Session/归档验证。

2026-09-08 本地环境门禁已验证：Docker Engine 29.7.2、本地 Supabase 核心服务和 17/17 migration 可用；8 个 pgTAP 脚本共 94 项 assertion 通过，5 个 plain SQL assert 脚本经本地 `psql -v ON_ERROR_STOP=1` 通过，13/13 脚本按各自 runner 通过。`vector` 日志辅助容器仍有重启异常，`imgproxy`/`pooler` 停止，但不阻塞当前应用核心链；真机尚未接入，所有真机和 E2E checkbox 继续保持未勾选。真机步骤见 [P6_REAL_DEVICE_RUNBOOK.md](./P6_REAL_DEVICE_RUNBOOK.md)。

2026-09-08 本地双账号 API/RLS 前置 smoke 已实际通过：脚本 `scripts/run-local-dual-account-api-smoke.ps1` 输出 18/18 PASS，验证 A/B 独立普通 Session、Activity/Participant 加入与 Claim、双方事实读取、跨 Activity 不可见及 Member 的 Creator-only 设置拒绝。该结果只证明本地 HTTP API/RLS 主链，不计入真机或完整 E2E 通过；测试账号和业务记录保留在本地，reset 后清理。真机、Storage、Realtime 及异常并发矩阵仍待执行，相关 checkbox 保持未勾选。

2026-09-08 本地双账号 Realtime smoke 已通过：脚本 `scripts/run-local-dual-account-realtime-smoke.ps1` 输出 11/11 PASS，验证 A/B 独立 Session、A 订阅 `participant_claims INSERT` 并收到 B Claim 事件、B 订阅 `activities UPDATE` 并收到 A 设置修改事件；事件均按订阅 ID、schema/table/event、过滤条件和 UUID/名称事实校验。该结果只证明本地 Realtime 前置链，不计入真机或完整 P3/E2E 通过；Android Coordinator、前后台、断网、DELETE/RLS 补读和真机双端仍待执行，相关 checkbox 保持未勾选。本轮及前序运行产生的本地测试账号及业务记录保留，reset 后清理。

2026-09-08 本地双账号 Storage smoke 已通过：脚本 `scripts/run-local-dual-account-storage-smoke.ps1` 输出 17/17 PASS，验证 A 创建 pending metadata、上传并 complete 最小 PNG，A/B 均能读取 metadata 和匹配对象字节；C 的 metadata 返回空集且对象下载返回 4xx。该结果只证明本地 Storage REST/RLS 前置链，不计入真机或完整 P2/E2E 通过；上传中断、JPEG/WebP、大小/MIME 边界、设备相册/相机和其余附件矩阵仍待执行，相关 checkbox 保持未勾选。生成的本地账号、附件 metadata 和对象保留，reset 后清理。

2026-09-08 已准备单真机 Realtime companion：`scripts/run-local-device-realtime-companion.ps1` 可由桌面普通用户 B 通过加入码加入真机 A 的 Activity、Claim 未绑定 Participant，并订阅同一 Activity 的 `activities UPDATE` 后重读最终名称；目前仅完成脚本静态验证和帮助解析，未接入真机，不能计入 P3/E2E 通过。该工具只能补充一个 Android 客户端与一个桌面并发客户端的观察，真机 A 页面、Android Coordinator、前后台、断网、DELETE/RLS 补读及双 Android UI 仍待执行，相关 checkbox 保持未勾选。

## 1. 验收信息

执行时填写以下信息，不记录密码、access token、refresh token、publishable key 或其他密钥。

| 项目 | 记录 |
| --- | --- |
| 日期与时区 | `YYYY-MM-DD / Asia/Shanghai` |
| Git commit |  |
| APK/build variant |  |
| Supabase 环境 | 本地 / hosted |
| migration 数量与最后版本 |  |
| 设备 A / Android 版本 |  |
| 设备 B / Android 版本 |  |
| 账号 A | Creator 测试账号标识，不写密码 |
| 账号 B | Member 测试账号标识，不写密码 |
| 执行人 |  |

## 2. 结果规则

- `PASS`：客户端行为、另一账号结果、数据库事实和投影全部符合预期。
- `FAIL`：结果明确错误，必须关联缺陷编号或修复提交。
- `BLOCKED`：环境或外部依赖阻塞，必须写清阻塞原因；不能计入通过。
- `N/A`：只允许用于明确延期且不属于 V0.1 完成标准的能力，并写明依据。

资金类用例出现超时或响应丢失时，先查询资金记录和服务端投影，再决定是否重试。未经确认不得重复提交。

## 3. P0 必过主链

### A. Auth 与 Session

- [ ] A 注册或登录成功，进入 Home。
- [ ] B 注册或登录成功，进入 Home。
- [ ] A/B 杀进程后恢复有效 Session。
- [ ] Session 失效后刷新成功，或明确回到 Auth；不会保留其他账号数据。
- [ ] 退出后返回 Auth；重新登录不会复用上一账号的 Activity/ViewModel 状态。
- [ ] 忘记密码邮件、`sharedledger://auth/reset` 回跳和新密码登录通过。
- [ ] 密码重置 deep link 冷启动和热启动均通过，重置后 Session/账号状态没有串号。

证据：A/B 页面、Session 最终状态、日志中的脱敏错误。

### B. Activity、Participant 与 Member

- [ ] A 创建大型 Activity，设置基准币及多币种开关。
- [ ] A 创建至少三名 Participant。
- [ ] B 使用加入码加入并 Claim 指定 Participant。
- [ ] A/B 刷新后看到一致的成员、Participant 和 Claim。
- [ ] A 创建两个子活动，A/B 均能看到。
- [ ] 创建首个锁定事实后，页面显示名单已锁定；不能新增/删除 Participant，但仍可 Claim 已有 Participant。
- [ ] B 解除并重新 Claim 可用 Participant，历史账务身份不被改写。
- [ ] A 移除 B 后，B 失去 Activity 读取与 Realtime 更新权限。
- [ ] A 将 Creator 转移给 B，双方权限及时更新。
- [ ] 新 Creator 删除未被历史事实引用且允许删除的 Participant。
- [ ] 活动资料编辑、复制加入码、删除 Participant、取消归档等入口执行真实操作。

证据：`activities`、`activity_members`、`participants`、`participant_claims`、`ledger_units` 最终行及双方页面。

### C. Expense 完整链

- [ ] 创建 AA Expense，Payment 与 Split 合计守恒。
- [ ] 创建多付款人 Expense。
- [ ] 创建手动分摊 Expense，覆盖四舍五入尾差。
- [ ] 创建外币 Expense，保存原币金额、汇率快照和正确 `base_amount`。
- [ ] B 在另一设备看到新 Expense 和更新后的债务投影。
- [ ] 修改 Expense 后版本、审计和债务投影正确。
- [ ] 删除 Expense 后原事实保留、投影回退。
- [ ] 恢复 Expense 后投影恢复。
- [ ] 创建关联退款，保留 `original_expense_id`，金额和预存恢复正确。
- [ ] 创建独立退款，不伪造原账单关联。
- [ ] Expense 发生时间通过日期+时间选择器输入，页面按 UTC+8 显示，服务端保存合法 `Instant`；编辑/退款保留已有时间。

证据：`expenses`、付款/分摊事实、`expense_debts`、`bilateral_debts`、`prepayment_usages` 和 A/B 页面。

### D. Settlement、Prepayment 与资金记录

- [ ] A 欠 B 时记录部分还款，剩余债务准确。
- [ ] 通过“收款”入口记录同一业务方向，双方和记录人正确。
- [ ] Creator 为未注册 Participant 分别执行 Transfer、Prepayment、Prepayment Return 和 Final Settlement 代记，`recorded_by` 与 `on_behalf_of_participant_id` 正确。
- [ ] 新增预存时先抵扣同方向旧债，剩余进入预存余额。
- [ ] 新 Expense 自动使用可用预存，债务与预存余额正确。
- [ ] 预存不足时只使用可用余额，其余形成普通债务。
- [ ] 预存返还不超过当前余额，成功后余额正确。
- [ ] 统一资金记录显示 settlement、prepayment、prepayment_return、final_settlement 和自动抵扣。
- [ ] 资金记录列表支持按时间正序/倒序排序，刷新后顺序与服务端时间字段一致。
- [ ] 作废 settlement/prepayment 后保留原事实，并重建正确投影。
- [ ] 恢复已作废资金记录时按当前债务、预存余额和最终结算方案重新校验；恢复成功后双方资金列表、债务和预存状态一致，已有效记录按幂等成功处理。
- [ ] 交易相关方添加争议；无关方被拒绝；取消争议后历史可审计。

证据：`transfers`、`transfer_components`、`transfer_allocations`、`prepayment_accounts`、`prepayment_usages`、`transfer_disputes` 和 A/B 页面。

### E. Final Settlement

- [ ] 大型 Activity 的多个子活动共同进入预览。
- [ ] 推荐方向、普通金额、预存返还金额和总额与服务端投影一致。
- [ ] 执行一个建议项后，资金事实落账并重新生成剩余方案。
- [ ] 预览后制造账务变化；旧建议按已经确认的版本语义正确接受或拒绝。
- [ ] final settlement 路径和资金详情显示一致。
- [ ] Activity 达到完成条件时，双方显示真实完成状态。

证据：预览返回、`financial_version`、`final_settlement_paths`、资金事实和执行前后双方页面。

### F. Storage 附件

- [ ] Expense 从相册添加 JPEG/PNG/WebP 并在双方设备查看。
- [ ] Expense 直接拍照、压缩、上传和查看通过。
- [ ] LedgerUnit 独立附件上传和查看通过。
- [ ] 上传者或 Creator 删除附件后，双方列表同步。
- [ ] 非成员和跨 Activity 路径读取被拒绝。
- [ ] 超过 10 MiB、错误 MIME、超过十张被拒绝且提示明确。
- [ ] 上传中断、complete 失败和删除失败均能恢复，无假成功状态。
- [ ] 归档后附件可读不可新增/删除。

Storage 手工验收步骤（每项都需要记录 A/B 页面、附件 metadata、私有 bucket 对象和失败提示）：

1. [ ] 使用 A 在同一 Activity 分别从相册选择 JPEG、PNG、WebP，验证 Expense 新增/编辑附件和 B 端查看；再在 LedgerUnit 独立附件入口重复验证。
2. [ ] 使用相机入口拍摄图片，验证 FileProvider 临时 URI、压缩、上传、B 端查看和取消拍照后的临时文件清理；同时验证相册取消不产生 pending metadata。
3. [ ] 依次提交超过 10 MiB 的图片、文件头与 MIME 声明不一致的伪 MIME 文件、GIF 等不支持类型，以及第 11 张图片；每项都被客户端/服务端拒绝，不留下可见假成功或孤儿 metadata。
4. [ ] 在 metadata 已创建、对象上传中断、`complete_attachment` 响应丢失和对象/metadata 删除部分失败的情况下恢复网络并重试；确认不会重复创建 metadata，最终状态可明确为完成、pending 或失败。
5. [ ] 归档 Activity 后分别尝试 Expense/LedgerUnit 新增、删除和重试附件；确认已有附件仍可读，所有写入入口隐藏/禁用且服务端拒绝。
6. [ ] 使用非成员和另一 Activity 的 URI/ID 尝试读取、上传和删除；确认读取与写入均被拒绝且错误不会泄露资源存在性。
7. [ ] 分别由上传者、Creator 和其他 Member 执行删除：验证允许角色可删除，其他 Member 按契约拒绝；A/B 列表和对象/metadata 最终状态一致。

证据：`attachments` metadata、私有 bucket 对象状态、双方页面和失败日志。

### G. Realtime 双端同步

- [ ] Activity/成员/Claim 变化使另一端重新读取对应页面。
- [ ] Expense 创建、修改、删除、恢复使另一端更新列表、详情和投影。
- [ ] Transfer、Prepayment、争议和 Final Settlement 使另一端更新资金与结算状态。
- [ ] 附件变化使另一端更新附件列表。
- [ ] 短时间连续写入经过 debounce，不形成刷新风暴。
- [ ] B 断网期间 A 写入；B 恢复网络或回前台后补读最终状态。
- [ ] 退出 Activity、退出登录和切换账号后没有旧 Activity 的更新泄漏。

P3 手工证据项（当前均待真实环境验收）：

- [ ] 单一 Activity 只建立一个 Realtime Channel；离开 Activity、切换 Activity、stop 和退出登录后 Channel 已清理。
- [ ] A/B 双账号分别验证 ActivityIdentity、Expense、Financial、Attachment 四个失效域的同步和最终重读结果。
- [ ] 新增有效 `ledger_unit` 后，Expense 的 `ledger_unit_id` scope 会重建；新旧 scope 不产生并行 Channel 或跨 Activity 监听。
- [ ] 主动触发 scope rebuild 后只完成一次有界重建，不出现自动循环、重复订阅或重复刷新。
- [ ] 断网、恢复联网、WebSocket 重连和回到前台后，四域均执行补读并恢复到服务端最终状态。
- [ ] Activity 归档和移除成员后，页面停止不应有的写入/读取与 Realtime 更新；RLS 拒绝结果和页面状态一致。
- [ ] 制造 DELETE 事件可能缺少 scope 列的场景，确认事件遗漏时由前台/重连补读恢复，而不是依赖 DELETE payload 计算账务。
- [ ] 通过 Realtime 诊断或服务端订阅证据确认没有无过滤全表监听，所有表均按 Activity 或有效 ledger unit scope 过滤。

证据：事件/刷新诊断日志、A/B 页面以及最终服务端状态。事件日志只证明收到提示，重新读取后的结果才是通过依据。

## 4. P1 异常与权限矩阵

### H. 网络与结果未知

- [ ] 读取离线显示可恢复错误，恢复网络后可以刷新。
- [ ] 写入前离线不会生成服务端事实。
- [ ] 写入已提交但响应丢失时，客户端提示“正在确认/结果未知”，重新读取后只存在一条事实。
- [ ] RPC 成功但详情刷新失败时显示“已保存，刷新失败”，不会引导重复提交。
- [ ] 图片上传中断不会出现 completed metadata 指向缺失对象。

### I. 重复提交与并发

- [ ] 快速双击创建 Expense 只产生预期的一次写入，或第二次被明确拒绝。
- [ ] 快速双击 Transfer/Prepayment/Final Settlement 不产生重复资金事实。
- [ ] A/B 同时修改 Expense，最终符合 Last Write Wins，`version`、`updated_by` 和审计记录一致。
- [ ] A/B 同时偿还同一债务，不会超额冲抵。
- [ ] A/B 同时使用/返还同一预存，不会形成负余额。
- [ ] Final Settlement 执行与 Expense/Transfer 并发时，结果符合当前方案校验。

### J. RLS、角色与跨活动攻击面

- [ ] 非成员无法读取 Activity 及其所有事实/投影/附件。
- [ ] Member 不能更新设置、移除成员、转移 Creator、归档或删除 Activity。
- [ ] 普通成员不能代表其他 Participant 代记。
- [ ] 使用另一个 Activity 的 Participant、LedgerUnit、Expense、Transfer 或附件路径被拒绝。
- [ ] 未绑定 Participant 的 Member 可以浏览，但不能执行资金操作。
- [ ] 被移除成员的已打开页面在下次事件、恢复前台或手动刷新后退出内容态。

### K. Archive 只读

- [ ] 有未结债务/预存时归档显示准确警告。
- [ ] 归档后创建/修改/删除/恢复 Expense 均被拒绝。
- [ ] 归档后 Settlement、Prepayment、Return、作废、争议和 Final Settlement 写入均被拒绝。
- [ ] 归档后附件只读。
- [ ] Creator 取消归档后，根据当前角色恢复允许的写入口。

## 5. P2 发布收口

- [ ] Runtime 导航与 Repository 不引用 Demo ID、DemoData 或 Fake 写入。
- [ ] 所有正式页面按钮都执行真实行为、明确禁用或已移除。
- [ ] 未配置 Supabase、路由缺参和远端失败不会回退到演示数据。
- [ ] Android 单元测试全绿。
- [ ] 必要的 instrumentation 测试全绿。
- [ ] 数据库测试按各自 runner 通过：8 个 pgTAP 脚本共 94 项 assertion，5 个 plain SQL assert 脚本经本地 `psql -v ON_ERROR_STOP=1` 通过，共 13/13；本发布门禁仍需结合其余真实验收后勾选。
- [ ] 本地与目标 migration inventory 一致。
- [ ] Supabase advisors/安全检查无未处理高风险项。
- [ ] Release APK、源码、日志与 Git diff 无敏感密钥。
- [ ] `git diff --check` 通过，工作区状态和验收 commit 已记录。

## 6. 缺陷与复验记录

| ID | 用例 | 结果 | 问题/证据 | 修复提交 | 复验结果 |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |

## 7. 最终签署

只有以下条件全部成立，才将项目状态更新为 `E2E Acceptance READY`：

- P0 主链全部 PASS。
- P1 中所有适用用例 PASS，没有 BLOCKED 或未解释结果。
- P2 发布收口全部完成。
- 数据库事实、投影和 A/B 最终页面一致。
- 所有失败修复均在目标 commit 上完成复验。

| 角色 | 结论 | 日期 | 备注 |
| --- | --- | --- | --- |
| 开发 |  |  |  |
| 验收 |  |  |  |
