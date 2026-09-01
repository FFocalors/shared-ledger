# 多人活动记账软件：业务逻辑规格

> 文档状态：业务基线，可进入数据库与 Android 页面设计  
> 适用范围：MVP 及第一阶段正式版本  
> 产品定位：熟人之间的多人活动记账与结算工具，不是银行债务或专业跨境清算系统

## 1. 文档目标

本文档统一记录项目当前已经确认的业务逻辑。后续数据库结构、服务端 RPC、Android 页面、状态展示和测试用例均应以本文档为依据。

设计遵循以下原则：

1. 优先覆盖聚餐、旅行等熟人共同消费的常见场景。
2. 准确保存消费、付款、分摊和真实转账，不追求银行级资金追溯。
3. 原始账务事实与计算结果分离，计算结果可以重建，真实资金记录不能被系统偷偷修改。
4. 日常使用尽量简单，复杂能力只在大型活动最终收尾时出现。
5. 特殊情况只做最小边界收束，不为低频场景引入复杂审批和状态机。

---

## 2. 产品范围

### 2.1 核心能力

- 创建普通活动或大型活动。
- 为活动添加参与人。
- 记录多笔消费。
- 一笔消费支持一个或多个付款人。
- 支持 AA 分摊和手动分摊。
- 支持外币消费并固化当时汇率。
- 自动计算每笔消费产生的债务。
- 支持普通转账、部分还款和多次还款。
- 支持大型活动级预存、预存抵扣和预存返还。
- 支持退款、逻辑删除和账务重新计算。
- 支持大型活动最终结算方案。
- 支持多人账号加入、协作编辑、审计和简单争议标记。
- 支持备注、账单图片和直接拍照。
- 自动判断活动是否完成，用户手动归档。

### 2.2 明确不做

- 不做传统个人收支统计和资产管理。
- 不建立跨活动复用的全局联系人池。
- 日常账务不做三人及以上的债务路径优化。
- 普通活动不提供优化转账方案。
- 不支持外币转账、外币预存或外币结算。
- 不计算汇兑损益。
- 不提供 LedgerUnit 级独立预存。
- 不提供 Owner/Admin/Member 三级角色，只保留 Creator/Member。
- 不提供复杂转账审批或多阶段争议处理。
- 不自动归档活动。
- 不允许用户手动强制标记活动完成。
- 不物理删除核心账务数据。

---

## 3. 核心术语

| 术语 | 含义 |
|---|---|
| User | 真实登录 App 的账号。 |
| Activity | 顶层活动，分为普通活动和大型活动。 |
| LedgerUnit | 账目单元。普通活动有一个根单元；大型活动有根单元和多个子活动单元。 |
| Participant | 活动账本中的一个参与人，可以没有账号。 |
| ActivityMember | 某个 User 对 Activity 的访问关系和角色。 |
| ParticipantClaim | User 对 Participant 的认领关系。 |
| Expense | 一笔消费或负消费（退款）。 |
| Payment | Expense 中谁实际付款、付了多少。 |
| Split | Expense 中谁应该承担、承担多少。 |
| ExpenseDebt | 一笔 Expense 独立生成的有向债务结果。 |
| BilateralDebt | 同一对参与人完成双边抵消后的当前净债务。 |
| Transfer | 参与人之间被用户确认已经真实发生的资金移动。 |
| TransferAllocation | 普通 Transfer 具体冲抵了哪些债务。 |
| Prepayment | owner 提前交给 custodian 保管的活动资金。 |
| PrepaymentUsage | 预存余额具体抵扣了哪些消费债务。 |
| Final Settlement | 大型活动收尾时，根据全部当前未结账务生成的转账建议。 |
| Dispute | 对 Transfer 的争议标记，不直接改变余额。 |

---

## 4. 活动模型

### 4.1 普通活动

适用于聚餐、唱歌、桌游、短途出行等单次场景。

结构：

```text
普通 Activity
└─ 根 LedgerUnit
   └─ 多笔 Expense
```

创建普通活动时手动添加本次参与人，不复用其他活动的 Participant。

### 4.2 大型活动

适用于旅行等包含多个消费阶段的长周期场景。

结构：

```text
大型 Activity
├─ 根 LedgerUnit
│  └─ 大型活动级退款或调整
├─ 子活动 LedgerUnit：早餐
│  └─ 多笔 Expense
├─ 子活动 LedgerUnit：门票
│  └─ 多笔 Expense
└─ 子活动 LedgerUnit：住宿
   └─ 多笔 Expense
```

大型活动创建时建立本次活动的参与人总名单。每个子活动只能从总名单中勾选实际参与者。

### 4.3 根账目单元

根 LedgerUnit 是内部统一结构：

- 普通活动的全部消费进入根单元。
- 大型活动的普通消费进入子活动。
- 不属于特定子活动的大型活动级退款或调整进入大型活动根单元。

这样 Expense 始终归属于一个 LedgerUnit，不需要同时维护两种归属方式。

---

## 5. 账号、成员与参与人

### 5.1 User 与 Participant 分离

Participant 是账本中的人，User 是真实账号。创建者可以先建立“张三”“李四”等 Participant，即使对方尚未安装 App。

对方以后加入活动时，可以认领已有 Participant，而不是创建重复身份。

### 5.2 加入活动

- Activity 内部使用 UUID 主键。
- 对用户提供唯一的 8 位数字加入码。
- 名单未锁定时，加入者可以创建新的 Participant 或认领已有 Participant。
- 名单锁定后，只能认领尚未绑定 User 的 Participant。

唯一约束：

```text
一个 User 在一个 Activity 最多认领一个 Participant
一个 Participant 最多绑定一个 User
```

### 5.3 参与人锁定

- 普通活动：创建第一笔正式 Expense 后锁定参与人名单。
- 大型活动：创建第一个子活动后锁定参与人总名单。
- 锁定后不允许新增或删除 Participant。
- 锁定不影响 User 认领已有 Participant。

### 5.4 角色

只保留两种角色：

```text
Creator
Member
```

#### Member 可以

- 查看全部活动账目。
- 新增 Expense。
- 修改其他成员录入的 Expense。
- 逻辑删除或恢复 Expense。
- 以自己的 Participant 身份使用转账或收款。
- 作废自己录入的 Transfer 或 Prepayment。
- 对与自己有关的 Transfer 添加争议标记。
- 名单未锁定时新增 Participant。
- 认领 Participant。

#### Creator 额外可以

- 修改 Activity 基本设置。
- 管理 Participant 和 ActivityMember。
- 代表未注册 Participant 代记 Transfer。
- 作废任意成员录入的 Transfer 或 Prepayment。
- 处理活动级管理操作。
- 归档、取消归档和逻辑删除 Activity。
- 将 Creator 身份转移给另一个 Member。

Creator 代记资金时必须保存：

```text
recorded_by
on_behalf_of_participant_id
```

移除 Member 只撤销该 User 的访问权，不删除 Participant 和历史账务。

---

## 6. 币种与金额精度

### 6.1 基准币

每个 Activity 只有一个 `base_currency`，默认 CNY。

- 普通活动和大型活动均使用 Activity 级基准币。
- 大型活动的所有子活动共用同一个基准币。
- 创建首笔资金记录后锁定 `base_currency`。

### 6.2 外币消费

只有用户主动开启多币种后，才显示币种和汇率相关字段。

每笔外币 Expense 独立保存：

```text
original_amount
currency
exchange_rate
base_amount
```

计算：

```text
base_amount = round(original_amount × exchange_rate, 1)
```

历史 Expense 固化自己的汇率。以后汇率变化不会修改旧账。

### 6.3 汇率缓存

- App 在线启动时刷新汇率缓存。
- 离线时使用最近一次成功缓存的汇率。
- 创建 Expense 时把实际采用的汇率复制为该笔账的快照。

### 6.4 金额精度

所有基准币账务金额保存前统一四舍五入到小数点后 1 位：

- Expense.base_amount
- Payment.base_amount
- Split.base_amount
- ExpenseDebt.amount
- Transfer.amount
- Prepayment.amount
- PrepaymentUsage.amount

产品接受少量舍入误差，不追求分级完全精确。

### 6.5 同一 Expense 的币种约束

- 同一 Expense 下的所有 Payment 使用该 Expense 的原币币种。
- Split 也以该 Expense 的币种录入或展示。
- 系统转换为基准币后再参与债务计算。
- 使用其他币种向付款人还钱属于 Transfer，不属于原 Expense 的 Payment。
- 所有 Transfer、Prepayment 和最终结算只使用 Activity.base_currency。

当一笔 Expense 包含多条 Payment 或 Split 时，各明细折算并保留 1 位小数后可能产生尾差。系统按固定顺序把尾差计入最后一条明细，确保：

```text
Σ Payment.base_amount = Expense.base_amount
Σ Split.base_amount = Expense.base_amount
```

---

## 7. Expense、Payment 与 Split

### 7.1 三者必须分离

```text
Expense：发生了什么消费、总额是多少
Payment：谁实际支付了多少钱
Split：谁最终应该承担多少钱
```

付款人与承担人是两个不同维度。

例如：

```text
Expense：300.0
Payment：A 200.0，B 100.0
Split：A 80.0，B 100.0，C 120.0
```

### 7.2 金额守恒

保存 Expense 时必须满足：

```text
Σ Payment.base_amount = Expense.base_amount
Σ Split.base_amount = Expense.base_amount
```

Expense、Payment、Split 必须在一次服务端事务中整体保存，不能出现只更新总额但分摊尚未更新的中间状态。

### 7.3 AA 分摊

- 默认对本笔 Expense 的参与人均摊。
- 最终基准币金额保留 1 位小数。
- 舍入尾差由固定排序中的最后一名参与人吸收。
- 必须保证 Split 合计等于 Expense.base_amount。

例如：

```text
100.0 ÷ 3
→ 33.3、33.3、33.4
```

### 7.4 手动分摊

用户直接填写每个人承担的金额。

如果合计不等于 Expense 总额，保存前提供：

1. 返回修改每个人金额；
2. 以当前分摊合计修改 Expense 总额，并同步重新校验 Payment 合计。

### 7.5 每笔消费的参与人

每笔 Expense 可以只选择 LedgerUnit 中的部分 Participant。大型活动中并非每一笔消费都默认由所有人参加。

---

## 8. 日常债务生成

### 8.1 每笔 Expense 独立计算

不直接使用整个活动的总净余额重新撮合债权人和债务人。

对某笔 Expense 中的每个人计算：

```text
个人净额 = Payment.base_amount - Split.base_amount
```

- 净额大于 0：该参与人在本笔消费中应收。
- 净额小于 0：该参与人在本笔消费中应付。
- 净额等于 0：本笔消费中无需结算。

### 8.2 确定性撮合

存在多个应收方和应付方时，双方都按以下顺序排列：

```text
participant_order ASC
participant_id ASC
```

然后依次撮合，直到本笔 Expense 的应收和应付全部分配完成。

例如：

```text
A 应收 150.0
B 应收 50.0
C 应付 120.0
D 应付 80.0
```

固定生成：

```text
C → A 120.0
D → A 30.0
D → B 50.0
```

同一笔数据无论重新计算多少次，都必须得到相同结果。

### 8.3 双边抵消

不同 Expense 之间，只允许同一对人的反向债务互相抵消。

```text
B → A 100.0
A → B 40.0

当前展示：B → A 60.0
```

不允许日常三方路径自动优化：

```text
B → A 50.0
C → B 50.0
A → C 50.0
```

仍然保留三组债务，不自动归零。

### 8.4 Debt 的性质

ExpenseDebt、BilateralDebt 和参与人余额都是可重建的计算结果，不是唯一原始账务事实。

系统不应通过直接编辑 Debt 来修改账目。需要调整时，应修改 Expense、Payment、Split、Transfer 或 Prepayment 等来源数据。

---

## 9. 普通转账与收款

### 9.1 页面入口

普通活动、大型活动和子活动页面底部均提供：

```text
转账 | 收款
```

两者只是操作视角不同，底层统一生成 Transfer。

### 9.2 转账

当前用户绑定的 Participant 固定为付款方，用户选择收款方。

候选列表只显示当前确实存在同方向净债务的人。

### 9.3 收款

当前用户绑定的 Participant 固定为收款方，用户选择付款方。

底层仍然生成：

```text
Transfer.from = 付款方
Transfer.to = 收款方
```

### 9.4 普通 Transfer 约束

`Transfer.type = settlement` 时必须满足：

```text
付款方当前直接欠收款方
0 < amount ≤ 当前同方向双边净债务
currency = Activity.base_currency
```

用户可以部分还款，也可以分多次还款。

金额上限必须由服务端在写入事务内重新计算，不能只信任客户端显示。

### 9.5 冲抵顺序

普通 Transfer 对同一方向的多笔债务按以下顺序冲抵：

```text
Expense.occurred_at ASC
Expense.created_at ASC
Expense.id ASC
```

系统保存 TransferAllocation，用于解释一笔 Transfer 分别结清了哪些 ExpenseDebt。

### 9.6 Transfer 不可编辑

Transfer 表示用户确认已经真实发生的资金移动。

- 创建后不能修改金额、付款人、收款人、类型或发生时间。
- 录错时作废原 Transfer，再创建正确记录。
- 作废是逻辑作废，原记录继续保留在历史和审计中。
- Member 只能作废自己录入的 Transfer。
- Creator 可以作废任意 Transfer。

---

## 10. Transfer 类型

Transfer.type 固定为：

```text
settlement
prepayment
prepayment_return
final_settlement
```

| 类型 | 含义 | 是否要求付款方直接欠收款方 |
|---|---|---|
| settlement | 普通还款或收款 | 是 |
| prepayment | owner 向 custodian 增加活动预存 | 否，但会先偿还同方向当前债务 |
| prepayment_return | custodian 返还 owner 的剩余预存 | 否，受可用预存余额限制 |
| final_settlement | 执行大型活动当前最终结算建议 | 否，但必须匹配服务端当前方案 |

一笔实际 Transfer 可以通过 TransferComponent 解释多个同方向用途，例如：

```text
A → B 实际支付 500.0
├─ 普通债务结算 200.0
└─ 预存返还 300.0
```

---

## 11. 预存

### 11.1 作用域

预存账户由以下三元组唯一确定：

```text
Activity + owner + custodian
```

- 普通 Activity 可以使用 Activity 级预存。
- 大型 Activity 的预存跨全部子活动使用。
- MVP 不提供 LedgerUnit 级独立预存。
- 预存和预存返还只使用 Activity.base_currency。

### 11.2 正式规则

1. 预存余额只属于 `owner → custodian` 这一对关系。
2. 当前出现 `owner → custodian` 的双边净债务时，优先使用现有预存抵扣，剩余才形成普通可结算债务。
3. 创建新的预存时，如果当前已经存在 `owner → custodian` 的未结净债务，则先偿还当前债务，剩余才进入预存余额。
4. 历史重算只重新计算 PrepaymentUsage，不修改任何真实普通 Transfer；预存多余部分回到预存余额，普通 Transfer 多付部分形成反向债务。

### 11.3 当前净债务

预存抵扣的对象是完成双边抵消后的：

```text
owner → custodian 当前净债务
```

不能抵扣：

- `custodian → owner` 的反向债务；
- `owner → 第三方` 的债务；
- 其他 Activity 的债务。

允许以下两种关系同时存在：

```text
B 在 A 处有预存余额
A 同时欠 B 普通债务
```

两者不自动抵消。

### 11.4 新增预存

例如：

```text
B 当前欠 A：300.0
B 向 A 新增预存：1000.0
```

结果：

```text
偿还当前债务：300.0
新增预存余额：700.0
```

确认前 UI 必须明确展示这两个部分。

### 11.5 消费抵扣

如果 A 是 custodian，并支付了包含 B 应承担部分的 Expense：

```text
B 应向 A 承担 500.0
B 在 A 处有预存 1000.0
```

结果：

```text
PrepaymentUsage：500.0
剩余预存：500.0
普通 B → A 债务：0
```

### 11.6 预存不足

```text
B 应向 A 承担 300.0
B 在 A 处只剩预存 100.0
```

结果：

```text
使用预存：100.0
预存余额：0
形成 B → A 普通债务：200.0
```

### 11.7 预存返还

- 支持部分返还和全部返还。
- `prepayment_return.amount` 不得超过当前可用预存余额。
- 返还后减少对应 Activity、owner、custodian 的预存余额。
- 预存返还创建后不可编辑，只能按 Transfer 规则作废重录。

### 11.8 PrepaymentUsage

PrepaymentUsage 用于解释：

> 这部分预存具体抵扣了哪一笔 ExpenseDebt。

它是可重建结果，不代表额外发生了一笔资金转账，也不会修改普通 Transfer。

---

## 12. 退款

### 12.1 退款是负消费

退款不建立独立账务世界，而是保存为：

```text
Expense.base_amount < 0
```

退款仍然记录：

- 实际收到退款的人；
- 各 Participant 应获得的退款份额；
- 原币、汇率和基准币金额；
- 可选关联的原 Expense。

### 12.2 独立退款

不关联原 Expense 时，完全按照负 Expense 参与 Payment、Split 和 Debt 计算。

### 12.3 关联退款

关联原 Expense 时：

1. 优先恢复该 Expense 曾经实际消耗的 PrepaymentUsage；
2. 累计恢复金额不得超过原 Expense 对该 Participant 的累计 PrepaymentUsage；
3. 超出可恢复预存的部分继续按负 Expense 生成当前余额；
4. 不修改任何真实普通 Transfer。

例如：

```text
原 Expense 使用 B 的预存：300.0
B 当前剩余预存：700.0
关联退款中 B 应获得：100.0
```

结果：

```text
该 Expense 的 PrepaymentUsage：300.0 → 200.0
B 的预存余额：700.0 → 800.0
```

---

## 13. 大型活动最终结算

正式业务定义：

> 大型活动最终结算根据当前全部未结账务生成确定性的优化转账方案，尽量减少不必要的中间转账，但不承诺任意复杂债务图上的数学全局最少付款笔数。

### 13.1 使用范围

最终结算只在大型 Activity 提供，面向活动准备收尾时使用。

计算范围固定为：

```text
大型 Activity 中全部当前未结清的根单元和子活动账务
```

用户不能只选择部分子活动参与最终结算。

### 13.2 与日常债务分离

最终结算方案：

- 只是当前账务快照下的付款建议；
- 不修改原始 ExpenseDebt；
- 不因为方案生成就视为已付款；
- 只有用户确认真实付款并成功写入 `final_settlement` Transfer 后才改变余额。

### 13.3 优化转账方案

最终结算可以根据大型 Activity 的全部普通未结余额进行跨人净额优化，生成确定性的推荐转账方案。

例如：

```text
早餐：A → B 100.0
门票：B → C 100.0
```

日常债务仍为：

```text
A 欠 B 100.0
B 欠 C 100.0
```

最终结算建议可以为：

```text
A → C 100.0
```

### 13.4 预存返还

最终结算中：

1. 普通未结债务参与优化转账计算；
2. 预存返还保持 `custodian → owner` 的实际方向；
3. 普通结算建议和预存返还方向相同时，可以合并为一笔实际付款并保存不同 TransferComponent；
4. 方向相反时不自动抵消。

### 13.5 final_settlement Transfer

`Transfer.type = final_settlement`：

- 不受“付款方必须直接欠收款方”的普通 Transfer 限制；
- 只能按照当前大型 Activity 的最终结算方案执行；
- 写入时由服务端 RPC 重新计算当前方案；
- 付款方、收款方和金额必须匹配当前方案项；
- 不能由客户端任意创建没有方案支持的 final_settlement。

服务端同时保存该笔 final_settlement 对底层债务的结清路径。例如 `A → C 100.0` 可以解释为同时结清 `A → B 100.0` 和 `B → C 100.0`。该路径只用于更新子活动状态和解释结算结果，不会改写原始 ExpenseDebt。

final_settlement 的路径分配与普通 TransferAllocation 不同：同一笔实际金额可以沿一条债务路径同时结清多段等额债务，因此不能要求“所有路径债务金额之和等于 Transfer.amount”。

### 13.6 方案更新

不为 MVP 建立复杂的长期结算会话。

```text
用户打开最终结算
→ 服务端按当前数据即时生成方案
→ 用户记录一笔真实付款
→ 该 Transfer 成为永久事实
→ 页面重新计算剩余方案
```

如果期间 Expense、普通 Transfer 或预存发生变化，直接重新计算当前方案。未执行建议不是账务事实，无需保留。

---

## 14. 争议

争议只用于提示某位成员不认可一条 Transfer。

最小字段：

```text
is_disputed
disputed_by
dispute_note
disputed_at
```

争议不会：

- 撤销 Transfer；
- 改变当前余额；
- 改变 TransferAllocation；
- 恢复已结债务；
- 自动阻止归档或普通记账。

界面应明显显示：

```text
金额已结清 · 存在转账争议
```

最终处理方式只有：

1. 保留原 Transfer，并移除争议标记；
2. 按权限作废原 Transfer，再根据需要创建正确记录。

不建立审批流、仲裁状态机或资金冻结机制。

---

## 15. 历史修改与重新计算

允许在发生 Transfer 后继续修改或逻辑删除历史 Expense。

最小处理原则：

```text
Expense 修改、删除或恢复
→ 重新计算当前 ExpenseDebt
→ 重新计算双边净债务
→ 重新计算 TransferAllocation
→ 重新计算 PrepaymentUsage
→ 重新计算余额和活动状态
```

真实发生的 Transfer 和 Prepayment 记录保持不变。

可能结果：

- 原本已结清的债务重新出现；
- 预存多余部分回到预存余额；
- 普通 Transfer 多付部分形成反向债务；
- Activity 从 completed 自动回到 active。

界面只需提示：

> 历史账目已修改，当前结算结果已更新。

不提供银行级事件回放界面或复杂人工调账流程。

---

## 16. 逻辑删除与作废

### 16.1 Expense 等业务数据

核心业务数据采用逻辑删除：

```text
is_deleted
deleted_at
deleted_by
```

逻辑删除后：

- 不参与当前账务计算；
- 原记录继续保留；
- 恢复后重新参与计算。

### 16.2 Transfer 与 Prepayment

资金记录不直接删除，使用作废语义：

```text
is_voided
voided_at
voided_by
void_reason
```

作废后不参与当前余额，但历史记录仍可查看。

### 16.3 Activity 删除

- 只有 Creator 可以逻辑删除 Activity。
- 删除前显示确认提示。
- Participant、Expense、Transfer 等数据随 Activity 保留，不物理清除。
- MVP 不设计复杂的成员投票和删除审批。

---

## 17. 完成与归档

### 17.1 自动完成

Activity 或 LedgerUnit 的账务完成条件：

```text
全部当前普通债务 = 0
且相关预存余额 = 0
```

大型 Activity 需要检查：

- 根 LedgerUnit；
- 全部子活动；
- 普通 Transfer；
- final_settlement Transfer；
- 全部 Activity 级预存及返还。

### 17.2 completed 不是锁定状态

- `completed` 是自动计算结果。
- 用户不能手动强制完成。
- completed 后仍可继续记账。
- 新增或修改账务导致余额不再为零时，自动回到 active。

### 17.3 归档

- 用户手动执行归档。
- 已完成 Activity 可以直接归档。
- 未完成 Activity 也可以归档，但必须显示未结债务和未返还预存提示。
- 存在争议时显示额外提醒，但不禁止归档。
- 归档后整个 Activity 只读。
- 大型活动的子活动不单独归档。
- Creator 可以取消归档，恢复编辑并重新计算状态。

---

## 18. 多人协作与并发

### 18.1 普通编辑冲突

Expense 等协作编辑采用 Last Write Wins：

```text
最后成功提交到服务端的版本生效
```

每条可编辑记录保存：

```text
created_by
updated_by
updated_at
version
```

同时写入简要 audit_logs，便于查看谁在何时做了修改。

MVP 不提供版本对比和历史版本恢复 UI。

### 18.2 资金并发不使用 LWW

LWW 不用于解决 Transfer、Prepayment 等资金并发超额问题。

所有会改变资金余额的写操作必须通过服务端 RPC，在一个数据库事务内执行：

```text
校验身份与权限
→ 读取并锁定当前活动账务状态
→ 重新计算当前金额与上限
→ 写入原始事实
→ 重建受影响投影
→ financial_version + 1
→ 提交事务
```

适用操作包括：

- 创建、修改、删除或恢复 Expense；
- 创建或作废 settlement Transfer；
- 创建或作废 Prepayment；
- 创建或作废 PrepaymentReturn；
- 创建 final_settlement Transfer；
- 归档状态下涉及资金的任何写入校验。

客户端校验仅用于改善交互，服务端校验才是最终依据。

---

## 19. 备注与附件

Expense 和 LedgerUnit 支持：

- 文字备注；
- 图片上传；
- Android 直接拍照。

附件统一建模，预留类型：

```text
image
file
link
```

MVP 只实现图片，上传前适当压缩，并限制单张大小和每条记录的附件数量。

---

## 20. 逻辑数据职责

### 20.1 原始事实

这些数据由用户操作产生，不应由重算逻辑直接改写：

```text
Activity
LedgerUnit
Participant
Expense
Payment
Split
Transfer
Prepayment 资金记录
Attachment
Dispute
AuditLog
```

### 20.2 可重建结果

这些数据可以由原始事实重新生成：

```text
ExpenseDebt
BilateralDebt
TransferAllocation
PrepaymentUsage
PrepaymentBalance
ParticipantBalance
ActivityFinancialStatus
```

### 20.3 最终结算建议

最终结算方案是当前快照下的临时计算结果，可以按需生成，不是永久账务事实。

只有成功创建的 `final_settlement` Transfer 才进入原始事实。

---

## 21. 核心数据实体建议

### 身份与活动

```text
profiles
activities
activity_members
ledger_units
participants
participant_claims
```

### 消费与分摊

```text
expenses
payments
splits
attachments
```

### 债务与转账

```text
expense_debts
bilateral_debts
transfers
transfer_components
transfer_allocations
final_settlement_paths
transfer_disputes
```

### 预存

```text
prepayment_accounts
prepayment_usages
```

其中真实预存资金移动由 `transfers.type = prepayment / prepayment_return` 保存，`prepayment_accounts` 可以作为 Activity、owner、custodian 维度的余额投影。

### 协作与审计

```text
audit_logs
exchange_rate_cache
```

---

## 22. 核心业务流程

### 22.1 创建并记账

```text
创建 Activity
→ 添加 Participant
→ 创建 LedgerUnit
→ 新增 Expense
→ 填写 Payment
→ 选择 AA 或手动 Split
→ 服务端校验金额守恒
→ 生成 ExpenseDebt
→ 双边抵消
→ 使用可用预存
→ 展示当前余额
```

### 22.2 普通结算

```text
进入当前活动或子活动
→ 点击转账/收款
→ 选择对方
→ 服务端计算最大金额
→ 用户填写实际金额
→ RPC 事务重新校验
→ 创建 settlement Transfer
→ 生成 Allocation
→ 更新余额和完成状态
```

### 22.3 新增预存

```text
选择 owner 和 custodian
→ 输入预存金额
→ 查询当前 owner → custodian 双边净债务
→ 先偿还当前债务
→ 剩余进入 Activity 级预存余额
→ 保存 Usage 和当前余额
```

### 22.4 大型活动最终结算

```text
打开最终结算
→ 服务端汇总大型 Activity 全部当前未结账务
→ 普通债务计算优化转账方案
→ 加入保持原方向的预存返还
→ 合并同方向用途
→ 显示建议
→ 用户确认某笔真实付款
→ RPC 重新计算并匹配当前建议
→ 创建 final_settlement Transfer
→ 更新余额
→ 重新生成剩余建议
```

---

## 23. 验收示例

### 示例一：多付款人确定性债务

```text
Expense：300.0
Payment：A 200.0，B 100.0
Split：A 80.0，B 100.0，C 120.0
```

净额：

```text
A：+120.0
B：0
C：-120.0
```

结果：

```text
C → A 120.0
```

### 示例二：双边抵消

```text
Expense 1：B → A 100.0
Expense 2：A → B 40.0
```

当前展示：

```text
B → A 60.0
```

### 示例三：预存优先

```text
B 在 A 处预存：500.0
新消费产生 B → A：300.0
```

结果：

```text
PrepaymentUsage：300.0
剩余预存：200.0
普通债务：0
```

### 示例四：新增预存时已有债务

```text
B 当前欠 A：300.0
B 新增预存：1000.0
```

结果：

```text
偿还债务：300.0
新增预存余额：700.0
```

### 示例五：反向债务不抵消预存

```text
B 在 A 处预存：1000.0
A → B 普通债务：200.0
```

保持：

```text
B 在 A 处预存：1000.0
A 欠 B：200.0
```

### 示例六：大型活动最终结算

```text
早餐：A → B 100.0
门票：B → C 100.0
```

日常债务保持两条，最终结算建议：

```text
A → C 100.0
```

只有 A 真实付款并创建 final_settlement Transfer 后，才更新活动余额。

### 示例七：关联退款恢复预存

```text
原 Expense 使用 B 的预存：300.0
当前 B 在 A 处剩余预存：700.0
关联退款中 B 应获得：100.0
```

结果：

```text
原 Usage 降为：200.0
当前预存升为：800.0
```

### 示例八：争议不改变余额

```text
A → B Transfer：200.0
B 对该记录提出争议
```

结果：

```text
Transfer 仍然有效
当前余额不变
界面显示争议标记
```

---

## 24. 开发阶段的硬约束

以下规则必须同时在数据库/RPC 和客户端体现：

1. 基准币金额统一保留 1 位小数。
2. Payment 合计和 Split 合计必须等于 Expense.base_amount。
3. 每笔 Expense 按固定参与人顺序独立生成债务。
4. 日常只允许双边抵消，不进行三方路径优化。
5. settlement Transfer 不得超过当前同方向净债务。
6. final_settlement 只能匹配服务端当前大型活动最终结算方案。
7. 预存只抵扣双边抵消后的 owner → custodian 当前净债务。
8. 大型活动预存作用于整个 Activity，不能绑定单个子活动。
9. Transfer 和 Prepayment 创建后不可直接编辑。
10. Dispute 不改变 Transfer 和余额。
11. 所有改变资金余额的写入必须经过服务端 RPC 单事务校验。
12. LWW 只用于普通协作编辑，不用于资金金额上限校验。
13. completed 由余额自动计算，archived 由 Creator 手动控制。

---

## 25. MVP 完成标准

满足以下条件时，可以认为业务逻辑 MVP 闭环：

- 普通活动可以完成创建、记账、分摊、转账和归档。
- 大型活动可以创建子活动并汇总全部账务。
- 多付款人和手动分摊能够稳定生成确定性债务。
- 双边抵消、部分还款和多次还款结果正确。
- Activity 级预存可以新增、消费抵扣和返还。
- 外币 Expense 能固化汇率并统一折算到基准币。
- 退款、逻辑删除和恢复能够触发正确的当前重算。
- final_settlement 能根据当前大型活动方案安全写入。
- 两台设备并发提交资金操作时不会突破当前金额上限。
- User、Participant、Creator、Member 和认领关系符合权限规则。
- completed、active、archived 和争议提示能够正确展示。
