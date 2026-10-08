# T0 步骤 3–5 进行中记录

记录时间：2026-10-08 09:58（Asia/Shanghai）。当前 run：`D:/AI/runs/shared-ledger/t0-deploy-smoke/20261007-200705-step3-merge/`。T0 尚未验收。本报告仅更新内部运行证据索引；大型权重、遥测、stdout/stderr 与原始模型响应均留在 D 盘 run 中。

## 阶段状态

| 步骤 | 状态 | 当前事实 |
|---|---|---|
| 1–2 | 完成 | 见[此前预检报告](20261007-192738-step12-aonly-cp36.md)。旧 A-only `checkpoint-36` 仅作格式兼容核对，不是新版语义质量、模型部署或 CAP 通过证据。 |
| 3 | **进行中** | Merge attempt 1、2 被私有进程树内存保护门安全终止；attempt 3 merge 与 metadata 检查通过，但 HF base+adapter 与 merged 模型对冻结用例的比较仍待完成。 |
| 4 | 工具链就绪，等待步骤 3 释放 | 本地 comparator 与 quantizer 已构建并过 harness 安全检查；F16/Q4 转换和模型对照尚未开始。 |
| 5 | 预检与日志路径准备完成；等待经主审批准的 Q4 产物 | LM Studio host/Docker 请求和分析 harness 已准备。没有导入或加载本轮模型，也没有执行 chat。 |
| 6 | 未开始 | T0 归档、共享状态文档更新和提交均未执行。 |

## 步骤 3 的实际尝试

- Attempt 1 以 exit 125 结束，原因是保护门 `process_tree_private_bytes_over_limit`；6 次遥测采样，`termination_verified=true`。这是安全中止，不是 merge 成功。证据：D run `logs/merge-tree-v1.tree-end.json` 与相应 telemetry/stdout/stderr。
- Attempt 2 因同一保护门以 exit 125 结束；33 次遥测采样，`termination_verified=true`。`merged-hf-attempt2` 仅有 1,696,082,848-byte 首分片与 10 条 per-tensor 记录，属于部分输出，不可转换或部署。证据：`logs/merge-tree-v2.tree-end.json`、`logs/merge-tree-v2.telemetry.jsonl`、attempt 2 目录清单。
- Attempt 3 merge 于 2026-10-08 09:55（+08）以 exit 0 完成，保护门未触发，71 次采样。输出 `merged-hf-attempt3/` 两个 shard 分别为 5,329,398,688 与 3,990,429,408 bytes，SHA-256 分别为 `9462882722b4b97c847f483877667dbd6b14c372c177bbfeb979f016e29f36ca` 和 `63b8c849d60c8bbef69d54c21fc72a89c56032c5b65db54bb4cba876b911ebdf`。`stream-merge-result.json` SHA-256 为 `A1C0942F69C53C8221602B95F38076639CC8F6B621B591E8603960530EE4C7A4`；safe-open metadata 校验 738/738 tensors 通过，校验记录 SHA-256 `11f9065620213c2375f9b87ceae7a6f72c5cf70eaca6635ede6b1e2d432683dc`。step 3 agent 汇报原始输入 hash 前后相同、248 个更新 tensor 与 bitwise reference 匹配、490 个 copy tensor 逐字节匹配、destination reread 738/738 通过。文件索引：`logs/merge-tree-v3.tree-end.json`、`logs/launch-merge-attempt3.meta.json`、`attempt-3/evidence/stream-merge-result.json`、`logs/safeopen-metadata-v3.python.stdout.txt` 与 `logs/safeopen-metadata-v3.tree-end.json`。
- Merge 通过仍不等于步骤 3 完成。当前下一项是按固定模板和相同 token 输入完成 base+adapter 与 merged HF 的合成对照；converter agent 表示重资源转换等待这项工作释放。

## 步骤 4 和 5 的准备边界

步骤 4 已构建的 comparator `step4-converter/build-sdk-ninja/t0_gguf_compare.exe` SHA-256 为 `21141EA88839F89F1B2E1EE4D7AEF1BE5E21D4AFBA7E80265C5A41A357354319`；对应 `gguf_compare.cpp` SHA-256 `38C25A30FC74DBA149BD6FB8E38A083EB3A296B10078349A288EE8215C794597`。`llama-quantize.exe` SHA-256 `C8E52FA79F32BFB0DA949A4F80077F6AF4A478B8EE502CABD8D72E09448B48DF`。构建记录在 `step4-converter/command-logs/cmake-rebuild-harness-final.meta.json`；overwrite-guard 的预期拒绝也留在 `step4-converter/command-logs/harness-guard-outdir-final.meta.json`。目前没有 F16 或 Q4 产物，HF release/比较完成前不要启动 conversion。上述工具与文件 hash 是工具链事实，不是模型转换通过。

冻结 `cases.json` SHA-256：`CB65DD89EE1B9BD3E537090305B92A85046EF57B1F16B06490EB55ADE920D93E`。step 5 只使用 `shared_ledger_explanation`（max output 32）和 `agent_answerdecision_json`（max output 96），上下文 512、thinking 关闭；manifest 中的算术 case cap 为 16，属于固定对照集，不加入 step 5 请求。每个 case 在 host 与 Docker 仅请求一次，不重试。

步骤 5 `scripts/step5_harness.py` SHA-256 `887C65833E45F0A5B37CE9CF723DA2A3B81896BA98151093B05935059AB90C60`。静态核验 exit 0，记录在 `logs/step5-harness-static-check.meta.json`、`.stdout.txt`、`.stderr.txt`；检查包括 AST、manifest SHA/caps、重复 JSON key 拒绝、HTTP/client exit/non-empty runtime gate，以及 response instance ID 与批准目录映射的检查路径。JSON format 与 runtime 独立报告；这些准备不代表模型执行结果。

当前没有经主审批准的 Q4 GGUF hash/metadata，故尚未进行 LM Studio import/load、native chat、Docker client、卸载本轮实例或任何实际推理。已有 catalog 中的 `qwen/qwen3.5-9b@q4_k_m` 是不同的 9B 模型，不替代本轮 4B 产物，也不作为步骤 5 结果。

## LM Studio 日志迁移证据

迁移前 `lms server status --json` 为 `running=false, port=1234`，匹配的 TCP listener 列表为空；settings 安全字段提取没有发现 server port/bind/CORS 字段，因此起始 active bind/CORS 为 N/A。一次 `lms ls --variants --json` 读取本机磁盘 catalog 时 stderr 记录“Waking up LM Studio service...”副作用；读取后仍无 1234 listener。该命令只执行一次，没有运行 `lms ps`，没有关闭 GUI 或其他进程。原状态与 help 证据见 D run `logs/step5-server-start-snapshot.json`、`logs/step5-server-control-help.json`、`logs/step5-lms-local-catalog.meta.json` 和对应 stdout/stderr。

C 源日志共 33 文件、7 目录、19,214,170 bytes。Robocopy 已复制到 `D:/AI/runtime/lmstudio/server-logs`；源与目标逐文件双采样 SHA/长度一致后，将原 C 目录一次性改名保留为 `C:/Users/zhy20/.lmstudio/server-logs.pre-t0-20261007-200705`，并在 C 原路径建立指向 D 的 directory junction。hold 和 D 当前各有同样 33 个文件/19,214,170 bytes，最终逐文件 SHA/路径差异为 0，junction 目标精确匹配。可复核索引：`logs/step5-serverlogs-robocopy.summary.json`、`logs/step5-serverlogs-C-pre-rename-final.json`、`logs/step5-serverlogs-D-copy-verify.json`、`logs/step5-serverlogs-rename-junction.meta.json`、`logs/step5-serverlogs-C-hold-final.json`、`logs/step5-serverlogs-D-final.json`、`logs/step5-serverlogs-final-verify.meta.json`。

初始 server stopped，因此迁移期间没有启动服务。junction 和数据完整性已验证，但尚无 native LM Studio 日志追加写入 D 的证据；C hold 保留，待获准的后续运行确认 native 写入后再另行审查清理。所有迁移 stdout/stderr、时间戳、exit code 与复现脚本留在同一 D run 的 `logs/` 和 `scripts/` 中；`scripts/step5-plan.md` 已记录现状。

## 旧资产与结论边界

旧 A-only `checkpoint-36` 只承担格式兼容预检用途，不能证明当前 merge、GGUF 转换、Q4 运行、新版语义或 CAP 质量。历史 9B 原生 host/Docker smoke 也仅是 9B runtime 证据。当前未运行 Teacher、训练、真实账本样本或工具调用。P1 并行变更文件没有在本次报告中修改；没有 stage、commit 或 push。
