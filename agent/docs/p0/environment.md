# P0 环境核验

核验日期：2026-10-06 至 2026-10-07。本环境文档执行子任务只读检查；主线另按既有授权完成隔离 DB 回归、linked scope migration，以及已下载模型的一次短时原生 host/Docker 合成 chat。没有改持久服务配置、下载/安装/更新软件、训练或发出 Teacher 请求；临时模型由本次执行员定向卸载。主机资源和栈状态会变化，实际测试前必须重查。

## 主机与工具

| 项目 | 只读观察 | 限制 |
|---|---|---|
| P0 原始审计工作目录 / shell | D:/project/Android/shared-ledger / Windows PowerShell | 2026-10-06 至 2026-10-07 原核验时的工作区快照；不代表拆分后的 Agent checkout |
| P0 原始审计 Git | 分支 feature/ai-training-pipeline；HEAD dcdb033b9cc245f355f61b5a303007b7d7571e18 | 保留为原审计时历史快照 |
| 当前 Agent worktree | D:/project/Android/shared-ledger-agent；分支 agent；HEAD dcdb033b9cc245f355f61b5a303007b7d7571e18 | agent/ 下 10 个文档未提交，index 为空；其 app/supabase/docs/backend 是旧提交基线 |
| 当前业务源码 worktree | D:/project/Android/shared-ledger；分支 main；HEAD d305011b02e6105e2fe3e5b40460de4218d466ba | 35 个业务文件未提交，index 为空；当前业务代码/迁移/测试来源 |
| Python | `py --version` 为 3.12.0；已知 `D:\AI\.venv\Scripts\python.exe --version` 为 3.11.15 | 不导入训练框架，不声称训练依赖完整 |
| Java | `java -version` 为 25.0.1 LTS | 本轮命令 |
| Docker / Compose | Docker 29.8.1、Compose 5.5.1、`desktop-linux` context | 本轮版本核对；不调整 context |
| Supabase CLI | 2.116.0；CLI 显示较新版本 2.119.0 可用 | 不升级/安装 |
| WSL | 既有只读记录见 `Ubuntu`、`docker-desktop` | 本轮未启用 WSL 作业 |
| 共享 DB 容器 | `supabase_db_shared-ledger`，PostgreSQL 17.6；最近 migration `20260925133211` | catalog 只读；落后仓库 migration。绝不对共享栈迁移/reset/写入 |
| Linked remote 数据库 | 主线只将 `20261006142507_sub_activity_participant_scopes.sql` 推送到 ref `zecjkgvwpcvwheyflbyi`，exit 0、`--skip-vault`；无 seed/role 改动或生产业务测试行。只读核验确认 migration history、default-false scope marker、scope 表 Member-read-only RLS、两个 public overload 仅 authenticated EXECUTE、旧 helper 撤权、三 scope trigger enabled、projection wrapper guard/rebuild | 此结论限于该 migration 及相关 catalog/ACL，不是全 CAP 线上端到端验收；本环境核验子任务没有执行 linked push |
| 隔离 DB / smoke 容器 | 主线确认 fresh DB 全回归完成，测试栈 `sl-dbtest-04074edf63` 已停止且 DB 容器已移除；只读 `docker stats` 不再列该容器。旧 `sl-dbtest-8111550fa0` 与 shared-ledger/smoke 容器仍在运行 | 隔离全套回归已结束；没有停止或修改其他既存容器，容器名称/健康状态不等于当前存在测试任务 |

LM Studio 桌面主程序 `D:\computer\LM Studio\LM Studio.exe`：主审本轮直接读取 ProductVersion `0.4.25.0`、FileVersion `0.4.25+1`。独立 CLI `C:\Users\zhy20\.lmstudio\bin\lms.exe`：文件 ProductVersion `1.3.3`，`lms --version` 标识 commit `69d945a`。两者分别记录，不能把 CLI 版本当桌面 app 版本。

## LM Studio、模型目录和资源

- `lms server status --json` 返回 `running=true, port=1234`；执行 chat 前后均确认 `lms ps --json` 为空列表 `[]`，临时测试模型已定向卸载，LM Studio server 仍运行。
- `lms ls --variants --json` 列出的 Qwen 是 `qwen/qwen3.5-9b@q4_k_m`，格式 GGUF、量化 Q4_K_M，大小 6,548,927,711 bytes（约 6.55 GB / 6.10 GiB）。目录 metadata 的最大上下文 262,144 仅为 catalog 字段，未由实际加载/推理证实。另有 embedding catalog 项。
- 宿主 `GET http://127.0.0.1:1234/v1/models` 与既有 DB 容器中 `GET http://host.docker.internal:1234/v1/models` 均曾 HTTP 200 且 ID 相同。LM Studio 官方说明 JIT 可使 models API 列出本机已下载目录：<https://lmstudio.ai/docs/developer/openai-compat/models>。因此 GET 只证明 catalog/API 与 Docker→host 网络路径可达；它不证明模型已加载、推理可用，也不证明 chat 端点的认证策略。
- 2026-10-06 23:45 +08 的历史快照：GPU RTX 4060 Laptop 总 8,188 MiB、空闲 3,750 MiB（约 3.66 GiB）、利用率 38%；31.8 GiB RAM 中可用 0.82 GiB。此时不加载。前列工作集为 YuanShen 4,819 MiB、`vmmemWSL` 2,714 MiB、`studio64` 2,303 MiB 与两个约 1.7 GiB Java 进程；GPU 进程清单无可用 per-process 显存值。该快照已被后续资源状态取代，不能作为当前资源阻断结论。
- 2026-10-07 00:49 +08 新快照：主线确认隔离测试栈清理；`lms ps=[]`、GPU free 6.15 GiB / 利用率 15%、RAM free 8.83 GiB。约 00:59 复核资源仍有名义余量且无已加载模型/活跃推理；在主审核准后，使用本机已下载的 `qwen/qwen3.5-9b@q4_k_m`，命令参数为 `--context-length 512 --gpu 0.5 --parallel 1 --ttl 300 --identifier p0-audit-9b`。未改持久设置，也未停止未知 DB 容器。
- OpenAI 兼容 `POST /v1/chat/completions` 使用纯合成输入 `Say hello in one short sentence.`、`stream=false`。Host `max_tokens=64` 和一次获准的 `128` 都 HTTP 200、model 为 `p0-audit-9b`，但 `choices[0].message.content` 是空字符串，usage 分别为 17/64/81 与 17/128/145，finish_reason 均为 `length`；Docker 路径 `max_tokens=64` 也 HTTP 200、内容为空，usage 为 17/64/81、finish_reason=`length`。原统计代码按 `choices[0].message.content` 字符串读取，测量可靠。该兼容 API 没有返回可见内容，不能算 chat 通过；留作 P2 兼容性排查。
- 随后按官方 REST `POST /api/v1/chat` 每侧各一次，不含 system/integrations，payload 设置 `reasoning:"off"`、`max_output_tokens:64`、`stream:false`、`store:false`。Host 和 Docker 均 HTTP 200、`model_instance_id=p0-audit-9b`、输出项类型为 `message`，字符串 content 经 trim 后非空；未打印正文。Host 成功测量长度 6，Docker 长度 26；响应 stats 均报告 `reasoning_output_tokens=0`。Host 首次尝试的脚本误把字符串当数组，已获准只重做一次 host 请求并正确处理字符串；以更正后的结果为准，未重试 Docker。
- 测试后定向执行 `lms unload p0-audit-9b` 成功；最终 `lms ps=[]`、server 仍运行，RAM free 9.14 GiB、GPU free 6,058 MiB / 利用率 8%，隔离回归栈筛查为空。原生路线的 9B host/Docker 最小合成 chat 已通过并关闭 P0-ENV-01 的模型运行项；这仅验证已下载 9B GGUF 的短时运行，不验证 OpenAI 兼容 payload、4B adapter 链、业务语义质量或 Agent。

## Teacher 路由核对（没有发请求）

- 只允许读取 `.env` 中的 provider/model/Base URL 非密钥字段；观察为 provider `opencode`、model `deepseek-v4.1-flash`、Base URL `https://opencode.ai/zen/go/v1/chat/completions`。API key 是否存在只记为“有值”，未打印、验证或使用；温度与无关环境变量未输出。
- 直接查看 `live_provider.py` 的 `_endpoint()`：若 Base URL 已以 `/chat/completions` 结尾，会原样返回，不再追加 `/v1`。故本机路径完整匹配 OpenCode Go 官方模型页公布的 `https://opencode.ai/zen/go/v1/chat/completions` 路由：<https://opencode.ai/docs/go/>。provider/model/endpoint 配置路径一致是本轮直接核验事实；官方目录与 route 核对是公开信息事实。
- 未联网调用 Teacher。因此本机凭证有效性、权限/额度、model ID 实际可用性、响应契约与费用仍未验证，也不从公开目录推断这些项目。

## P0 环境状态

| 检查 | 当前状态 | 关闭条件 |
|---|---|---|
| 本机 server/catalog | 已直接读取 | 无需推断推理能力 |
| Docker 到 host models API | 历史只读探针 HTTP 200 | 已证明 catalog/API 路径；不等价 chat 或认证验证 |
| 9B host 原生 `/api/v1/chat` | 通过：HTTP 200、输出 `message` content 非空；已卸载模型 | 本次 P0-ENV-01 关闭；只验证已下载 9B GGUF 的受控 runtime |
| 9B Docker 原生 `/api/v1/chat` | 通过：HTTP 200、输出 `message` content 非空 | 本次 P0-ENV-01 关闭；不能扩展成兼容 API 或 Agent 验收 |
| OpenAI 兼容 `/v1/chat/completions` | 三次 HTTP 200，host 64/128 与 Docker 64 的 content 均为空、finish_reason=`length` | P0 native route 已关闭；兼容 payload 可见回复/推理行为列 P2 跟进，不报通过 |
| 4B adapter→LM Studio | 未执行 | 按 [T0 路径](t0-assets-and-lessons.md#4b-adapter-与-9b-gguf-不是同一模型) 独立完成 adapter 对应、merge、GGUF 转换、加载与最小 chat |
| Teacher completion | 未执行；远端 completion 不在本次审计范围内 | 将来若 generation 任务包含 Teacher 调用，按该任务记录额度与数据边界；不能用 key-present 替代验证 |

9B 原生路线的 host 与 Docker 最小 runtime smoke 已通过；OpenAI 兼容路径未返回可见回复，按 P2 跟进。未声称 Teacher、4B adapter 链或 Agent 语义已通过。
