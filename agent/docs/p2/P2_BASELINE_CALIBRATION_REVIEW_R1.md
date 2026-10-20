# P2 baseline calibration — 独立复核记录 R1

**判定：`VERIFIED_WITH_FINDINGS`（实质结论成立）／`NOT_ACCEPTED_AS_REPRODUCIBLE`（绑定关系未通过）。**

本文复核 [P2 baseline calibration R1](P2_BASELINE_CALIBRATION_R1.md) 的声明，逐项从证据artifact 重算。**结论是分裂的**：四条证据 leg 的实质数值全部可从 artifact 复算成立；但校准记录赖以成立的**绑定关系**（pin 对应已提交源码、套件证据对应那个源码）在当前状态下不可复现或不可核验。因此在校准记录修好之前，它不应被当作"可复现的正式验收记录"使用。

## 0. 审查性质与独立性（必须先读）

- **审查方 = 产出方（同一 P2 会话）**。这是**对声明的再验证（re-verification）**，不是组织意义上的独立评审。
- 本文**不**声称独立。作为 T1 准入的关闭依据，仍须 **root 会签**；会签栏见 §8。
- 再验证的确是独立动作：所有哈希由本脚本重算，所有数值从 artifact 重读，未采信校准记录的叙述；另外**主动做了一次干净 checkout 复现**（见 §4 R1-1/R1-4），而不是只核对文档自洽。

## 1. 审查范围与方法

只读。未改动任何生产代码、测试、既有证据文件。

| 复核项 | 方法 |
|---|---|
| pin 摘要与组件绑定 | 重算 manifest 的 SHA-256；对 49 个组件按**提交 `3fcb2fd` 的 git 对象**复算（而非工作树），并额外用"行尾规范化"变体比对 |
| pin 的可复现性 | 在 `3fcb2fd` 上 `git worktree add --detach` 出**干净 checkout**，用同一 venv 重新逐组件比对 |
| 四条 leg | 重读各自 `close-loop-result.json`，抽取结果、键值、预算、返回码与桥统计，并记录 artifact 自身 SHA-256 |
| 全量套件证据 | 重读 `baseline-result.json`；对保存的 `pytest-full.stdout.txt` 重算 SHA-256 并与记录值比对；核对记录的 `git_head` 与工作树是否 clean |
| 干净 checkout 下的套件 | 在上述干净 worktree 内以整目录调用重跑全量，并归因每个失败 |

产物：`D:/AI/runs/shared-ledger/p2/calibration-review-20261020-01/verify_calibration.py`、`verify-output.json`、`review-evidence.json`；干净 checkout 套件：`D:/AI/runs/shared-ledger/p2/review-suite-3fcb2fd/pytest.stdout.txt`。

## 2. 逐项复核结果

### 2.1 pin 摘要

| 项 | 声明 | 复核 |
|---|---|---|
| manifest SHA-256 | `362e66ad…e8a848` | **一致**（重算 `362e66ad04491be4f711c8db076f5bb0736904b5d6e9962a9f13ba82e6e8a848`） |
| 组件数 | 49 | **一致** |
| 组件绑定 | "对当前工作树 0 处 mismatch" | **对本机工作树成立**；但**对提交对象不成立**（见 R1-1） |

### 2.2 四条证据 leg（数值全部可复算）

| leg | run 目录 | 结果 | 模型 POST | source 收据 | QEV | fact | 受保护答案 | claim 已释放 | 关键量 |
|---|---|---|---|---|---|---|---|---|---|
| offline | `run-3a2ccfcf36-offline` | `CLOSE_LOOP_COMPLETED` | **0** | 2 | 1 | 1 | 1 | 是 | 引用 `qev_AIYO…`；桥只转发 GET（auth 11 / activities 2 / activity_members 3） |
| live | `run-9e41381182-live` | `CLOSE_LOOP_COMPLETED` | **2**（均 200） | 2 | 1 | 1 | 1 | 是 | 引用 `qev_wyfV…`；模型调用额度 3、逻辑读取 1 |
| offline-resume | `run-bd61b11ad6-offline-resume` | `AUTH_RESUME_COMPLETED` | 0 | 4 | 2 | 2 | 1 | 是 | `auth_503_count=1`；attempt `[1,2]` 均 page 0；**单一逻辑查询**；`orphan_invariant=settled` |
| live-resume | `run-6ce2698302-live-resume` | `AUTH_RESUME_COMPLETED` | **2**（均 200） | 4 | 2 | 2 | 1 | 是 | 同上，且用 2 次真实 POST 完成读与答 |

四条 leg 的 artifact 各自记录了 `manifest_sha256 = 362e66ad…`，与 pin 摘要**逐一相符**。这是本复核中**最强的一项**：leg 与 pin 的绑定在 artifact 层面成立。

### 2.3 全量套件

| 项 | 声明 | 复核 |
|---|---|---|
| 结果 | 745 passed + 1 xfailed，连跑两次 | **文本一致**（两次 stdout 均为 `745 passed, 1 xfailed`），退出码 0、导出复核 0 |
| 源码绑定 | "均在该提交（`3fcb2fd`）上产出" | **不成立为可核验事实**：两次 artifact 记录 `git_head=0022b00`、`git_status_clean=false`（见 R1-2） |
| stdout 哈希 | 记录了 SHA-256 | **不可复算**：保存文件的字节与记录值不同（见 R1-3） |
| 干净 checkout 复现 | — | **740 passed / 5 failed / 1 xfailed**，5 项归因见 R1-4 与 §4 说明 |

## 3. 发现清单

### R1-1（阻断：可复现性）pin 绑定的是本机工作树的字节形态，不是已提交源码

- 按提交 `3fcb2fd` 的 git 对象复算：46 个仓库组件中 **41 个精确匹配、2 个仅行尾规范化后匹配、3 个两种规范化都不匹配**。
- 在 `3fcb2fd` 的**干净 checkout** 上复算：**44 / 46 不匹配**。
- 不匹配全部是行尾差异，不是内容差异。例如 `agent/app/contracts.py`：manifest 记 `9fd214d9…`（正是 `CONTRACT-VERSION-DIFF.md` 记过的"agent checkout 原始字节 SHA"），提交对象是 LF 规范化的 `4da745ee…`。
- **影响**：manifest pin 由工作树字节生成，而本机工作树是行尾混合形态（部分文件被编辑器写成 CRLF、部分由 git 检出）。任何干净克隆或第三方环境都会 fail closed。pin 因此**不能作为"源码身份"被独立复现**，只能作为"这台机器当时那份字节"的指纹。
- **对校准记录的影响**：§2 的"对当前工作树逐组件复核 0 处 mismatch"字面为真，但"源码提交 `3fcb2fd`"这一行会误导读者以为 pin 可从仓库复现。

### R1-2（中）套件证据产自脏树，源码绑定靠推断

- 两次 `baseline-result.json` 均记录 `git_head=0022b00a…`、`git_status_porcelain` 非空。
- `git log` 显示 `3fcb2fd` 的父提交正是 `0022b00`，即那次运行发生在**批次改动尚未提交**的脏树上；字节上等同 `3fcb2fd`，但 **artifact 本身无法证明这一点**（没有工作树摘要）。
- **影响**：校准记录"四条 leg 与全量套件均在该提交上产出"对 leg 成立（leg 绑定 manifest 摘要），对套件**只能靠历史推断**。

### R1-3（中）录制的 stdout SHA-256 无法从保存的文件复算

- 重算与记录值不符（两次运行均不符）。
- 根因已定位：`run_baseline_suite.py` 用 `Path.write_text(str(output))` 保存，Windows 上把 `\n` 再翻成 `\r\n`，文件里出现 `\r\r\n`（实测 `CRLF=19, LF-only=0`，尾部为 `...\r\r\n`）；而记录值是对**子进程原始字节**取的哈希。
- **影响**：证据链的"哈希可复算"这一环断裂；内容仍可读、结论仍可核对，但哈希声明无效。

### R1-4（中）三个迁移用例硬编码原始仓库绝对路径

- `agent/tests/test_p2_v3_store_recovery_edges.py:1169-1172` 直接写 `Path(r"D:\project\Android\shared-ledger-agent\...")`。
- **影响**：套件只在原始 checkout 路径下全绿；任何其他路径/干净 worktree 副本，这 3 个用例必然因校验和不一致失败（干净 checkout 实测正是这 3 条）。
- 干净 checkout 另外 2 条失败（`unable to open database file`）是**本复核方的调用差异**：未预建两个 store 根目录；预建后该文件其余用例可通过。这不计入产品问题。

### R1-5（低）leg 的 HEAD 绑定是"声明"而非"校验"

- harness 把 `P2_EXPECTED_HEAD` 原样写进结果，**从不执行 `git rev-parse` 核对**。四条 leg 记录里该字段只是调用方给的字符串。
- **影响**：leg 与源码的真实绑定实际来自 `manifest_sha256`（已逐步核对通过）。该字段应删除或改为实测。

### R1-6（信息）证据目录含 24 次未成功尝试，均已保留

36 条运行中 24 条未成功，分类如下（不推翻四条 leg，但必须与成功项一并引用）：

| 类别 | 数量 | 说明 |
|---|---|---|
| harness 迭代失败 | 13 | manifest/SHA 前置校验、cohort 未通过、缺失 env、桥在故障解除后重新武装、轮询对瞬时 503 不容忍——均为**我的 harness**缺陷，非产品 |
| 修复前的遗弃缺陷复现 | 6 | `TURN_RUNNING` + 持 claim，正是后来被 `_finalize_claim` 修掉的缺陷 |
| 修复前的预算耗尽 | 2 | `TURN_FAILED` / `RATE_LIMITED`（恢复在描述符绑定前重规划） |
| 模型侧协议不遵循 | 2 | live leg 的 `TURN_FAILED`，answer 多出契约未声明字段；原始响应已留档 |
| 模型未加载 | 1 | live-resume 启动即失败 |

**披露**：四条 leg 都是在修掉上述产品缺陷（遗弃缺陷、提示词）之后、在同一 pin 上跑出的。这是正常的"先修后验"，但读者应知道成功样本是修复后的、且同一目录里保留了负例。

## 4. 对校准记录的措辞修正建议

| 位置 | 现文 | 建议 |
|---|---|---|
| §2 "组件绑定" | "49 个 component，对当前工作树逐组件复核 0 处 mismatch" | 补一句：**pin 由本机工作树字节生成，行尾形态与干净 checkout 不一致；独立复现须先规范化行尾**（R1-1） |
| §2 "源码提交" | "四条 leg 与全量套件均在该提交上产出" | 拆开：leg 成立（manifest 摘要逐步相符）；套件为"脏树、HEAD 0022b00、字节等同 `3fcb2fd`"，属推断（R1-2） |
| §4 "证据" | "各含 `baseline-result.json`、原始 stdout 及其 SHA-256" | 注明 stdout 哈希不可复算（R1-3），并替换为准确描述 |
| §4 调用方式前提 | 两条前提 | **增加两条**：必须在原始 checkout 路径下运行（R1-4）；两个 store 根目录须**预先存在且每轮清空** |

## 5. 复现方式

```bash
# 1) 再验证（只读）
python D:/AI/runs/shared-ledger/p2/calibration-review-20261020-01/verify_calibration.py

# 2) 干净 checkout 复现套件（本复核已执行，worktree 已清理）
git worktree add --detach <dir> 3fcb2fd
# 以整目录调用运行，并预先建好两个 store 根；原始路径下的 3 条硬编码用例除外
```

## 6. 处置建议（按优先级）

> **2026-10-20 裁定：本节建议暂停执行。** 用户决定停止绑定修复，P2 按「完成、带已知限制」收口并转 P3b 待命；下列 1–6 项转为已知限制的「何时必须回头处理」触发条件，见 [P2 收口：已知限制一页](P2_CLOSED_LIMITS_R1.md) §二。

1. **重签 pin 前先修可复现性**：哈希前统一行尾（或改为对 git blob 取哈希，并在仓库加 `.gitattributes` 固化），使同一提交在任何 checkout 上得到同一组哈希。否则 pin 只是本机指纹。
2. **套件证据重新绑定**：在 clean tree 上重跑并记录 `git_head` + clean 标志（或在 artifact 里记录 `app/`+`tests/` 的工作树摘要）。
3. **修 `run_baseline_suite.py` 的写文件方式**：`write_bytes` 代替 `write_text`，让记录的哈希可复算。
4. **去掉测试里的绝对路径**：改用 `Path(__file__).resolve().parents[2]`，使套件可在任意路径运行。
5. **leg 的 HEAD 字段**：删除或改为实测 `git rev-parse`。
6. 上述完成后重跑四条 leg 与全量，再出 R2 校准记录并请 root 会签。

## 7. 本复核明确未做的事

未修改任何生产代码、测试或既有证据；未重跑模型 leg（本次只做只读复核与一次干净 checkout 的 CPU 套件复现）；未对模型质量、云端、CAP 作任何结论。

## 8. 签署

- 复核方：P2 会话（**产出方自审**，非组织独立评审）
- 复核日期：2026-10-20
- 复核依据：§1 列出的脚本与 artifact；所有数值均由脚本重算
- **root 会签：________________（未签署）**
