# Kimi Code 前端优化交接

> 快照日期：2026-09-16（Asia/Shanghai）  
> 仓库：`D:\project\Android\shared-ledger`  
> 快照提交：`c6b0657 feat(fx): 服务端ECB汇率同步与外币账单快照，子活动删除恢复`  
> 快照状态：`main == origin/main`，工作树干净  
> 本阶段性质：Android Jetpack Compose 前端视觉、布局、交互与动效优化

## 1. 项目背景

SharedLedger 是一个多人共享记账 Android 应用。用户围绕“活动”组织账本：普通活动直接记录账单，大型活动可以包含多个子活动。活动成员可以绑定参与人身份，记录消费、退款、转账/收款、预存和最终结算，并查看统一资金记录、附件、争议和审计相关信息。

产品强调财务事实真实、状态清晰和多人协作一致性。前端不能用视觉占位替代真实数据，也不能为了美化改变账务方向、金额、身份归属或权限语义。

## 2. 技术与代码结构

- Android：`minSdk 30`、`targetSdk 37`、Java 11。
- UI：Kotlin 2.4、Jetpack Compose、Material 3、Navigation Compose。
- 状态：ViewModel + `StateFlow`，导航入口集中在 `SharedLedgerApp.kt`。
- 数据：Supabase Auth/PostgREST/Storage/Realtime、Ktor、DataStore。
- 主题入口：`app/src/main/java/com/ffocalors/sharedledger/ui/theme/`。
- 公共组件：`app/src/main/java/com/ffocalors/sharedledger/ui/components/`。
- 页面：`app/src/main/java/com/ffocalors/sharedledger/ui/screens/`。
- 视觉参考：`docs/stitch/9598285378004174921/`。

当前已有设计 token：

- 间距：`SharedLedgerSpacing`，范围 4/8/12/16/20/24/32dp。
- 页面尺寸：`SharedLedgerDimens`，包括 24dp 页面水平边距、480dp 内容最大宽度、顶部栏和底部操作栏尺寸。
- 圆角：`SharedLedgerRadius`，包括 8/12/16/18/24dp、32dp 底栏和 Full pill。
- 阴影：`SharedLedgerElevation`，当前只有 0/2/8dp 三档。
- 字体：`SharedLedgerTextStyles`。
- 色彩：鼠尾草绿、暖橙、奶油色、暖白背景和语义状态色。

优先复用和整理这些 token，不要在各页面继续散落新的魔法数字。

## 3. 当前开发进度

### 已完成或已接入

- 注册、登录、Session 恢复、密码相关入口。
- 活动创建、加入、普通/大型活动、子活动、成员与参与人管理。
- 账单新增、编辑、删除、恢复、退款、AA/手动分摊、多付款人。
- 转账、收款、预存、预存返还、统一资金记录和资金详情。
- 普通活动和大型活动最终结算。
- 活动归档/恢复、活动删除、子活动删除/恢复。
- 附件、Realtime 刷新提示、会话级查询缓存。
- 个人信息页真实数据接入。
- ECB 外币汇率、账单汇率快照、离线缓存和定时同步。

### 尚不能宣称完成

- 双账号双 Android 真机完整 E2E 尚未完成。
- Storage、Realtime、断网、前后台恢复、权限和异常矩阵仍需真机验收。
- 当前阶段只能优化 UI，不得把未完成的验收项改写成“已验证”。

详细边界见 `docs/backend/E2E_ACCEPTANCE_CHECKLIST.md`。

## 4. 前端目标

目标不是“换一套皮肤”，而是在不改变业务逻辑的前提下建立稳定的页面节奏、组件一致性、可读层级和必要的交互反馈：

1. 信息密度适中，长列表能快速扫读。
2. 相同语义使用相同组件、圆角、间距、阴影和状态表达。
3. 底部操作栏、键盘、系统导航栏和滚动内容不互相遮挡。
4. 动效解释状态变化和空间关系，不以炫技为目标。
5. 小屏、字体放大、长名称、长金额、加载/空/错误/删除/归档状态都可用。

设计取向：移动生产应用，以细腻、克制为主。动效应让界面“感觉顺滑”，而不是让用户注意到动画本身。

## 5. 已确认问题

### P0：首页活动卡片没有列表间距

文件：`ui/screens/HomeScreen.kt`

`LazyColumn` 当前没有 `verticalArrangement`，`items` 中的 `HomeActivityCard` 只设置了水平 padding，导致连续卡片紧贴。需要建立统一列表节奏：建议卡片间距 12–16dp，并分别处理首项、尾项、空态和 FAB 安全区，不能只在卡片内部继续加 padding。

### P0：固定底部操作区可能遮挡滚动内容

多个页面使用 `Scaffold.bottomBar`、浮动底栏、渐变背景和手工额外 bottom padding。需要统一核对：

- `NormalActivityScreen.kt`
- `LargeActivityScreen.kt`
- `LedgerUnitScreen.kt`
- `NewExpenseScreen.kt`
- `ExpenseDetailScreen.kt`
- `TransferScreen.kt`
- `TransferDetailScreen.kt`
- `FinalSettlementScreen.kt`
- `CreateActivityScreen.kt`
- `CreateSubActivityScreen.kt`
- `JoinActivityScreen.kt`

滚动内容底部必须至少完全越过操作栏、gesture navigation 和 IME，不允许最后一项被遮住，也不要每页使用不同的猜测值。

### P0：组件圆角、阴影和交互状态不一致

用户已反馈 hover/交互阴影与按钮形状不匹配。需要审计 `Card`、`Surface`、`Button`、FAB、底部操作项、选择卡和可点击 Row：

- 阴影轮廓必须与容器 shape 相同，不得出现矩形阴影包着圆角按钮。
- 点击 indication、hover、focus、pressed 的裁剪边界必须与圆角一致。
- 手机触控没有常规 hover；hover 只为鼠标、触控板、手写笔和 ChromeOS 等指针场景提供，不能替代 pressed/focus 反馈。
- 优先使用具有 `onClick` 的 Material `Surface`/`Card`，或保证 modifier 顺序为 shape/clip 与 indication 同源。
- 不要给每张卡片都使用 8dp 浮动阴影；建立静态、可交互、浮动三个层级。

### P1：跨页面布局和信息层级不统一

重点核对：

- 普通活动、子活动和大型活动顶部摘要卡的宽度、内边距、指标布局不一致。
- 子活动账单列表与普通活动账单列表应共享同一账单卡视觉；删除态只增加紧凑状态标识，不改变整张卡的基础风格。
- 资金记录区域曾出现上下留白过大，需要重新检查 section spacing、列表 content padding 和底栏安全区。
- 活动管理页卡片数量多、层级深，页面容易形成“卡片套卡片”和大面积空白。
- 新增消费、多付款人、分摊和发生时间区域在窄屏/键盘弹出时容易拥挤。
- 币种选择菜单应有受控宽高、滚动、当前项标识；不得遮住整个表单或重复显示 `CNY CNY`。
- 金额、状态、人员、日期的对齐基线不统一；长标题、长人员名和大金额需要明确 ellipsis/换行策略。
- UI 不应直接展示完整 ISO 时间串；继续使用统一时间格式化工具。

### P1：加载、空、错误和只读状态视觉缺少统一模式

为以下状态建立可复用表现，不要每个页面临时拼接文本：

- 首次加载、后台刷新和提交中。
- 真实空数据、未绑定身份、无权限、活动归档、活动删除。
- 网络失败、未知写入状态、可重试错误。
- 已删除账单/资金记录、争议、恢复入口。

业务规则：加载时使用 `—` 或骨架，不得用硬编码 `0` 冒充结果；只有真实空结果才显示 `0`。

### P1：动效缺失或不连贯

当前除登录页少量 `AnimatedContent` 外，大多数页面几乎没有系统化动效。需要补充“有目的”的动画，而不是全局套统一动画：

- Tab/分段控件选中指示器：180–220ms，位置连续，不闪烁。
- 展开/收起、错误提示、空态到内容：180–240ms，轻微 alpha + 最多 8dp 位移；退出更弱。
- 按钮 pressed：即时、轻微缩放（约 0.98）或 tonal/elevation 变化，不弹跳。
- 保存、复制、恢复等图标状态切换：140–180ms 的 crossfade/scale，明确反馈成功。
- 列表新增/删除/恢复：保持位置连续，避免整页重排跳动；高频滚动本身不加动画。
- 页面导航：仅在方向和层级需要解释时使用短促过渡，不能让高频返回变慢。

禁止：循环呼吸 CTA、全屏缩放、强弹簧、长时间 blur、滚动绑定动画、为每张列表卡逐个延迟入场。

## 6. 动效与无障碍规则

- 移动端主导：生产级细腻度优先，克制与速度其次。
- 高频操作尽量瞬时；一般反馈控制在 180–250ms。
- 使用可中断的状态驱动动画，快速连续点击不能排队或跳变。
- 优先动画 alpha、translation、scale；避免动画 width、height、padding、margin 等布局属性。
- 弹簧默认无 bounce/overshoot；财务与错误状态不得使用玩具感弹跳。
- 尊重 Android 系统动画缩放/减少动态效果设置；缩放为 0 时界面必须立即到最终状态且仍可完整操作。
- 触控目标至少 48dp；保留 TalkBack `contentDescription`、state description 和焦点顺序。
- 以 1.0x、1.3x 字体比例检查布局，不得依赖固定高度裁掉文字。

## 7. 建议实施顺序

### 阶段 A：建立视觉基线

1. 在改动前运行现有 Preview，记录 360/390/412dp 宽度截图。
2. 盘点 spacing、radius、elevation、container、interaction state 的重复实现。
3. 先补齐 token 和公共组件，避免逐页复制 modifier。

### 阶段 B：首页与核心活动页

1. 修复首页列表间距和卡片扫描层级。
2. 统一普通活动、大型活动、子活动的顶部摘要、section 标题和账单卡。
3. 统一底部操作栏与内容安全区。

### 阶段 C：财务表单与详情页

1. 新增/编辑消费、转账/收款、预存、最终结算。
2. 账单详情、资金记录、资金详情。
3. 检查键盘、下拉菜单、长金额、长名称和错误提示。

### 阶段 D：管理、个人信息与低频流程

1. 活动管理、加入活动、创建活动/子活动。
2. 登录注册、个人信息、密码与隐私弹层。
3. 整理危险操作和确认弹窗的层级。

### 阶段 E：动效与全局回归

布局稳定后再加动效。逐一验证 interrupted interaction、系统动画关闭、低端设备滚动、深色模式（若保留）、横竖屏和 IME。

## 8. 代码边界

允许修改：

- `ui/theme/**`
- `ui/components/**`
- `ui/screens/**`
- 必要的 Compose UI/截图/纯展示测试
- 与页面转场直接相关的 `ui/navigation/**`，但不得改变 route 和业务回调含义

默认禁止修改：

- `data/**`、Repository、DTO、payload 和金额计算
- Supabase migration、Edge Function、RLS、RPC、Storage 和 Realtime 契约
- ViewModel 业务状态机；如 UI 确实缺少展示状态，先报告而不是自行改业务
- Git 历史、远端分支和密钥文件

不要删除看似“多余”的 loading/error/unknown/archived/deleted 分支。不要把 Preview 的 `DemoData` 接入运行时。

## 9. 验收矩阵

至少覆盖：

| 维度 | 验收点 |
| --- | --- |
| 屏幕 | 360×800、390×844、412×915；顶部/底部系统栏正常 |
| 字体 | 默认和 1.3x；标题、金额、人员名不被裁切 |
| 输入 | IME 打开后当前字段、保存按钮和错误提示可见 |
| 列表 | 0/1/多项、长列表、删除态、归档态，间距稳定 |
| 状态 | loading/refresh/empty/error/read-only/submitting/unknown write |
| 交互 | touch、keyboard focus、mouse/stylus hover（适用时）、快速重复点击 |
| 动效 | 系统动画 1x 和 0x；无循环装饰动画，无明显掉帧 |
| 主题 | 当前浅色主题必须通过；若保留深色主题则不能使用浅色语义 token |
| 业务 | 金额、币种、付款人、参与人、删除/恢复和权限信息保持不变 |

## 10. 验证与交付要求

每个阶段完成后：

1. 运行 `git diff --check`。
2. 运行 `.\gradlew.bat compileDebugKotlin` 和受影响的定向单元/UI 测试。
3. 不默认构建或安装 APK；真机由项目负责人通过 Android Studio 验证，除非明确要求协助。
4. 提供改动前后截图或 Compose Preview 对比，列出验证尺寸和状态。
5. 单独报告仍需业务层配合的问题，不要用 UI 假数据绕过。
6. 未经明确要求，不执行 Git commit/push，不修改 Supabase。

## 11. 完成定义

前端优化完成需要同时满足：

- 首页卡片、页面 section 和列表节奏统一。
- 同类组件跨页面视觉一致，不再出现按钮形状与交互阴影不匹配。
- 底部栏、系统栏、键盘和滚动内容没有遮挡。
- 状态层级、金额层级和长文本策略明确。
- 必要动效短促、可中断、尊重系统减少动态效果。
- 真实业务数据和所有回调语义保持不变。
- 编译、定向测试、Preview/截图检查通过；真机未验证项被明确标注。
