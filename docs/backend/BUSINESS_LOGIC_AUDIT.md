# 业务逻辑最终收口审计（待人工确认）

> 审计日期：2026-09-22～2026-09-23。代码基点：`660201c5f8eb76a8b935b84413cf85d9de4c1d53`。  
> **结论：BUSINESS_LOGIC.md 尚不能作为无歧义、已验证的唯一业务基线。**  
> 本报告记录当前实现，不批准新业务设计。`BUSINESS_LOGIC.md` 未修改，业务代码、migrations、既有测试未修改。最终基线更新和 `BUSINESS_LOGIC_FINAL_REVIEW.md` 必须等待人工确认。

阅读顺序：第3节逐章差异 → 第4～5节当前真实行为 → 第6节冲突证据 → 第9节验证结果 → 第10节人工决策。附录用于追溯，不表示全部接口都应继续对新客户端开放。

## 1. 审计范围、证据和限制

证据优先级：当前 SQL/Kotlin 实现 → 当前约束、触发器、权限 → 测试及实际执行 → 其他文档 → 待审计基线。注释、提交标题、测试名称不能替代函数实际行为。

- 扫描 `supabase/migrations` 全部 **39** 个文件，追踪同名函数覆盖、重载、撤权和历史回填；完整文件清单见附录 A。
- 检查 `supabase/tests/database` 全部 **22** 个脚本的范围；实际执行 17 个非并发脚本，另做指定还款的双会话并发验证。5 个旧并发脚本未直接运行，原因见第 9 节。
- 检查 Android Activity、Expense、Transfer、Financial、ExchangeRate、Attachment 的 Repository、payload、DTO、关键 ViewModel、请求缓存及相关测试；检查 Edge Function、Storage/Realtime 接线、后端契约和验收文档。
- 检查最近业务提交：`660201c`（指定还款/最终结算）、`0613686`（多币种预存/历史不可变）、`a52166c`（多币种普通结算/移除恢复）、`c6b0657`（ECB/子活动恢复）、`5f31c91`（公平 AA）。
- 本地开发库 migration history 到 `20260921051720`，**缺少仓库最后两条 20260922 migration**。未更新开发库；将其 schema 克隆到独立临时数据库，补入这两条仓库 SQL 后进行验证。未读取或修改远程生产库，不能据此宣称线上已部署。
- 临时库未复制业务数据、Vault secrets、Storage 文件或 Cron job；排除只允许在 `postgres` 数据库安装的 `pg_cron`。补齐权限并为测试安装 pgTAP。该验证不是“从零重放全部 migrations”的部署验证，也不是 Edge 网关/真机 E2E 验收。
- 临时数据库清理已完成：首次收尾时 Docker 不可连接；用户启动 Docker 后，已删除本次专用的 `shared_ledger_audit_20260922`，并查询确认该库不存在。开发库 `postgres` 未删除、重置或应用 migration；清理前后 migration history 均为37条，最新 `20260921051720`。此前测试结果保持有效。
- 审计开始工作区干净；后续出现 5 个并行 UI 改动（StateViews、SharedLedgerApp、HomeScreen、NewExpenseScreen、NormalActivityScreen）。本任务未修改、撤销或纳入自己的代码变更。SQL 与 Repository 证据仍以以上基点为准。

状态含义：`CURRENT` 一致；`OUTDATED` 已被当前实现取代；`MISSING` 已实现但未记载；`CONFLICT` 有明确行为冲突；`INCOMPLETE` 闭环未完成；`UNCLEAR` 资料不足以确认最终设计。**测试通过只证明覆盖场景通过；错误行为不会因“代码优先”而自动成为应接受的业务规则。**

## 2. 当前业务逻辑总览

| 模块 | 当前已存在的实现 | 收口判断 |
|---|---|---|
| 身份/活动/成员 | Auth profile、normal/large、8 位数字加入码、Creator/Member、认领/取消认领、移除成员、转移创建者 | 已实现；成员权限须按操作区分 |
| LedgerUnit | normal 的 default；large 的 root/sub_activity；成员创建、删除/恢复子活动 | 已实现；没有子活动参与人名单实体 |
| Expense/Payment/Split | 单事务保存，AA/manual，负消费，原币和基准币合计校验 | 已实现；零净债务账单、自动汇率编辑存在错误 |
| Debt | 原币净额确定债务双方；基准币附着同一债务拓扑；同币种双边抵消 | 已实现；结算后退款与反向抵消有缺陷 |
| 普通/指定还款 | 候选、预览、FIFO/TARGETED 提交、账单进度、部分/多次还款 | 主路径已实现；集成收口 **IMPLEMENTATION INCOMPLETE** |
| Transfer 历史 | 四类 Transfer、component、作废、source history、永久账单 allocation facts | 已实现；旧入口与新入口保证不同 |
| Prepayment | Activity/owner/custodian/currency 账户；自动使用、退款释放、原币返还 | 已实现；净债务优先、重试和撤销资金来源有缺陷 |
| Final Settlement | normal/large 的 v2 双模式方案与逐项执行、跨人跨子活动路径 | 已实现；作废后重执行及极小金额存在边界问题 |
| Multi Currency | Expense ECB 快照、4 位原币/1 位基准币、按币种债务与预存 | 已实现；不可宣称所有资金事实都有独立 FX 快照 |
| Archive/状态 | Creator 归档/取消归档、只读保护、活动/参与人状态视图 | 已实现；非零原币余债可能被错误标 completed |
| Dispute/Audit | 双方/录入者争议、解决、审计行；不改财务金额 | 已实现 |
| 附件/协作 | 私有图片 bucket、metadata 生命周期、Realtime 重读、请求持久化 | 已实现代码；本轮未作设备与 Storage E2E |

### 2.1 实体、约束和权限的真实边界

当前 public 业务实体为 25 张表、2 个普通视图，没有业务 materialized view。债务、账户和 usage 是**存储在表中的重建投影**，不能把它们误称为数据库物化视图。

| 实体组 | 关键约束/保护 |
|---|---|
| activities / activity_members | UUID；唯一 8 位数字 join_code；成员 `(activity_id,user_id)` 唯一；财务版本非负；Creator 来自 `activities.created_by`，没有独立角色 enum |
| ledger_units / participants / participant_claims | 单元和参与人的 Activity 复合 FK；参与人顺序在 Activity 内唯一；participant 唯一认领；每用户每 Activity 最多一认领；成员移除不删除认领及账务 |
| expenses / payments / splits | original_amount 非零、fx_rate 正、base_amount 与折算公式一致；每账单每人各一条 payment/split；金额守恒与同符号主要由 RPC 实施，不是跨表 CHECK；软删除生命周期 CHECK |
| expense_debts / bilateral_debts | 债权人与债务人不同；Expense/Unit/Activity 复合 FK；每 Expense/双方唯一；bilateral 唯一键包含无序双方及 currency；允许非零原币配零基准币的 bilateral 行 |
| transfers / transfer_components | 四种 Transfer enum；双方同活动且不同；代记人必须为一方；作废元数据完整；component 类型为 settlement/prepayment/prepayment_return；同 Transfer 同 component_type 唯一；合计由 RPC 校验 |
| transfer_allocations | 可重建；Transfer/Component/Debt 的 Activity 复合 FK；同 Transfer/Debt 唯一；原币正数、基准币可为零；并非永久的历史金额来源 |
| transfer_source_expenses | 仅记录真实 settlement 触及；`(transfer_id,expense_id,component_type)` 唯一；UPDATE/DELETE trigger 拒绝；不因作废清除；普通成员无 SELECT 权限 |
| transfer_expense_allocations | 永久金额事实；FIFO/TARGETED/FINAL_SETTLEMENT；普通 allocation 按 Transfer/Expense/双方/mode 唯一，最终路径按 source_path_id 唯一；UPDATE/DELETE trigger 拒绝；原币/payment 正、base 可零 |
| final_settlement_paths | 保存执行路径与来源；source_expense_debt_id 是历史标识，不应假设可级联重建；mode/path_currency/original/base/fx；base 正数约束与极小原币路径有张力 |
| prepayment_accounts / prepayment_usages | 账户唯一维度含 currency；余额非负；usage 账户/债务唯一；保存预存币、债务币、两种原币用量、base、bill FX/时间；usage 的 base 必须正 |
| transfer_disputes / audit_logs | 每 Transfer/Participant 一条争议，可重新打开；audit 不参与余额；API 不直接编辑审计 |
| attachments | image only；JPEG/PNG/WebP；大小 1～10 MiB；pending/ready/deleted；每 Expense 或独立 Unit 最多 10 个 pending+ready（RPC 计数加活动锁） |
| exchange_rate_* | 缓存币种对主键；支持币列表；单例同步状态；写入受 service_role 限制 |

四个业务 enum 为 activity_type、ledger_unit_type、expense_split_method、transfer_type；settlement_mode 和 final mode 是带 CHECK 的 text，不能混为一个枚举。`FIFO/TARGETED/FINAL_SETTLEMENT` 是分配意图，`base_unified/original_currency` 是最终结算币种模式。

RLS 已覆盖上述业务表；活动账务一般由成员谓词读取，逻辑删除 Activity 对成员谓词不可见；profiles 和汇率参考数据有全 authenticated 读取策略。财务事实/投影不开放 authenticated 直接 DML；两个财务状态视图均 `security_invoker=true`。public wrapper 多为 invoker，private 实现以 definer 执行并检查身份；private 不作为 PostgREST 暴露 schema。权限检查必须同时看 grant、RLS 和函数内部，不能只看函数存在。

普通索引覆盖 Activity、双方、FK、账单时序与历史源查找；影响业务语义的唯一索引包括币种双边净债务、币种预存账户、`transfers(activity_id,request_id) WHERE request_id IS NOT NULL` 和永久分配标识。`20260920151825` 删除冗余 source 唯一索引，没有删除 constraint-backed 唯一保护；`20260920152349` 修复 PostgreSQL 截断后的旧三维账户唯一约束。

## 3. BUSINESS_LOGIC.md 逐章节差异

下表审计的是原文各章的重要规则，不将一章中的部分正确误记为整章正确。细节冲突编号对应第 6 节。

| 业务领域 | BUSINESS_LOGIC.md | 当前实现 | 状态 | 说明 |
|---|---|---|---|---|
| §1 文档定位 | 已确认的唯一开发依据 | 尚未覆盖新还款契约，且存在实现缺陷 | OUTDATED | 本轮后仍需人工确认，不能先宣布冻结 |
| §2 产品能力 | 描述完整功能集合 | 多数有实现；若干关键路径不能成功/不守账 | INCOMPLETE | 不能把功能入口存在等同业务闭环 |
| §2 资金 FX | 每笔资金事实保存完整币种/FX/base | Transfer 无统一 FX/base 字段；预存账户无存入时 FX | CONFLICT | C07 |
| §3 术语 | allocation 仅为重建结果 | 新增永久 transfer_expense_allocations、financial_locked、两类 mode | MISSING | 区分历史金额事实与实时投影 |
| §4 普通/大型结构 | normal root；large root+sub | 数据 enum 为 default/root/sub_activity | CURRENT | 业务概念与数据库名须区分 |
| §4 子活动名单 | 每子活动勾选名单，Expense 只能从该名单选 | 无子活动名单表/字段/RPC；children 校验 Activity participant | CONFLICT | U01，不能写成已强制执行 |
| §4 根单元用途 | large 普通消费只能进子活动 | Expense RPC 未按 root/sub 限制正负号或类型 | UNCLEAR | U01；页面引导不能冒充服务端约束 |
| §5 加入/认领 | 加入可新建或认领 | join 只加 membership；create_participant/claim 独立调用 | CURRENT | 应补事务边界和并发唯一约束 |
| §5 名单锁定 | normal 首 Expense；large 首子活动 | 任意 Expense 插入或 sub_activity 插入均置锁；删空也不清锁 | OUTDATED | large root 先记账也会锁名单 |
| §5 成员删除账单 | Member 可删除 Expense（未区分录入者） | 仅 Expense 创建者或 Activity Creator；还受真实历史/退款保护 | OUTDATED | 权限收紧已在 trigger 实施 |
| §5 新增预存 | 未记最新权限放开 | v2 任意 Activity 成员可为两个参与人记预存；禁止 behalf 参数 | MISSING | `20260921022101` |
| §5 最终结算 | 容易套用普通转账身份规则 | 任意 Activity 成员可执行当前 plan，不要求认领一方 | MISSING | `20260922072033`；普通还款和单独预存返还未放开 |
| §6.1 base 锁定 | 首笔资金记录后锁 | update_settings 按 financial_version>0 锁 base | CURRENT | 无“恢复为空即可换基准币” |
| §6.2/6.3 FX 快照 | 自动汇率；同币种编辑保留；退款继承 | 新增未关联账单有自动入口；编辑/关联退款遇 STABLE 行锁错误；旧手工入口仍开放 | CONFLICT | C01、C06 |
| §6.4 精度 | Transfer/Prepayment/Usage 均 1 位 | 原币金额通常 4 位，base 1 位，FX 10 位；不可笼统“都 1 位” | OUTDATED | C07；每列职责不同 |
| §6.5/§7.3 AA | 全部尾差给最后一人 | base 以 0.1 单位向稳定排序前若干人各分一单位，负数同理 | OUTDATED | `20260910133739`；100/3 的 base 为 33.4、33.3、33.3 |
| §7.1/7.2 Payment/Split | 付款与承担分离，单事务双合计守恒 | RPC 实施原币合计、符号、重复人、成员范围，再分配 base 尾差 | CURRENT | 补充失败条件；手工分摊不由服务端自动改总额 |
| §7.5 Expense 人员范围 | LedgerUnit 的部分人 | 实際是 Activity 活跃参与人的子集 | OUTDATED | U01 |
| §8.1 债务生成 | Payment.base−Split.base 决定撮合 | 先按原币净额生成双方，base 绑定同一拓扑并处理尾差 | OUTDATED | `20260920120259`，避免虚构原币债务双方 |
| §8.1 零净额 | 无债务无需结算 | 全体净额为零的有效账单被 RPC 拒绝 | CONFLICT | C05 |
| §8.2 稳定匹配 | participant_order/id | 仍按稳定参与人顺序匹配原币区间 | CURRENT | base 配额不可表示某条原币债务时会拒绝保存 |
| §8.3 双边抵消 | 同一双方反向债务互抵 | 还必须同原币；汇率不同时 base 残值按各债务快照 | OUTDATED | 跨币种不做日常自动净抵 |
| §8.4/§20 投影 | ExpenseDebt 总能重建替换 | financial_locked 账单的 debt 行在全量重建中保留 | OUTDATED | 历史路径和永久 allocation 依赖稳定来源 |
| §9.1～9.3 转账/收款 | 认领参与人为一方 | 当前普通还款仍如此；Creator 可代未认领一方 | CURRENT | 与最终结算、新增预存的成员门槛不同 |
| §9.4 币种门槛 | 外币必须开启多币种 | 普通还款可清偿已有同币外债，不受当前开关/支持列表限制 | OUTDATED | Android 注释与 RPC 一致；预存/最终执行另有校验 |
| §9.5 FIFO | 所有普通 Transfer 自动 FIFO | 新接口可 TARGETED 多选 Expense；选中集合内部再排序 | MISSING | 指定还款完整契约见第 4 节 |
| §9.6/§16.2 Transfer | 不可编辑，作废不可恢复/再作废 | lifecycle trigger 与 RPC/撤权一致 | CURRENT | component/path 对普通客户端依靠无 DML 权限，勿夸大为所有表都有不可变 trigger |
| §10 类型/component | 四类 Transfer，混合用途 | 保持；增加 settlement_mode 与目标快照 | CURRENT | 补 mode，不新增第五类 repayment Transfer |
| §11 预存方向 | owner→custodian 存入；反向返还 | 保持；账户增加 currency；普通活动也有后端预存能力 | CURRENT | 不能仅描述为大型活动可用 |
| §11 净债务优先 | 双边抵消后再用预存 | 当前 usage 重建未扣反向 offset，也未扣 final path | CONFLICT | C03；非纯文档过时 |
| §11/§12 退款恢复 | 恢复曾用预存但不改真实付款 | 按 linked refund split 的 base benefit 减原账单当前 usage；历史事实不改 | CURRENT | 恢复上限是重建出的当前可恢复 usage，不是完整时间事件回放 |
| §12 多次/退款上限 | 未定义完整边界 | 多条关联无唯一限制，无原总额/累计金额上限，未要求被关联账单为正消费 | MISSING | U02；不能自行补“退款≤原消费” |
| §12 付款后退款 | 负消费产生当前反向余额 | 已付款债务与退款被再次毛额抵消，可能丢失应返金额 | CONFLICT | C02 |
| §13.1 scope | normal+large；large 全 Activity | v2 支持；旧 final 写入口仍要求 large | CURRENT | 新旧 RPC 范围不相同，须在基线列兼容边界 |
| §13.2 base_unified | 债务和预存全换为 base | 普通债务换 base；预存始终账户原币返还 | OUTDATED | 20260922 执行修正明确支持纯外币返还 |
| §13.2 单币种模式 | 关闭多币种只能 base_unified | plan 不检查开关，base 币 original_currency 也可执行 | CONFLICT | U03；外币执行却受 validate_financial_currency 限制 |
| §13.3～13.6 plan/path | 建议非付款；执行需精确匹配；路径可多跳 | 保持，v2 增 expected version/request_id；路径额不等于实际总付款 | CURRENT | 但作废后预览/执行不一致：C04 |
| §13.5 合并 | 同方向可合并，反向不抵消预存 | 还要求同币种；预存不参与普通图净额优化 | OUTDATED | 不同币种相同双方不合成一 Transfer |
| §13.7 重算 | 每笔成功后重新计算方案 | 保持；全额匹配单个 plan 项，不是一次自动执行全 plan，也不支持任意部分执行该项 | CURRENT | 按当前版本逐项执行 |
| §14 争议 | 只提示，不改余额/分配 | 独立表，解决字段；无 financial_version 变化 | CURRENT | 补录入者可代表相关一方标记、Creator/提出者可解决 |
| §15 财务历史锁 | 有真实历史 Expense 完全不能修改 | title/note/icon 可走 presentation RPC；财务字段/children/删除锁定 | OUTDATED | `20260921043414`；作废不解锁 |
| §15 多付 | 普通 Transfer 多付后形成反向债务 | 最新 allocation 重建有未分配金额会抛 23514；并非通用反向债务机制 | OUTDATED | 历史修改可能整个事务回滚 |
| §16.1 Expense 删除 | 逻辑删除永久不可恢复 | 与当前契约一致；旧 restore 对象仍在但已撤权 | CURRENT | 别因旧函数/旧测试仍在而恢复旧规则 |
| §16 子活动生命周期 | 基本未描述 | 可删除/恢复；有真实 transfer source 历史时两种变更均禁止 | MISSING | `20260913112306`、`20260920142942` |
| §16.3 Activity 删除 | Creator 逻辑删除 | 还要求未归档；删除后不可见/只读，未提供恢复 RPC | CURRENT | 保留所有历史，不是级联物理删除 |
| §17 完成 | 全部债务和预存为零 | view 只看 base debt，可能遗漏非零原币零 base 余债；余额展示混币相加 | CONFLICT | C08；不应承诺 LedgerUnit 有同等服务端状态实体 |
| §17 归档 | Creator；未结也可；只读 | 保持，warning RPC；争议不影响许可 | CURRENT | archive 旧返回金额只有 1 位，不适合作多币种准确总额 |
| §18 LWW/版本 | 普通编辑全部 LWW | 全量 Expense 更新无 expected version；presentation 可显式 optimistic version | OUTDATED | 行 version 与 Activity financial_version 不同 |
| §18 并发/幂等 | 活动锁、单事务、财务版本递增 | 主写链一致；每类 request_id 支持不同；预存 v2 重试错误 | MISSING | 第 5.6 节/C09；Expense 创建没有请求去重 |
| §19 附件 | image/file/link 预留；Unit 文字备注 | DB kind 只接受 image；ledger_units 无 note 字段 | OUTDATED | 图片/拍照客户端接线不等于 file/link 已支持 |
| §20/§21 实体职责 | 主要旧表列表 | 新历史表、FX 支持币/同步状态、快照与 marker 缺失 | MISSING | Prepayment 为 Transfer+component，不是独立资金表 |
| §22 流程 | 只写普通 FIFO、旧权限/币种流程 | 增候选→选择→preview(version)→commit(request)；预存与 final 要分支 | OUTDATED | 不可把所有写接口画成同一个幂等协议 |
| §23 示例 | 简单 AA/双边/预存/路径/争议 | 简单场景多成立，不能覆盖已付款退款、混币、撤销和残值 | MISSING | 保留正确示例，增加失败/生命周期示例 |
| §24 硬约束 | 所有金额 1 位、先净抵再预存、自动 completed | 精度需修订，后两项有已复现缺陷 | CONFLICT | 不可仅更改文字“承认”丢账 |
| §25 MVP 标准 | 满足即可闭环 | 本轮测试未全通过且存在财务错误 | INCOMPLETE | 当前不是可签署的最终完成状态 |

## 4. 指定账单还款：当前实现与未完成边界

Implementation Reference：`20260921051720_targeted_expense_repayment_contract.sql`；`TransferRepository.kt`、`TransferPayload.kt`、`TransferRequestStore.kt`、`TransferViewModel.kt`；`ExpenseRepository.kt`、`ExpenseViewModel.kt`；`TARGETED_REPAYMENT_CONTRACT.md` 仅作次级佐证。

| 问题 | 真实行为 |
|---|---|
| 还款对象 | Activity 内固定 debtor→creditor 的 ExpenseDebt 剩余可支付部分；不是向 Expense 总额付款，也不改 payments/splits |
| 双方 | 请求固定 from/to；必须有效、同活动、不同人；普通成员认领一方，Creator 自己是一方或 behalf 未认领的一方 |
| 只能指定一账单？ | 否。`TARGETED` 必须传非空 Expense ID 集合，可多选；commit 拒绝 null 元素、去重并按 ID 规范化保存。`FIFO` 忽略目标列表 |
| 可选账单 | 必须有对应双方、付款币种允许的剩余债务；排除已删除 Expense/Unit/Activity；扣 reverse offset、有效普通/final 分配、当前 usage 后有原币余额 |
| 金额上限 | `0 < amount ≤ 当前同方向 bilateral cap` 且 `≤所选候选的 payment_currency_amount 合计`；不是每张账单原总额 |
| 部分、多次 | 允许在剩余上限内部分/多次；每次新事实必须取最新 financial_version 和新 request_id |
| 多选分配 | 不接受客户端逐单分配额；服务端在所选集合内排序分配。候选列表按 occurred_at/created_at/expense_id/debt_id；preview/commit 的显式 ORDER BY 为 occurred_at/expense_id/debt_id，**同 occurred_at 时不保证按 created_at** |
| 币种 | base 付款可覆盖各账单原币，使用各自历史 FX；外币付款仅覆盖同原币账单，不允许任意第三币兑换 |
| 保存 | settlement Transfer + settlement component + immutable `transfer_expense_allocations`；`settlement_mode=TARGETED/FIFO`、`target_expense_ids` 是历史意图 |
| ExpenseDebt 变化 | 不修改原始 debt 金额；由 allocation/usage/offset 推导余债；触及账单设 financial_locked，后续全量重建保留其 debt 行 |
| BilateralDebt 变化 | 重建双方币种净余债；金额下限保护与退款交互存在 C02，不代表所有反向资金结果都正确 |
| 对预存 | TARGETED 本次提交保留已有 usage，不抢回预存使账单可付；之后 void/其他重建可以重算动态 usage；FIFO 分支执行完整预存重建 |
| 对 final | 当前未结余额改变，下次方案重算；final paths 触发永久 allocation，用于账单进度；受 C04/C08 等限制 |
| 对 Activity | 成功 financial_version+1，状态视图即时反映投影；没有“还款直接把 Activity 状态字段写 completed” |
| Refund 后 | 原付款事实/分配保持不变；退款是独立负 Expense；已付款后退款的实际 bilateral 结果存在 C02，不能签署为已正确闭环 |
| Expense 修改 | 有一次真实触及就锁财务字段和 children；只能改展示字段；未锁账单修改需重算且可能因既有事实无法分配而失败 |
| 删除/恢复 | 已触及账单禁止删除，即使付款已 void；Expense 恢复接口已撤权；未触及的账单按自身删除权限和退款引用保护处理 |
| 已结清账单 | 剩余为零不能作为新 TARGETED 候选；“financial_locked”不等于“已全额结清”：部分还款后锁定但仍可继续还剩余 |
| 并发 | Activity advisory transaction lock + Activity FOR UPDATE；锁内校验版本并重算 preview；实测余额100的两笔80仅一笔成功 |
| 幂等 | request_id/expected_version 必填；同 Activity 请求唯一；同 payload 返回保存的 result，先于 stale version 检查；不同 payload 报23505。已归档/删除仍先拒绝，不是跨生命周期无条件重试 |
| 历史缺口 | migration 只从当时仍存在的 allocation/path 回填；已 void 或已被重建覆盖的旧金额不能凭 source identity 还原。没有历史事实的旧转账保留旧 FIFO 重建路径 |

**完成判定：主路径已实现且两份专项 SQL 通过；作为最后核心业务的完整收口仍为 `IMPLEMENTATION INCOMPLETE`。** 原因不是缺少目标选择或提交 RPC，而是退款、重算、最终结算作废和原币残值的集成边界有实际错误；端到端与全部回归未通过。不要在新基线中把整个功能写成“尚未实现”，也不要写成“已全面验收”。

## 5. 其他关键业务的当前行为

### 5.1 Expense、Refund 与删除

- Expense 的原币字段为 `original_amount/original_currency/fx_rate`，不是文档示意中的 `currency/exchange_rate`。Payment/Split 的 `amount` 是该 Expense 原币；各有 base_amount。付款、分摊同 Expense 正负号、同币种，双方可不同集合，但均必须是该 Activity 活跃参与人。
- AA 原币按四位单位分配；base AA 再按稳定参与人顺序分配 0.1 单位余数。手动 Split 和 Payment 折算尾差给稳定顺序最后一行；不要把三者舍入算法混写。
- Refund 无独立创建 RPC/表。Android `RefundExpenseInput.toCreateInput` 把总额及子项转负，调用 `create_expense_auto_rate`。原账单 payment/split 保持不变；退款自己的 payment 表示实际收到钱的人，split 表示退款受益者。
- linked refund 要求引用当前活动内可用 Expense；auto 路径还要求同币并继承其 FX。没有“只能一次退款”、累计退款金额上限、引用必须为正消费、分摊必须与原账单相同比例等数据库规则。旧手工入口更宽松。C01 导致当前 auto linked 路径不能正常提交。
- 未关联的负 Expense 不恢复某笔指定 usage，按自己的负净额形成债务。linked refund 根据负 split 的 base benefit 逐个释放原 Expense、该 owner 的当前 usage；释放不超过可用 usage。其他账单的 usage 不作为该退款直接释放对象；有多币种 usage 时通过 bill FX 换回预存用量。
- 多次 linked refund 按退款 occurred_at/created_at/id 与 participant 顺序迭代；没有请求幂等键。活动锁序列化了写入，但**序列化不会补出不存在的总退款上限**。
- 有活跃关联退款时原 Expense 删除 RPC 拒绝；未锁原 Expense 仍可通过旧全量更新更改财务数据，没有“有退款就锁财务”的通用约束。既有退款不随原账单更新而自动改金额/FX；usage 重建依据当前来源重新计算。这是历史修改设计待确认处 U02。
- Refund 自身服从普通 Expense 财务锁、录入者/Creator 删除权限和不可恢复规则；删除合资格退款后重算 usage/balance。不能笼统称“退款可恢复”。

### 5.2 Prepayment

- 真实资金来源是 `transfers.type=prepayment`，方向 owner→custodian，金额分为 settlement component 与 prepayment component；只有后者计入资金池。单独返还为 custodian→owner，prepayment_return component 减同币账户。
- v2 先按当前 eligible bilateral cap 分割新增款项，余款入池；没有 large-only 检查。v2 新增任意成员可记，behalf 必须空；返还仍走普通双方认领/Creator 代记门槛。旧 `create_prepayment` 权限与币种能力未升级为完全相同。
- 账户是余额池，不保存每笔入金剩余批次。FIFO 指**可用债务的账单时间顺序**，不是“预存入金批次 FIFO”。大型活动跨所有子活动使用，不能绑定单个 Unit。
- 同 owner/custodian 的外币账户先于 base 账户处理；外币只能用同原币债务；base 账户可用各币种剩余债务，取账单 FX，不能把外币 A 任意换外币 B。
- usage 与账户都重建；未锁账单修改/删除会影响用量，符合条件的子活动删除/恢复也会重建。TARGETED 提交特意保留当时 usage。**当前重建没有完整落实“先双边净抵再用预存”**，详见 C03。
- v2 返还上限为当前同币账户余额，需活动锁及 expected version；金额必须正，base 金额限一位，外币可四位。并发不会同时读取并花掉同一版本余额，但重复请求存在 C09。
- 退款释放 usage 不意味着新增真实转账，也不改历史 prepayment component。已经返还后再作废入金可使资金池负源额被忽略，见 C10。

### 5.3 Transfer / Settlement / 历史

- 普通 settlement 新入口为 `create_expense_repayment_v2`，旧 `create_settlement_transfer` 两个重载仍 callable；客户端仅在契约缺失且不需要新语义时允许受限兼容，不能把旧接口当 TARGETED 的降级实现。
- Transfer active→voided 是唯一已开放生命周期变更；void reason 必填，当前成员且录入者/Creator 可操作；重复 void 报错，不是幂等 no-op。两种 void RPC 最终走同一实现，实际可处理四类 Transfer。
- lifecycle trigger 保护金额、双方、类型、币种、发生时间、录入人、代记人、request_id/payload、mode 和 targets；已 void 行任何实际改动都拒绝。`request_result` 允许首次提交后写入，不能把“整行从 INSERT 后绝对不能 UPDATE”作为规则。
- allocation/path 插入捕捉 source history；void 后来源与永久金额事实保留，动态 allocation 去除，Expense 财务锁不清。自动预存 usage 不建立真实 source history。
- source history 与永久 allocation 有 UPDATE/DELETE 拒绝 trigger；components、final paths、audit 对普通客户端没有直接写权限，但并非所有这些表都有相同的超级用户级不可变 trigger。
- 新普通还款永久固定已分配账单；旧普通入口和新的混合预存 settlement component 不自动获得同等永久金额事实（source marker 不等于金额分配）。重建保证不能概括成“所有历史 allocation 都完全不变”。

### 5.4 Multi Currency

| 项目 | 当前口径 |
|---|---|
| Expense 快照 | original 4位、base 1位、fx 10位；auto source same_currency/ECB_REFERENCE；旧入口/迁移兼容 legacy_manual |
| 缓存更新 | ECB r(base)/r(quote) round 10；service-role 更新；至少5/至多100币，EUR=1，日期/正值校验；异常事务不提交；过期缓存仍可用于新外币账单 |
| 历史不重估 | 缓存更新不主动改旧 Expense；不改币的自动编辑设计为保留快照，实际受 C01 阻断；关联退款设计继承快照 |
| 普通债务 | 原币决定拓扑；双边同币净抵；base 存历史折算结果；可出现 original>0/base=0 的余债 |
| 还款 | 外币只清同币，base 可清不同币；分配保存 debt FX；base 全额消耗某候选时新接口取完整剩余 original，避免反除残差 |
| 预存 | 原币资金池，不能声称每笔存入都按存入日 ECB 固化 base；base 消耗外债时使用账单 FX |
| 最终结算 | base_unified 的普通部分跨币转base；original_currency 分币优化；预存两种模式都按账户原币返还 |
| 关闭多币种 | 普通还款仍可清旧外债；v2预存/返还/final执行会因 validate_financial_currency 拒绝外币；plan读接口仍可能给出外币项目 |
| 精度限制 | 新 TARGETED 可记录零base的外币 allocation；旧 FIFO、usage、final path 并不全支持这一边界，见 C08/C11 |

不计算汇兑损益是产品范围；**不等于原币/基准币残值可以丢弃**。`activity_financial_status.total_prepayment` 和 participant view 当前把不同账户原币直接相加，不能标注为正确的 base 总金额。

### 5.5 Final Settlement、完成和归档

- v2 以 Activity 全范围 bilateral residual 为普通债务图，可跨人及子活动，用确定性路径分解减少付款；不承诺数学全局最少笔数。无部分子活动过滤参数。
- 预存返还不进入普通图净额计算；方向始终 custodian→owner；同双方同币种才与普通建议合并，反向不互相抵消。
- plan 只读、不建长期会话、不自动付款。execute 需 mode/currency/双方/金额精确匹配锁内最新单项 plan；该项不得任意部分付款。request 和版本必须齐备；每项成功后重取剩余 plan。
- 20260922 最新规则：任意 Activity Member 可登记当前 final plan，不需要认领任何一方；behalf 若提供仍必须是一方；与普通 settlement 的 actor gate 不同。
- 执行写 Transfer、component、路径和 source/永久 allocation，随后重建并增 financial_version。同一真实付款沿多跳可以结清多段，不能要求所有路径金额之和等于 Transfer 金额。
- 两种模式的预存返还都使用账户币种；当前外币纯返还 path 的 `base_amount=original_amount, fx_rate=1` 是实际写法，**不能当作可信基准币折算快照**（C07）。
- 作废后的 final path 仍作为历史存在；新的 plan 不计已 void 转账，但执行 capacity 查询未同样排除，造成 C04。
- 纯环路、所有参与人净额均为零时，当前 flow 没有负净额 source，不发普通付款建议；bilateral 行可能仍存在、Activity 仍 active。没有自动登记“无现金消环”的已实现规则，最终产品意图为 U04。
- completed 是活动/参与人视图计算值；无手动强制完成 RPC，completed 不锁记账。没有统一持久化 LedgerUnit financial_status 表；客户端账单/单元展示需要按实际分配另算，不可假设与 Activity 同一判据。
- archive/unarchive 只允许 Creator，取同活动锁；未结也允许归档，提示不等于禁止；归档后财务、成员、附件等写路径拒绝。Activity 删除要求未归档，删除后无恢复入口。子活动没有独立 archive。

### 5.6 并发、版本与请求幂等

所有普通资金写链在一次 PostgreSQL RPC 事务内完成，异常使事实、投影、版本一起回滚。共享锁为 `pg_advisory_xact_lock(hashtextextended('shared-ledger:debt-projection:' || activity_id,0))`，配合 Activity/相关行锁。只读候选/preview 不预留余额，提交必须再校验。

| 写入路径 | 幂等/版本真实保证 |
|---|---|
| create_expense / auto_rate、create_activity、create_sub_activity | 无 request_id 去重；网络重复提交可能创建新记录，不得宣称全业务 exactly-once |
| update_expense / auto_rate | 旧全量更新 LWW，增加 Expense.version 和 financial_version；并非带 expected-version 的 compare-and-swap |
| update_expense_presentation | 可传 expected_version，不匹配40001；仅 Expense.version+1，Activity financial_version不变 |
| create_expense_repayment_v2 | request+financial version必填；规范化targets；同payload旧请求优先返回原result；新请求过期40001；变payload23505 |
| 旧 create_settlement_transfer | 新重载 request_id可空、无expected version；重复比对双方/金额/币种/时间/代记/类型，返回同Transfer与**当前**版本；旧重载不提供request |
| create_prepayment_v2 / return_v2 | request+version必填，但版本校验发生在查旧request之前；成功后的原payload重试失败：C09 |
| execute/create_final_settlement_v2 | request+version必填；在活动可写/成员/币种校验后，旧request命中先于版本比较；payload包括mode、时间、版本 |
| legacy prepayment/final writes | 无统一请求幂等或预览版本契约；仍是暴露兼容入口，不应忽略 |
| void | 活动锁+权限；重复void报55000；保留历史，不回用原request_id创建新付款 |
| delete Expense / sub lifecycle / claim / join | 部分有状态no-op/唯一键语义，不等于带payload的request幂等；原记录被保护时依然失败 |
| dispute / attachment / membership | 有相应权限/状态检查；不推进financial_version；remove_dispute/complete_attachment等不是任意重复都成功 |

Android 两类 DataStore 持久化 pending request、固定 occurred_at/payload，区分“提交失败”和“已提交但刷新失败”。客户端缓存不能弥补服务端 C09，也不能给没有 request_id 的 Expense 创建带来数据库唯一性。

## 6. 冲突、明确错误与待确认设计

### C01 — 自动汇率编辑/关联退款执行失败（CONFLICT，已复现）

- **旧规则**：同币编辑保留快照，关联退款继承原账单 FX。
- **当前实现**：`private.resolve_expense_fx_snapshot` 被声明为 STABLE，却在 existing/refund 分支 `SELECT ... FOR SHARE`。PostgreSQL 报 `SELECT FOR SHARE is not allowed in a non-volatile function`。
- **Migration / RPC**：`20260913112419_ecb_exchange_rate_expense_snapshots.sql`；`update_expense_auto_rate`、`create_expense_auto_rate`（含 icon 重载）。
- **相关测试**：`exchange_rate_expense_snapshots.sql` 本身先因非数字 join_code 失败；不能作为通过证据。审计探针实际创建原账单后分别调用自动编辑及关联退款，两者均复现。
- **判断**：明确执行错误，不是最终业务设计改变。正常自动新建与 presentation 更新不走该锁分支，不能把它们一并判失败；修复前不能写“自动编辑/退款已验收”。

### C02 — 已还款后的退款应返债务被吞掉（CONFLICT，已复现）

- **旧规则**：真实付款不变，退款作为负消费更新余额，超出预存恢复部分形成当前余额。
- **当前实现**：bilateral 重建先用原始毛债务计算反向抵消，再减 settlement，并分别 `greatest(...,0)`，可同时扣掉本该返还的反向债务。
- **复现**：B 替 A 支付100 → A TARGETED还B100 → 同原账单负退款100由B收到、A受益。原付款仍有效，实际应有返款含义；实现 `bilateral_debts` 为空、Activity completed。此探针用仍开放的手工 Expense入口避开 C01，验证投影本身，而不是宣称 Android退款路径成功。
- **Migration / RPC**：`20260920142845_multi_currency_prepayment_final_settlement_core.sql` 的 `rebuild_bilateral_debts_locked`；`20260921051720` 的 TARGETED；create_expense / create_expense_repayment_v2。
- **相关测试**：两份 targeted专项均通过但无此后续退款案例；`phase9_fair_aa_final_settlement.sql` 亦在负退款后的方案断言失败，不应简单丢弃为旧测试。
- **判断**：会丢失真实资金含义，不能把“退款后无需返款”收录为最终设计；需修复或显式业务裁定。

### C03 — 预存 usage 没有先扣反向净抵/最终路径（CONFLICT）

- **旧规则**：仅抵扣双边抵消后的 owner→custodian 净债务。
- **当前实现**：最新 usage available 只减普通 allocation 和已有 usage，未减 reverse debt 或有效 final path；之后 bilateral 又减毛额 offset。
- **复现（已执行）**：A在B处预存100 → A欠B账单100 → B欠A账单100。双边债务为空，但usage仍100、预存余额0；按旧规则应释放/保留预存100，而不是与已抵消债务同时消耗。
- **Migration / RPC**：`20260920152349_fix_prepayment_currency_priority.sql`，覆盖 `rebuild_prepayment_projections_locked`；Expense写入、void、FIFO、final均可触发。
- **相关测试**：`phase5_prepayment.sql`通过只能覆盖基础场景；`phase5_prepayment_extended.sql`在重建allocation断言失败；targeted正常保留usage案例不足以否定本冲突。
- **判断**：净抵场景为已复现实现错误；final path被二次使用风险为静态确认的漏减分支，本轮没有将其冒称独立复现成功。

### C04 — 最终结算作废后，plan 可见但无法再执行（CONFLICT，已复现）

- **旧规则**：作废后可按当前方案创建正确新记录，历史不删除。
- **当前实现**：plan/bilateral排除void；execute v2的available_base/original减 `final_settlement_paths` 时未 join有效Transfer，仍扣掉void历史。
- **复现**：债务100 → base_unified final100 → void → preview再给100 → 新request/current version执行100报 `final settlement path has no remaining expense debt capacity`。
- **Migration / RPC**：最终有效定义 `20260922072033_final_settlement_member_actor_gate.sql`；preview_final_settlement_v2 / execute_final_settlement_v2 / void_prepayment_transfer。
- **相关测试**：旧phase6/phase8侧重曾经允许的恢复，不能覆盖新的“void后创建新final”契约；审计探针实测。
- **判断**：plan/execute内部不一致，必须作为实现错误保留，不能通过禁止用户再结算的文档补丁掩盖。

### C05 — 合法零债务 Expense 被拒绝（CONFLICT，已复现）

- **旧规则**：付款净额为0无需结算，Expense仍是消费事实。
- **当前实现**：`v_base_debt_total=0` 直接报23514，即使非零消费100由同一人支付并承担。
- **Migration / RPC**：`20260920120259_fix_multi_currency_allocation_invariants.sql` 的 `rebuild_expense_debts_locked`；全部Expense创建/重算链。
- **相关测试**：`phase2c_base_amount_normalization.sql:230`亦失败于该错误；审计单人自付100复现。
- **判断**：与消费事实和债务分离冲突；没有提交/文档证据说明最终设计禁止无欠款账单，不能直接写为“不支持”。

### C06 — 手工 FX 旧 RPC 仍接受客户端任意汇率（CONFLICT，已复现）

- **旧规则**：客户端汇率不是可信输入，外币新建必须用服务端缓存。
- **当前实现**：authenticated仍能调用两个 create_expense / update_expense手工重载；外币只检查开关与正rate，不校验ECB。
- **复现**：无ECB缓存的新活动，用 create_expense 提交USD10、fx123，成功保存base1230、source legacy_manual。
- **Migration / RPC**：`20260830115402`、`20260919094626_expense_icon_keys.sql`的旧入口授权；新auto入口未撤旧入口。
- **相关测试**：多数SQL fixture继续依赖手工入口；`exchange_rate_expense_snapshots.sql`未能到达核心测试。
- **判断**：Android已使用auto，但“服务器完全不信任客户端FX”尚未成立。保留兼容还是关闭旧入口是 **UNCLEAR**，不能擅自撤权。

### C07 — 所有资金记录完整 FX 快照的承诺不成立（CONFLICT，静态确认）

- **旧规则**：多币种Transfer/Prepayment保存原币、base、FX；base_unified预存也折算base。
- **当前实现**：Transfer主要保存amount/currency；debt allocation/usage保存账单FX；预存账户仅原币余额。外币最终返还path却写base=原币金额、fx=1。没有存入日独立FX可追溯。另一个字段口径差异：base_unified普通路径的path_currency保存债务原币，`capture_final_settlement_allocation_fact`将其写入永久allocation.payment_currency，因此该字段可能不同于实际Transfer.currency；不能仅凭payment字段名把路径币种当实际付款币种。
- **Migration / RPC**：`20260920142845`、`20260922031227`、`20260922072033`；create_prepayment_v2 / execute_final_settlement_v2。
- **相关测试**：targeted multicurrency验证债务快照，不证明预存入金快照；没有覆盖“外币返还base字段是真实折算”的通过证据。
- **判断**：原币返还模式属于已明确演进，可修文档；错误/占位的base字段不能伪装成真实汇率快照。是否补资金级FX设计为 **UNCLEAR**，本次不设计schema。

### C08 — 非零原币余债可显示 completed，余额汇总混币（CONFLICT）

- **旧规则**：全部当前债务=0且预存=0才完成。
- **复现（已执行）**：2 JPY、账单fx0.05，TARGETED支付1.01 JPY后，bilateral original=0.99/base=0，`activity_financial_status.completed=true`。
- **当前实现**：view仅sum bilateral.amount(base)；participant view也未保留原币维度。total_prepayment直接sum不同原币账户，不能当成统一币种金额；archive RPC还把预存sum cast为1位。
- **Migration / RPC**：`20260920142845`两个view；`20260831160108`archive/unarchive；`20260921051720`微额分配。
- **相关测试**：phase12原本包含小额场景但更早遇C11停止；两份targeted专项没有覆盖本状态。
- **判断**：完成判据错误已复现；混币汇总单位错误静态确认。需要先统一金额口径，再签署完成基线。

### C09 — 预存及返还的 request_id 不满足成功后重试（CONFLICT，均已复现）

- **旧规则/现有契约方向**：重复request返回同事实、不重复付款；其他v2接口先命中旧请求。
- **当前实现**：prepayment/return先 assert_financial_version，再查询request；首次成功推进版本，原payload第二次报40001；把payload改新版本又与原request_payload冲突。
- **Migration / RPC**：新增预存最终定义`20260921022101`；返还`20260920142845`；create_prepayment_v2 / create_prepayment_return_v2。
- **复现**：预存100成功后原payload再提交；另一个探针预存100、返还20成功后重复返还原payload；均报financial_version mismatch。
- **相关测试**：targeted测试验证的是另一条正确的重试顺序；Android FinancialRequestStore测试不能证明SQL正确。
- **判断**：明确重试实现缺陷。唯一索引能阻止重复事实，但不能把“无重复行”当成“原请求可重放成功”。

### C10 — 已返还的预存再作废来源，负资金源被隐藏（CONFLICT，已复现；处理策略UNCLEAR）

- **旧规则**：真实资金事实保留，作废后重算当前余额。
- **复现**：预存100→返还100→作废原预存。返还Transfer仍有效100；账户和bilateral均为空。
- **当前实现**：账户facts按component求funded；`having sum(delta)>=0`排除负数；余额再greatest(...,0)，没有相应反向余额/拒绝撤销机制。
- **Migration / RPC**：`20260920152349`账户重建、`20260831160108` void实现；void_prepayment_transfer。
- **相关测试**：phase5基础通过不代表资金来源作废链正确；审计探针实测。
- **判断**：无法把有效返还100的净资金含义静默消失视为闭环。应拒绝作废、要求先撤返还还是保留反向债务，资料不足，交人工确认，不擅自设计。

### C11 — 旧 FIFO 重建重新拒绝零 base 的外币分配（CONFLICT，既有测试复现）

- **旧规则/较早修复**：原币转账可四位，极小原币支付可对应base0，最终尾差须守恒。
- **当前实现**：20260921051720的旧事实fallback分支在 `v_allocate_base<=0` 时continue，最后按未分配金额抛23514；新永久TARGETED路径允许base0，两个入口不一致。
- **Migration / RPC**：`20260920120259`曾放开约束；`20260921051720`覆盖 `rebuild_transfer_allocations_locked`；旧 create_settlement_transfer。
- **相关测试**：`phase12_multi_currency_allocation_invariants.sql:207`，2 JPY账单第一次还0.01 JPY报 `has 0.0100 unallocated JPY`。
- **判断**：较新代码回归，不能笼统把phase12归为废弃测试；未来基线应明确原币极小支付限制/尾差，而非忽略失败。

### U01～U05 — 无法自行判定的业务意图（UNCLEAR）

| 编号 | 旧规则/冲突 | 当前实现与来源 | 相关测试 | 待确认 |
|---|---|---|---|---|
| U01 | 子活动有独立参与名单；large root只作退款/调整 | `20260830100426`无关联实体，create_sub_activity仅activity/name，replace_expense_children仅校验Activity；create_expense不限制root正消费 | phase10验证生命周期，不证明名单隔离 | 这两条是否仅旧设计？若保留则应标未实现，不能写当前已强制 |
| U02 | 退款上限、原账单历史修改未完整定义 | 多次、不限累计、可引用负Expense、原账单有退款仍可财务更新（未锁时）；auto入口另有C01 | phase5退款与审计over-refund探针（原100退150成功） | 接受自由负调整还是限制累计/引用对象？不得猜测 |
| U03 | 多币种关闭仅base模式 | plan不查开关；普通还旧外债可用；预存/return/final外币执行拒绝；update_settings可关开关 | phase11普通历史币种；缺跨模块关闭后验收 | 是否必须能清偿所有既有外币资金？目前不可统一声称 |
| U04 | 最终结算覆盖全部未结账务 | 纯环路净额为0时flow无source、plan为空而bilateral可非零 | phase6/9非纯环路验证不足 | 接受空建议但active，还是存在其他结束规则？实现没有答案 |
| U05 | 幂等/来源历史被理解为全量永久追溯 | migration明确不恢复已丢失的旧allocation金额；legacy写与新v2保证不同；request payload未绑定recorded_by，TARGETED旧request命中早于成员/actor检查 | targeted只覆盖相同用户重复 | 兼容RPC保留范围、历史回填缺口，以及跨调用人重放边界须确认；未把后者宣称已复现越权 |

## 7. 应新增、废弃及明确未完成的规则

### 7.1 已实现、基线缺失的内容

1. 指定还款的候选/preview/commit/progress完整链；一个或多个目标、双重金额上限、不能抢占预存、已锁但未清仍可还。
2. `financial_locked` 与业务“已结清”分离，presentation-only编辑及可选Expense版本检查。
3. 永久allocation、source marker、final path与动态projection的不同职责；void后历史和锁持续；旧数据不可凭空回填。
4. 原币决定Debt拓扑；每列精度；同币净抵、base全币分配、外币同币分配；账户币优先于base账户。
5. v2预存成员权限、v2最终结算成员权限，与普通还款/返还权限的差异。
6. 子活动软删除/恢复、真实资金历史保护、不改变Expense自身删除状态。
7. 各RPC实际的request/version协议和兼容入口限制；Android提交确认与重试payload持久化。
8. 附件10张/10MiB与状态限制、独立争议表/解决权限、服务端汇率同步状态。

### 7.2 应删除或改写的旧表述

- AA基准币尾差全给最后一人；所有金额都只保留1位；只按base净额决定Debt双方。
- 所有普通还款只能FIFO；“每笔多币种Transfer/Prepayment都有独立完整FX快照”。
- 有资金历史的Expense任何字段都不能改；所有ExpenseDebt都可任意重建替换。
- base_unified连外币预存也隐式换成base；普通/预存/final具有相同身份门槛。
- 只靠“Member可删账单”描述权限；普通Transfer多付总会变成反向债务。
- file/link是当前已支持附件；LedgerUnit文字备注已经有后端字段。
- 其他技术文档中restore_expense/restore_transfer仍可调用、Phase7契约已冻结的旧断言。此次不自动修改其他文档；未来引用应标历史而非与新基线并列权威。

### 7.3 当前仍未完成

**IMPLEMENTATION INCOMPLETE：** 指定还款与退款/重算/最终结算/原币残值的联合闭环；自动汇率编辑及关联退款；预存净抵和重试；final作废后重执行；完整当前契约回归。

**UNCLEAR 而非承诺开发：** 子活动名单、退款累计上限、纯环路收尾、资金级FX、关闭多币种后的历史返还政策、负预存来源处理。除非用户确认保留这些设计，不得把它们排进新增功能计划。

**明确当前不开放：** Expense恢复、Transfer恢复/编辑/再次作废、客户端直接改财务投影、手动强制完成、按子活动范围独立预存、任意创建无plan支撑的final、普通日常三方债务优化、任意第三币种兑换还款。

## 8. RPC 行为索引

附录 B列出当前public业务RPC的**准确输入/输出和重载**，来自临时库catalog，并与仓库调用核对。以下族表给出写表、读状态、事务锁、幂等及失败条件；二者结合为完整RPC清单，不以旧API文档代替实际签名。

记号：`F`=Activity财务版本；`E`=Expense.version；`L`=Activity advisory事务锁+Activity行锁；`P`=重建transfer_allocations/prepayment_accounts/prepayment_usages/bilateral_debts；source插入可触发financial_locked及audit。写RPC一次调用为一个数据库事务，相关audit在同事务内；只读RPC不占有付款额度。

| 族 | RPC | 读取/写入 | 锁、版本、幂等 | 主要失败条件/规则 |
|---|---|---|---|---|
| A1 | create_activity | 写activities/member/root或default、audit | 单事务；join_code唯一冲突重试≤100；无request | 未登录、名称/币种/类型非法 |
| A2 | join_activity_by_code | 读活动可用性；写membership/audit | 活动行锁、成员唯一键；已加入返回is_new=false | 加入码不存在、归档/删除；不自动认领 |
| A3 | create_sub_activity | 读large/root/member；写unit、名单锁/audit | Activity/root行锁；无request/F递增 | 非成员、非large、无root、归档/删除、空名 |
| A4 | delete_sub_activity / restore_sub_activity | 读member/type/source；改unit、全Activity debt+P、audit | L+unit锁；真正变更F+1；同状态no-op | 非large sub、归档/删除、真实transfer历史；单个Expense删除状态不变 |
| A5 | create_participant / delete_participant | 读名单锁/member/claim/财务引用；写participant/audit | L；无request/F变化 | 名单锁、无成员、无效名称/顺序；删除被认领/使用者拒绝 |
| A6 | claim_participant / unclaim_participant | 读活动、成员、participant；写claim/audit | L+participant锁/唯一键；相同认领no-op | 别人已认领、自己已认领别的人、归档/删除 |
| A7 | update_activity_settings | 读creator/F/状态；写活动/audit | L；无request/F变化 | 非Creator；F>0改base；无效币种/名称；归档/删除 |
| A8 | remove_activity_member / transfer_activity_creator / delete_activity | 读Creator/member/状态；删访问关系或改活动/audit | L；不重写历史；无request/F变化 | Creator不能移除自己；新Creator须其他Member；归档/删除不可管理 |
| A9 | archive_activity / unarchive_activity | 读Creator、debt/accounts；改archived_at/audit | L；不推进F；changed状态返回 | 非Creator/成员或已删除；允许未结归档；旧金额返回精度限制 |
| E1 | create_expense / create_expense_auto_rate（各2重载） | 读Unit/Activity/member/participant/可选original/cache；写Expense/children/debt/P、名单锁/audit | L（auto先resolve快照）；F+1,E=1；无request | 非零/符号/合计/成员/FX/拆分；C01/C05/C06 |
| E2 | update_expense / update_expense_auto_rate（各2重载） | 读旧Expense/来源锁/Unit；替换children、debt/P、audit | L+Expense行锁；E+1,F+1；LWW | 归档/删除、跨Activity、财务锁；auto编辑C01 |
| E3 | update_expense_presentation | 读member/Expense/expected E；只写title/note/icon、E、audit | L+Expense锁；F不变；expected E可选 | 空title、无权限、归档/删除、过期E；已财务锁仍允许 |
| E4 | delete_expense | 读member/录入者/Creator、active refunds/source；软删除、debt/P/audit | L+Expense；真正变更E/F推进；已删返回false | 非录入者/Creator、有活跃退款、有真实历史 |
| T1 | list_settlement_options | 读bilateral/Activity/member，返回双方币种cap与F | 只读 | 非成员；不会因base为0过滤非零原币 |
| T2 | list_transfer_expense_candidates / preview_expense_repayment / get_expense_repayment_progress | 读ExpenseDebt、Expense/Unit、普通/final分配、usage、reverse、F | 只读；preview检查F | 无成员/Activity、参数/币种格式；preview目标不合格、超cap、过期版本 |
| T3 | create_expense_repayment_v2 | 读T2+actor+request；写Transfer/component/永久allocation/source、P或TARGETED部分P、audit | L+participant；F+1；完整请求去重 | request/version必填、成员/actor、金额双上限、目标集、archived；重放见5.6 |
| T4 | create_settlement_transfer（2重载） | 读bilateral/actor/request；写Transfer/component、P/source/audit | L+participant；F+1；8参可选request，6参无 | 同方向cap、币种/精度、actor；不能提供TARGETED；C11 |
| P1 | preview_prepayment | 读member/participants/Activity/currency/bilateral/account | 只读，返回F | 任意成员；同币cap分settlement/存款；归档/删除/无效双方 |
| P2 | create_prepayment_v2 | 读P1+request；写Transfer/components/P/source/audit | L；F+1；request/version必填但C09 | 任意成员；behalf非空拒绝；币种支持、有效双方 |
| P3 | create_prepayment_return_v2 | 读账户/actor/currency/request；写Transfer/component/P/audit | L；F+1；request/version必填但C09 | 余额上限、普通actor门槛、币种开关 |
| P4 | create_prepayment / create_prepayment_return | 读旧base账户/债务、actor；写Transfer/components/P | L+participant；F+1；无request | 旧base-only协议、双方认领；多币账户读口径未升级，不视为v2等价 |
| T5 | void_settlement_transfer / void_prepayment_transfer | 读Transfer/creator/recorded_by/状态；设void、P/audit | L+Transfer；F+1；再void报错 | reason空、无成员/录入权限、归档/删除；不删历史、不恢复 |
| F1 | preview_final_settlement_v2 / get_final_settlement_plan_v2 / preview_activity_settlement_v2 | 读bilateral/accounts/member/Activity，返回模式化plan+F | 只读 | 非成员、无Activity、模式非法；不检查多币开关造成U03 |
| F2 | execute_final_settlement_v2 / create_final_settlement_v2 | 读F1+currency/request；写Transfer/component/path/source/永久allocation、P/audit | L；F+1；request/version必填、重复先于版本 | 任意成员、精确匹配当前单项plan；C04等 |
| F3 | preview_final_settlement / get_final_settlement_plan / preview_activity_settlement；create_final_settlement / execute_final_settlement / execute_final_settlement_item | 旧plan与旧写入；后者仍要求large；写Transfer/component/path/P | 读或L；写F+1；无request/version | 旧模式协议；来源映射和币种字段不等同v2，客户端final不降级到此 |
| D1 | add_transfer_dispute / remove_transfer_dispute | 读member/Transfer/claim/recorded_by/Creator；upsert/resolve dispute+audit | add取L；remove为权限条件UPDATE；F不变 | add要求有效Transfer且相关party；remove提出者或Creator；归档拒绝 |
| H1 | create_attachment / complete_attachment / delete_attachment | 读member/Unit/Expense/Storage object；写metadata/audit；文件另走Storage API | create取活动锁限额；后两者条件UPDATE；F不变 | 格式/大小/数量/关联/状态/权限；complete必须已存在对象；delete上传者或Creator |
| X1 | list_supported_exchange_currencies / get_exchange_rate / get_exchange_rate_sync_status | 读参考缓存/状态 | 只读；不重估历史 | get_exchange_rate同币返回1；缺缓存返回空行 |
| X2 | claim_exchange_rate_sync / replace_exchange_rate_cache / record_exchange_rate_sync_failure | service-role同步claim、币种/cache和状态 | claim锁单例并设置刷新间隔；replace单事务 | 非service_role拒绝；payload校验；失败不覆盖旧cache；不推进Activity F |
| R0 | restore_expense / restore_transfer | 旧对象存在但已撤权 | authenticated/service_role执行权均撤；trigger再防恢复 | **不是当前可用RPC**；不能列入已支持流程 |

## 9. 实际验证结果与测试债务

### 9.1 数据库测试

在临时审计库用 `psql -v ON_ERROR_STOP=1` 执行；需要未限定 `plan/ok` 的3个脚本补装pgTAP并设置search_path后重跑，最终结果如下。按**脚本**计 6 通过、11 未通过，不能解释为断言数量或11个独立业务缺陷。

| 脚本 | 结果 | 原因/解释 |
|---|---|---|
| phase3_debt_projection.sql | PASS | 基础债务投影 |
| phase5_prepayment.sql | PASS | 基础预存路径，不代表C03/C09/C10通过 |
| fix_original_currency_debt_projection.sql | PASS | 补齐pgTAP运行前提后通过 |
| phase11_multi_currency_settlement.sql | PASS | 补齐pgTAP运行前提后通过 |
| targeted_expense_repayment.sql | PASS | 多目标、cap/offset/usage、永久分配、重建、重试/过期、void/锁 |
| targeted_expense_repayment_multicurrency.sql | PASS | 专项外币与final进度；范围有限 |
| exchange_rate_expense_snapshots.sql | FAIL（fixture） | 第30行join_code `FE000001/FE000002`违反8位数字约束，未到达业务断言 |
| phase2c_base_amount_normalization.sql | FAIL | 第230行zero debt base异常，C05 |
| phase3_deleted_expense_read_restore.sql | FAIL（旧契约） | 第203行restore_expense执行权已撤 |
| phase4_settlement_transfer.sql | FAIL | 第254行多Transfer/Expense FIFO断言；新永久分配与旧排序预期需逐条修订，不能伪称通过 |
| phase5_prepayment_extended.sql | FAIL | 第177行rebuild transfer_allocations exact断言；重建/反向抵消需进一步回归 |
| phase6_final_settlement.sql | FAIL（旧契约） | 第151行更改已有历史账单被财务锁拒绝 |
| phase7_finalization.sql | FAIL（旧契约） | restore相关断言/调用失效 |
| phase8_transfer_restore.sql | FAIL（旧契约） | 第111行restore_transfer执行权已撤 |
| phase9_fair_aa_final_settlement.sql | FAIL | 第243行负退款后plan断言失败，不能只当过时测试 |
| phase10_sub_activity_delete_restore.sql | FAIL | 第91行旧settlement cap前提失败，尚未证明后续生命周期测试通过 |
| phase12_multi_currency_allocation_invariants.sql | FAIL | 第207行微额JPY分配失败，C11 |

5个旧并发脚本为 phase3_debt_projection_concurrency、phase4_settlement_transfer_concurrency、phase5_prepayment_concurrency、phase6_final_settlement_concurrency、phase7_finalization_concurrency。它们使用dblink、硬编码 `dbname=postgres`，并有跨连接提交及旧式物理删除清理；直接跑会进入现有开发库且受不可变trigger阻止清理。因此本轮仅审阅，不宣称通过，也没有改写仓库测试。

另外在隔离库创建仅测试数据，以两个独立数据库会话同时向同一版本100余额各提交TARGETED80：一笔成功，一笔40001；事实1笔80、bilateral20、F从1到2。只证明这个并发场景，**不外推为refund/final/void全部组合并发已验证**。

### 9.2 审计探针

C01、C02、C03反向净抵、C04、C05、C06、C08微额完成、C09两类重试、C10均在临时库实际运行。C11由既有phase12复现。每个探针使用两个不同参与人、authenticated角色及虚构身份；普通探针在事务内回滚，并发探针只向独立临时库提交。

为了区分入口故障与算法故障，涉及负退款投影的探针使用当前仍开放的手工FX Expense入口，避免C01先拦截整个测试。这是定位方法，不是建议客户端退回不可信手工FX。

### 9.3 Android / 集成

执行 `gradlew.bat testDebugUnitTest --console=plain`，实际日志 `BUILD FAILED`：`ExpenseViewModelTest.kt:489` 参数类型不符（`() -> Unit`传给Boolean）及 `Unresolved reference 'it'`，失败在 `:app:compileDebugUnitTestKotlin`。**单元测试未运行完成**；不能将旧报告“已通过”转述为本轮结果。未修测试代码。

本轮未执行双设备、Auth网关、Storage上传、Realtime断线、在线ECB同步与远程环境验收；scripts/run-local-dual-account-*及相关runbook是已有验收入口，不是本轮成功证据。`BACKEND_INTEGRATION_READINESS.md`/README仍含Phase7冻结与恢复契约的过时段落，应从后续基线引用链中排除。

## 10. 人工确认清单（本轮停止点）

1. **文档演进是否认可**：TARGETED、多目标/部分还款、永久allocation、presentation-only编辑、公平AA、原币Debt拓扑、成员新增预存/执行final、外币预存原币返还，按当前实现纳入基线。
2. **已复现错误如何处置**：C01～C11不得被改写成正常业务；是否先修复并复测再冻结，或先将基线明确标为“已实现但存在以下限制/缺陷”。本轮不改业务实现。
3. **退款最终边界**：U02的多次、累计上限、可关联对象和原账单历史修改；当前没有这些约束，不能擅自发明。
4. **多币种/最终收尾决策**：U03关闭开关后的既有外币清偿；U04纯环路；C07真实FX字段口径；C08完成和汇总口径。
5. **历史/兼容边界**：是否保留手工Expense/旧预存/旧final入口；旧历史缺口如何标注；C10负资金源如何处理；U05跨调用人request重放语义。
6. **未落地旧设计**：U01子活动名单、large root用途、Unit备注/file/link是否删除旧承诺，或明确列为未实现。此处只需业务取舍，不自动启动新功能。
7. **验证门槛**：旧恢复测试需退役/重写，真正回归失败需修复，Android测试编译需恢复；完成当前回归和环境验证前，不把基线标“全部验收通过”。

**只有人工确认本报告后，才更新 BUSINESS_LOGIC.md，并执行反向审计、生成 BUSINESS_LOGIC_FINAL_REVIEW.md。当前未开始设计或实现 LLM/Business Logic Verification Workflow。**

## 附录 A：migration 扫描清单

下列文件按执行顺序列出；旧定义不自动代表当前行为，冲突以最后有效定义/权限为准。

| Migration（位于 supabase/migrations） | 审计关注点 |
|---|---|
| [20260830100421_backend_foundation_types.sql](../../supabase/migrations/20260830100421_backend_foundation_types.sql) | activity/unit enum、private schema |
| [20260830100423_profiles_and_auth.sql](../../supabase/migrations/20260830100423_profiles_and_auth.sql) | profile与Auth插入trigger |
| [20260830100424_activities_and_members.sql](../../supabase/migrations/20260830100424_activities_and_members.sql) | 活动、加入码、成员唯一性/FK |
| [20260830100426_ledger_units_and_participants.sql](../../supabase/migrations/20260830100426_ledger_units_and_participants.sql) | 单元/参与人/认领、稳定顺序、updated_at |
| [20260830100429_foundation_rls.sql](../../supabase/migrations/20260830100429_foundation_rls.sql) | 成员/Creator谓词、RLS、初始grant |
| [20260830105311_activity_lifecycle_rpc.sql](../../supabase/migrations/20260830105311_activity_lifecycle_rpc.sql) | 创建活动/根、加入、子活动、直接写收束 |
| [20260830115348_expense_core_schema.sql](../../supabase/migrations/20260830115348_expense_core_schema.sql) | Expense/Payment/Split原币/FX、FK、删除一致性 |
| [20260830115402_expense_core_rpc.sql](../../supabase/migrations/20260830115402_expense_core_rpc.sql) | 单事务子项守恒、退款引用、删除引用保护 |
| [20260830115418_expense_core_rls.sql](../../supabase/migrations/20260830115418_expense_core_rls.sql) | Expense/children成员读取 |
| [20260830151327_base_amount_normalization.sql](../../supabase/migrations/20260830151327_base_amount_normalization.sql) | base子项、守恒、舍入尾差 |
| [20260830191659_backend_debt_projection.sql](../../supabase/migrations/20260830191659_backend_debt_projection.sql) | 存储投影、复合FK、活动advisory锁、回填 |
| [20260831034645_backend_settlement_transfer.sql](../../supabase/migrations/20260831034645_backend_settlement_transfer.sql) | Transfer、allocation、F、actor/cap/void |
| [20260831055425_backend_prepayment.sql](../../supabase/migrations/20260831055425_backend_prepayment.sql) | components/账户/usage、actor、旧存返接口 |
| [20260831120000_phase5_fk_indexes.sql](../../supabase/migrations/20260831120000_phase5_fk_indexes.sql) | Phase5 FK索引，不改变金额规则 |
| [20260831160108_backend_final_settlement_archive.sql](../../supabase/migrations/20260831160108_backend_final_settlement_archive.sql) | final path/flow、archive、状态view、只读保护 |
| [20260901124212_backend_finalization_integration_readiness.sql](../../supabase/migrations/20260901124212_backend_finalization_integration_readiness.sql) | 管理、争议、审计、附件/Storage、Realtime、旧restore |
| [20260905151820_expense_deleted_read_restore.sql](../../supabase/migrations/20260905151820_expense_deleted_read_restore.sql) | 已删除Expense读取；不能据文件名认定现在可恢复 |
| [20260908063410_transfer_restore_contract.sql](../../supabase/migrations/20260908063410_transfer_restore_contract.sql) | 旧恢复对象与审计，后被撤权 |
| [20260908092201_allow_members_create_sub_activity.sql](../../supabase/migrations/20260908092201_allow_members_create_sub_activity.sql) | 子活动创建放开至Member |
| [20260910133739_fair_aa_base_allocation.sql](../../supabase/migrations/20260910133739_fair_aa_base_allocation.sql) | AA base余数逐人分配、修复重建 |
| [20260913112306_sub_activity_delete_restore.sql](../../supabase/migrations/20260913112306_sub_activity_delete_restore.sql) | sub lifecycle/审计/全投影重建 |
| [20260913112419_ecb_exchange_rate_expense_snapshots.sql](../../supabase/migrations/20260913112419_ecb_exchange_rate_expense_snapshots.sql) | ECB快照、同步、auto入口、STABLE行锁冲突 |
| [20260913120850_schedule_ecb_exchange_rate_sync.sql](../../supabase/migrations/20260913120850_schedule_ecb_exchange_rate_sync.sql) | 两个工作日Cron，Vault读取配置 |
| [20260913121250_fix_ecb_cron_net_http_post.sql](../../supabase/migrations/20260913121250_fix_ecb_cron_net_http_post.sql) | net.http_post修正与10秒timeout |
| [20260913123459_fix_exchange_rate_cache_update_where.sql](../../supabase/migrations/20260913123459_fix_exchange_rate_cache_update_where.sql) | 同步安全UPDATE谓词、事务缓存替换 |
| [20260918054229_profiles_avatar_style_presets.sql](../../supabase/migrations/20260918054229_profiles_avatar_style_presets.sql) | profile展示预设/列授权，不作账务权限依据 |
| [20260919094626_expense_icon_keys.sql](../../supabase/migrations/20260919094626_expense_icon_keys.sql) | icon白名单、保留旧重载、auto重载 |
| [20260919164707_multi_currency_settlement.sql](../../supabase/migrations/20260919164707_multi_currency_settlement.sql) | currency Debt/allocation/request、财务锁、旧FX入口仍在 |
| [20260920112458_fix_original_currency_debt_projection.sql](../../supabase/migrations/20260920112458_fix_original_currency_debt_projection.sql) | 原币匹配恢复，临时匹配表仅内部重建 |
| [20260920120259_fix_multi_currency_allocation_invariants.sql](../../supabase/migrations/20260920120259_fix_multi_currency_allocation_invariants.sql) | 原币拓扑/base配额、微额约束、零债务拒绝 |
| [20260920142845_multi_currency_prepayment_final_settlement_core.sql](../../supabase/migrations/20260920142845_multi_currency_prepayment_final_settlement_core.sql) | 账户币种、v2预存/final、双mode、views、request payload/result |
| [20260920142942_immutable_transfer_delete_restore_contract.sql](../../supabase/migrations/20260920142942_immutable_transfer_delete_restore_contract.sql) | source history、Transfer lifecycle、Expense锁、撤restore |
| [20260920151825_fix_transfer_source_expenses_indexes.sql](../../supabase/migrations/20260920151825_fix_transfer_source_expenses_indexes.sql) | 去冗余唯一索引，保留constraint身份 |
| [20260920152349_fix_prepayment_currency_priority.sql](../../supabase/migrations/20260920152349_fix_prepayment_currency_priority.sql) | 修旧截断唯一约束、同币预存优先、usage最终定义 |
| [20260921022101_allow_members_create_prepayment.sql](../../supabase/migrations/20260921022101_allow_members_create_prepayment.sql) | v2新增预存Member范围、禁behalf、重试顺序问题 |
| [20260921043414_expense_financial_lock_presentation_update.sql](../../supabase/migrations/20260921043414_expense_financial_lock_presentation_update.sql) | financial_locked、展示更新、两侧children保护 |
| [20260921051720_targeted_expense_repayment_contract.sql](../../supabase/migrations/20260921051720_targeted_expense_repayment_contract.sql) | 永久allocation、TARGETED全链、锁定debt保留、旧FIFO fallback |
| [20260922031227_fix_final_settlement_transfer_mode.sql](../../supabase/migrations/20260922031227_fix_final_settlement_transfer_mode.sql) | FINAL_SETTLEMENT mode写入、base模式纯外币返还、重试顺序 |
| [20260922072033_final_settlement_member_actor_gate.sql](../../supabase/migrations/20260922072033_final_settlement_member_actor_gate.sql) | 最终执行Member门槛的最后有效定义 |

## 附录 B：public RPC 精确签名与输出

本附录为catalog快照；SQL中的numeric精度以第2/5节及列约束为准（PostgreSQL函数identity不保留numeric typmod）。`authenticated可调用`不代表任意成员都满足函数内部权限。族编号对应第8节。禁用恢复与service-only接口也列出，避免把对象存在误认为产品可用。

### `add_transfer_dispute`（D1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
add_transfer_dispute(transfer_id uuid, participant_id uuid, note text DEFAULT NULL::text)
RETURNS TABLE(dispute_id uuid, created boolean)
```

### `archive_activity`（A9）

当前 Android 调用；authenticated EXECUTE：是。

```sql
archive_activity(p_activity_id uuid)
RETURNS TABLE(activity_id uuid, archived boolean, changed boolean, archived_at timestamp with time zone, total_debt numeric, total_prepayment numeric, completed boolean, has_unsettled boolean, warning text)
```

### `claim_exchange_rate_sync`（X2）

服务端 Edge 同步调用；authenticated EXECUTE：否。

```sql
claim_exchange_rate_sync(p_min_interval_seconds integer DEFAULT 7200)
RETURNS TABLE(claimed boolean, next_attempt_at timestamp with time zone)
```

### `claim_participant`（A6）

当前 Android 调用；authenticated EXECUTE：是。

```sql
claim_participant(activity_id uuid, participant_id uuid)
RETURNS TABLE(claim_id uuid, claimed_participant_id uuid, is_new boolean)
```

### `complete_attachment`（H1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
complete_attachment(attachment_id uuid)
RETURNS boolean
```

### `create_activity`（A1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
create_activity(name text, type activity_type, base_currency character DEFAULT 'CNY'::bpchar, multi_currency_enabled boolean DEFAULT false)
RETURNS TABLE(activity_id uuid, join_code text, activity_name text, activity_type activity_type, activity_base_currency character, activity_multi_currency_enabled boolean)
```

### `create_attachment`（H1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
create_attachment(activity_id uuid, ledger_unit_id uuid, expense_id uuid, filename text, mime_type text, size_bytes bigint)
RETURNS TABLE(attachment_id uuid, bucket text, path text, status text)
```

### `create_expense`（E1）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
create_expense(ledger_unit_id uuid, title text, original_amount numeric, original_currency character, fx_rate numeric, split_method expense_split_method, payments jsonb DEFAULT '[]'::jsonb, manual_splits jsonb DEFAULT '[]'::jsonb, aa_participant_ids uuid[] DEFAULT '{}'::uuid[], occurred_at timestamp with time zone DEFAULT now(), note text DEFAULT NULL::text, original_expense_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(expense_id uuid, base_amount numeric, version bigint)
```

### `create_expense`（E1）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
create_expense(ledger_unit_id uuid, title text, original_amount numeric, original_currency character, fx_rate numeric, split_method expense_split_method, payments jsonb, manual_splits jsonb, aa_participant_ids uuid[], occurred_at timestamp with time zone, note text, original_expense_id uuid, icon_key text)
RETURNS TABLE(expense_id uuid, base_amount numeric, version bigint)
```

### `create_expense_auto_rate`（E1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
create_expense_auto_rate(ledger_unit_id uuid, title text, original_amount numeric, original_currency character, split_method expense_split_method, payments jsonb DEFAULT '[]'::jsonb, manual_splits jsonb DEFAULT '[]'::jsonb, aa_participant_ids uuid[] DEFAULT '{}'::uuid[], occurred_at timestamp with time zone DEFAULT now(), note text DEFAULT NULL::text, original_expense_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(expense_id uuid, base_amount numeric, version bigint, fx_rate numeric, fx_rate_source text, fx_rate_observed_at timestamp with time zone)
```

### `create_expense_auto_rate`（E1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
create_expense_auto_rate(ledger_unit_id uuid, title text, original_amount numeric, original_currency character, split_method expense_split_method, payments jsonb, manual_splits jsonb, aa_participant_ids uuid[], occurred_at timestamp with time zone, note text, original_expense_id uuid, icon_key text)
RETURNS TABLE(expense_id uuid, base_amount numeric, version bigint, fx_rate numeric, fx_rate_source text, fx_rate_observed_at timestamp with time zone)
```

### `create_expense_repayment_v2`（T3）

当前 Android 调用；authenticated EXECUTE：是。

```sql
create_expense_repayment_v2(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, currency character, mode text DEFAULT 'FIFO'::text, target_expense_ids uuid[] DEFAULT NULL::uuid[], occurred_at timestamp with time zone DEFAULT now(), on_behalf_of_participant_id uuid DEFAULT NULL::uuid, expected_financial_version bigint DEFAULT NULL::bigint, request_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(transfer_id uuid, amount numeric, currency character, mode text, financial_version bigint)
```

### `create_final_settlement`（F3）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
create_final_settlement(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, occurred_at timestamp with time zone DEFAULT now(), on_behalf_of_participant_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(transfer_id uuid, amount numeric, currency character, financial_version bigint)
```

### `create_final_settlement_v2`（F2）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
create_final_settlement_v2(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, currency character, mode text, expected_financial_version bigint, request_id uuid, occurred_at timestamp with time zone DEFAULT now(), on_behalf_of_participant_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(transfer_id uuid, amount numeric, currency character, mode text, financial_version bigint)
```

### `create_participant`（A5）

当前 Android 调用；authenticated EXECUTE：是。

```sql
create_participant(activity_id uuid, name text, participant_order integer DEFAULT NULL::integer)
RETURNS TABLE(participant_id uuid, participant_name text, participant_order integer)
```

### `create_prepayment`（P4）

Android 受限兼容入口；authenticated EXECUTE：是。

```sql
create_prepayment(activity_id uuid, owner_participant_id uuid, custodian_participant_id uuid, amount numeric, occurred_at timestamp with time zone DEFAULT now(), on_behalf_of_participant_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(transfer_id uuid, settlement_amount numeric, prepayment_amount numeric, currency character, financial_version bigint)
```

### `create_prepayment_return`（P4）

Android 受限兼容入口；authenticated EXECUTE：是。

```sql
create_prepayment_return(activity_id uuid, owner_participant_id uuid, custodian_participant_id uuid, amount numeric, occurred_at timestamp with time zone DEFAULT now(), on_behalf_of_participant_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(transfer_id uuid, amount numeric, currency character, financial_version bigint)
```

### `create_prepayment_return_v2`（P3）

当前 Android 调用；authenticated EXECUTE：是。

```sql
create_prepayment_return_v2(activity_id uuid, owner_participant_id uuid, custodian_participant_id uuid, amount numeric, currency character, occurred_at timestamp with time zone DEFAULT now(), on_behalf_of_participant_id uuid DEFAULT NULL::uuid, expected_financial_version bigint DEFAULT NULL::bigint, request_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(transfer_id uuid, amount numeric, currency character, remaining_balance numeric, financial_version bigint)
```

### `create_prepayment_v2`（P2）

当前 Android 调用；authenticated EXECUTE：是。

```sql
create_prepayment_v2(activity_id uuid, owner_participant_id uuid, custodian_participant_id uuid, amount numeric, currency character, occurred_at timestamp with time zone DEFAULT now(), on_behalf_of_participant_id uuid DEFAULT NULL::uuid, expected_financial_version bigint DEFAULT NULL::bigint, request_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(transfer_id uuid, settlement_amount numeric, prepayment_amount numeric, new_balance numeric, currency character, financial_version bigint)
```

### `create_settlement_transfer`（T4）

Android 受限兼容入口；authenticated EXECUTE：是。

```sql
create_settlement_transfer(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, currency character, occurred_at timestamp with time zone, on_behalf_of_participant_id uuid, request_id uuid)
RETURNS TABLE(transfer_id uuid, amount numeric, currency character, financial_version bigint)
```

### `create_settlement_transfer`（T4）

Android 受限兼容入口；authenticated EXECUTE：是。

```sql
create_settlement_transfer(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, occurred_at timestamp with time zone DEFAULT now(), on_behalf_of_participant_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(transfer_id uuid, amount numeric, currency character, financial_version bigint)
```

### `create_sub_activity`（A3）

当前 Android 调用；authenticated EXECUTE：是。

```sql
create_sub_activity(activity_id uuid, name text)
RETURNS TABLE(parent_activity_id uuid, ledger_unit_id uuid, created_name text, created_type ledger_unit_type)
```

### `delete_activity`（A8）

当前 Android 调用；authenticated EXECUTE：是。

```sql
delete_activity(activity_id uuid)
RETURNS boolean
```

### `delete_attachment`（H1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
delete_attachment(attachment_id uuid)
RETURNS boolean
```

### `delete_expense`（E4）

当前 Android 调用；authenticated EXECUTE：是。

```sql
delete_expense(expense_id uuid)
RETURNS TABLE(deleted_expense_id uuid, deleted boolean, version bigint)
```

### `delete_participant`（A5）

当前 Android 调用；authenticated EXECUTE：是。

```sql
delete_participant(participant_id uuid)
RETURNS TABLE(participant_id uuid, deleted boolean)
```

### `delete_sub_activity`（A4）

当前 Android 调用；authenticated EXECUTE：是。

```sql
delete_sub_activity(sub_activity_id uuid)
RETURNS TABLE(sub_activity_id uuid, activity_id uuid, changed boolean, is_deleted boolean, financial_version bigint)
```

### `execute_final_settlement`（F3）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
execute_final_settlement(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, occurred_at timestamp with time zone DEFAULT now(), on_behalf_of_participant_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(transfer_id uuid, amount numeric, currency character, financial_version bigint)
```

### `execute_final_settlement_item`（F3）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
execute_final_settlement_item(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, occurred_at timestamp with time zone DEFAULT now(), on_behalf_of_participant_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(transfer_id uuid, amount numeric, currency character, financial_version bigint)
```

### `execute_final_settlement_v2`（F2）

当前 Android 调用；authenticated EXECUTE：是。

```sql
execute_final_settlement_v2(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, currency character, mode text, expected_financial_version bigint, request_id uuid, occurred_at timestamp with time zone DEFAULT now(), on_behalf_of_participant_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(transfer_id uuid, amount numeric, currency character, mode text, financial_version bigint)
```

### `get_exchange_rate`（X1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
get_exchange_rate(p_base_currency character, p_quote_currency character)
RETURNS TABLE(base_currency character, quote_currency character, rate numeric, observed_at timestamp with time zone, source text)
```

### `get_exchange_rate_sync_status`（X1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
get_exchange_rate_sync_status()
RETURNS TABLE(last_attempted_at timestamp with time zone, last_succeeded_at timestamp with time zone, last_ecb_observed_at timestamp with time zone, next_attempt_at timestamp with time zone, last_error_code text)
```

### `get_expense_repayment_progress`（T2）

当前 Android 调用；authenticated EXECUTE：是。

```sql
get_expense_repayment_progress(p_activity_id uuid, p_expense_id uuid)
RETURNS TABLE(expense_id uuid, debtor_participant_id uuid, creditor_participant_id uuid, debt_currency character, debt_original_amount numeric, debt_base_amount numeric, settled_original_amount numeric, settled_base_amount numeric, prepayment_original_amount numeric, prepayment_base_amount numeric, offset_original_amount numeric, offset_base_amount numeric, remaining_original_amount numeric, remaining_base_amount numeric, financial_version bigint)
```

### `get_final_settlement_plan`（F3）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
get_final_settlement_plan(activity_id uuid)
RETURNS TABLE(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, ordinary_amount numeric, prepayment_return_amount numeric, currency character, source_financial_version bigint, is_prepayment_return boolean)
```

### `get_final_settlement_plan_v2`（F1）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
get_final_settlement_plan_v2(p_activity_id uuid, p_mode text DEFAULT 'base_unified'::text)
RETURNS TABLE(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, ordinary_amount numeric, prepayment_return_amount numeric, currency character, mode text, path_currency character, source_financial_version bigint, is_prepayment_return boolean)
```

### `join_activity_by_code`（A2）

当前 Android 调用；authenticated EXECUTE：是。

```sql
join_activity_by_code(join_code text)
RETURNS TABLE(activity_id uuid, is_new boolean)
```

### `list_settlement_options`（T1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
list_settlement_options(p_activity_id uuid)
RETURNS TABLE(debtor_participant_id uuid, creditor_participant_id uuid, currency character, original_amount numeric, base_amount numeric, base_total numeric, financial_version bigint)
```

### `list_supported_exchange_currencies`（X1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
list_supported_exchange_currencies()
RETURNS TABLE(currency_code character, display_name text, observed_at timestamp with time zone)
```

### `list_transfer_expense_candidates`（T2）

当前 Android 调用；authenticated EXECUTE：是。

```sql
list_transfer_expense_candidates(activity_id uuid, from_participant_id uuid, to_participant_id uuid, currency character)
RETURNS TABLE(expense_id uuid, ledger_unit_id uuid, ledger_unit_name text, title text, occurred_at timestamp with time zone, debtor_participant_id uuid, creditor_participant_id uuid, debt_currency character, debt_original_amount numeric, debt_base_amount numeric, offset_original_amount numeric, settled_original_amount numeric, prepayment_original_amount numeric, remaining_original_amount numeric, remaining_base_amount numeric, payment_currency_amount numeric, financial_version bigint)
```

### `preview_activity_settlement`（F3）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
preview_activity_settlement(activity_id uuid)
RETURNS TABLE(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, ordinary_amount numeric, prepayment_return_amount numeric, currency character, source_financial_version bigint, is_prepayment_return boolean)
```

### `preview_activity_settlement_v2`（F1）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
preview_activity_settlement_v2(p_activity_id uuid, p_mode text DEFAULT 'base_unified'::text)
RETURNS TABLE(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, ordinary_amount numeric, prepayment_return_amount numeric, currency character, mode text, path_currency character, source_financial_version bigint, is_prepayment_return boolean)
```

### `preview_expense_repayment`（T2）

当前 Android 调用；authenticated EXECUTE：是。

```sql
preview_expense_repayment(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, currency character, mode text, target_expense_ids uuid[], expected_financial_version bigint)
RETURNS TABLE(expense_id uuid, ledger_unit_id uuid, allocation_mode text, payment_currency character, payment_amount numeric, original_currency character, original_amount numeric, base_amount numeric, fx_rate numeric, remaining_original_amount numeric, remaining_base_amount numeric, source_financial_version bigint)
```

### `preview_final_settlement`（F3）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
preview_final_settlement(activity_id uuid)
RETURNS TABLE(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, ordinary_amount numeric, prepayment_return_amount numeric, currency character, source_financial_version bigint, is_prepayment_return boolean)
```

### `preview_final_settlement_v2`（F1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
preview_final_settlement_v2(p_activity_id uuid, p_mode text DEFAULT 'base_unified'::text)
RETURNS TABLE(activity_id uuid, from_participant_id uuid, to_participant_id uuid, amount numeric, ordinary_amount numeric, prepayment_return_amount numeric, currency character, mode text, path_currency character, source_financial_version bigint, is_prepayment_return boolean)
```

### `preview_prepayment`（P1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
preview_prepayment(p_activity_id uuid, p_owner_participant_id uuid, p_custodian_participant_id uuid, p_amount numeric, p_currency character)
RETURNS TABLE(activity_id uuid, owner_participant_id uuid, custodian_participant_id uuid, amount numeric, settlement_amount numeric, prepayment_amount numeric, new_balance numeric, currency character, financial_version bigint)
```

### `record_exchange_rate_sync_failure`（X2）

服务端 Edge 同步调用；authenticated EXECUTE：否。

```sql
record_exchange_rate_sync_failure(p_error_code text)
RETURNS boolean
```

### `remove_activity_member`（A8）

当前 Android 调用；authenticated EXECUTE：是。

```sql
remove_activity_member(activity_id uuid, user_id uuid)
RETURNS boolean
```

### `remove_transfer_dispute`（D1）

当前 Android 调用；authenticated EXECUTE：是。

```sql
remove_transfer_dispute(dispute_id uuid)
RETURNS boolean
```

### `replace_exchange_rate_cache`（X2）

服务端 Edge 同步调用；authenticated EXECUTE：否。

```sql
replace_exchange_rate_cache(p_ecb_date date, p_rates jsonb)
RETURNS TABLE(currency_count integer, pair_count integer, observed_at timestamp with time zone)
```

### `restore_expense`（R0）

已撤销 API 执行权；authenticated EXECUTE：否。

```sql
restore_expense(expense_id uuid)
RETURNS TABLE(restored_expense_id uuid, restored boolean, version bigint)
```

### `restore_sub_activity`（A4）

当前 Android 调用；authenticated EXECUTE：是。

```sql
restore_sub_activity(sub_activity_id uuid)
RETURNS TABLE(sub_activity_id uuid, activity_id uuid, changed boolean, is_deleted boolean, financial_version bigint)
```

### `restore_transfer`（R0）

已撤销 API 执行权；authenticated EXECUTE：否。

```sql
restore_transfer(transfer_id uuid, restore_reason text)
RETURNS TABLE(transfer_id uuid, restored boolean, financial_version bigint)
```

### `transfer_activity_creator`（A8）

当前 Android 调用；authenticated EXECUTE：是。

```sql
transfer_activity_creator(activity_id uuid, new_creator_user_id uuid)
RETURNS uuid
```

### `unarchive_activity`（A9）

当前 Android 调用；authenticated EXECUTE：是。

```sql
unarchive_activity(p_activity_id uuid)
RETURNS TABLE(activity_id uuid, archived boolean, changed boolean, archived_at timestamp with time zone, total_debt numeric, total_prepayment numeric, completed boolean, has_unsettled boolean, warning text)
```

### `unclaim_participant`（A6）

当前 Android 调用；authenticated EXECUTE：是。

```sql
unclaim_participant(activity_id uuid)
RETURNS boolean
```

### `update_activity_settings`（A7）

当前 Android 调用；authenticated EXECUTE：是。

```sql
update_activity_settings(activity_id uuid, name text, base_currency character, multi_currency_enabled boolean)
RETURNS TABLE(activity_id uuid, activity_name text, activity_base_currency character, activity_multi_currency_enabled boolean)
```

### `update_expense`（E2）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
update_expense(expense_id uuid, ledger_unit_id uuid, title text, original_amount numeric, original_currency character, fx_rate numeric, split_method expense_split_method, payments jsonb DEFAULT '[]'::jsonb, manual_splits jsonb DEFAULT '[]'::jsonb, aa_participant_ids uuid[] DEFAULT '{}'::uuid[], occurred_at timestamp with time zone DEFAULT now(), note text DEFAULT NULL::text, original_expense_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(updated_expense_id uuid, base_amount numeric, version bigint)
```

### `update_expense`（E2）

保留公开入口/重载或别名；当前 Android 无直接调用；authenticated EXECUTE：是。

```sql
update_expense(expense_id uuid, ledger_unit_id uuid, title text, original_amount numeric, original_currency character, fx_rate numeric, split_method expense_split_method, payments jsonb, manual_splits jsonb, aa_participant_ids uuid[], occurred_at timestamp with time zone, note text, original_expense_id uuid, icon_key text)
RETURNS TABLE(updated_expense_id uuid, base_amount numeric, version bigint)
```

### `update_expense_auto_rate`（E2）

当前 Android 调用；authenticated EXECUTE：是。

```sql
update_expense_auto_rate(expense_id uuid, ledger_unit_id uuid, title text, original_amount numeric, original_currency character, split_method expense_split_method, payments jsonb DEFAULT '[]'::jsonb, manual_splits jsonb DEFAULT '[]'::jsonb, aa_participant_ids uuid[] DEFAULT '{}'::uuid[], occurred_at timestamp with time zone DEFAULT now(), note text DEFAULT NULL::text, original_expense_id uuid DEFAULT NULL::uuid)
RETURNS TABLE(updated_expense_id uuid, base_amount numeric, version bigint, fx_rate numeric, fx_rate_source text, fx_rate_observed_at timestamp with time zone)
```

### `update_expense_auto_rate`（E2）

当前 Android 调用；authenticated EXECUTE：是。

```sql
update_expense_auto_rate(expense_id uuid, ledger_unit_id uuid, title text, original_amount numeric, original_currency character, split_method expense_split_method, payments jsonb, manual_splits jsonb, aa_participant_ids uuid[], occurred_at timestamp with time zone, note text, original_expense_id uuid, icon_key text)
RETURNS TABLE(updated_expense_id uuid, base_amount numeric, version bigint, fx_rate numeric, fx_rate_source text, fx_rate_observed_at timestamp with time zone)
```

### `update_expense_presentation`（E3）

当前 Android 调用；authenticated EXECUTE：是。

```sql
update_expense_presentation(expense_id uuid, title text, note text DEFAULT NULL::text, icon_key text DEFAULT 'money'::text, expected_version bigint DEFAULT NULL::bigint)
RETURNS TABLE(updated_expense_id uuid, version bigint, financial_version bigint, financial_locked boolean)
```

### `void_prepayment_transfer`（T5）

当前 Android 调用；authenticated EXECUTE：是。

```sql
void_prepayment_transfer(transfer_id uuid, void_reason text)
RETURNS TABLE(transfer_id uuid, voided boolean, financial_version bigint)
```

### `void_settlement_transfer`（T5）

当前 Android 调用；authenticated EXECUTE：是。

```sql
void_settlement_transfer(transfer_id uuid, void_reason text)
RETURNS TABLE(transfer_id uuid, voided boolean, financial_version bigint)
```
