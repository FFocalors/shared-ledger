# P1-06 deployment and recovery record

初始静态记录：2026-10-09；真实容器续验：2026-10-10（Asia/Shanghai）  
范围：Agent 专用 checkout 中的 Docker Compose 部署、SQLite 备份/恢复与容器重建验收。  
状态：2026-10-10 真实 Docker A10 容器验收、P1-04 本地真实 Supabase Auth 正向补验均已通过；主会话已于 2026-10-10 批准整体 P1 限定工程范围通过（`PASSED_LIMITED_P1_ENGINEERING`）。A01–A11 无阻塞项；生产 Scope、模型推理与业务写入仍未验证/保持关闭。限制和证据索引见[整体终审报告](FINAL_REVIEW.md)。

本阶段只在 Agent 专用 checkout 操作。业务 shared-ledger 主 checkout、共享 agent/README.md、agent/docs/dev-status.md、统一指南及 P0/T0 历史未修改。没有执行 git add、reset、清理既有文件、commit 或 push。实际容器验收脚本使用两个随机 p1-06-* Compose project、独立宿主 loopback 端口及私有临时目录；结束时仅按这两个 project 名称清理其服务、网络和卷，并保留构建镜像与脱敏 JSON 证据。

## A01–A11 验收矩阵

此前（2026-10-09）主会话独立验证的完整 Python 测试集记录为 126 passed in 26.48s：原 P1-05 的 115 项基线加备份恢复专项 11 项。该历史结果覆盖本地身份夹具、确定性 Mock Runtime、SQLite 和离线协议，不证明真实 Supabase、真实业务数据库、真实模型或 Docker 部署；2026-10-10 Docker 续验未重跑 Python 全量测试。

| 项 | 测试或实际入口 | 覆盖范围与限制 |
|---|---|---|
| P1-A01 | [test_identity_api.py](../../tests/test_identity_api.py)：test_routes_are_authenticated_owner_scoped_and_errors_are_frozen；[test_mock_runtime_api.py](../../tests/test_mock_runtime_api.py)：test_api_owner_boundary_covers_events_cards_and_all_mutations | 两个本地身份夹具的 sessions、events、cards 与 mutation 隔离；不是 Supabase 正向身份验证。 |
| P1-A02 | [test_protocol_contracts.py](../../tests/test_protocol_contracts.py)：test_idempotency_hashes_context_and_replays_original_typed_response；[test_sqlite_persistence.py](../../tests/test_sqlite_persistence.py)：test_different_store_connections_serialize_global_submit_idempotency；[test_identity_api.py](../../tests/test_identity_api.py)：test_clarification_accepts_verbatim_input_replays_before_disable_and_rejects_changed_key | 请求摘要、跨连接唯一键、原响应重放和 resume 去重的本地覆盖。 |
| P1-A03 | [test_sqlite_persistence.py](../../tests/test_sqlite_persistence.py)：test_process_exit_before_and_after_commit_recovers_atomic_turn_and_event；[test_mock_runtime_api.py](../../tests/test_mock_runtime_api.py)：test_api_auth_required_survives_restart_then_http_auth_resume_requeues_turn | SQLite 事务边界与模拟服务进程恢复；真实 Docker stop/start/recreate 另属 A10，已在 2026-10-10 实测。 |
| P1-A04 | [test_identity_api.py](../../tests/test_identity_api.py)：test_auth_resume_restores_planning_confirmation_and_same_execution_checkpoint；[test_mock_runtime.py](../../tests/test_mock_runtime.py)：test_unknown_execution_recovery_keeps_key_and_does_not_starve_queued_turn；[test_mock_runtime_api.py](../../tests/test_mock_runtime_api.py)：test_api_auth_required_survives_restart_then_http_auth_resume_requeues_turn | 本地认证暂停和执行身份恢复夹具；不调用真实 Supabase。 |
| P1-A05 | [test_protocol_contracts.py](../../tests/test_protocol_contracts.py)：test_model_context_refs_and_evidence_resolve_to_persisted_turn_bindings；[test_sqlite_persistence.py](../../tests/test_sqlite_persistence.py)：test_checkpoint_reference_and_read_result_bindings_are_append_only_across_restart | 持久化引用和读结果绑定的确定性协议测试。 |
| P1-A06 | [test_mock_runtime_api.py](../../tests/test_mock_runtime_api.py)：test_api_adjustment_auth_pause_resumes_and_retries_the_same_reserved_input；[test_identity_api.py](../../tests/test_identity_api.py)：test_injected_adjust_preparer_rotates_nonce_and_confirm_gates_expiry_and_disable_revision；[test_sqlite_persistence.py](../../tests/test_sqlite_persistence.py)：test_late_planning_output_loses_to_cancel_state_revision_cas | 本地提案修订、确认门、nonce/expiry 与 CAS 竞争；没有真实业务写入口。 |
| P1-A07 | [test_mock_runtime.py](../../tests/test_mock_runtime.py)：test_model_timeout_keeps_gate_until_provider_finishes_and_discards_late_output；test_global_queue_limit_is_atomic_across_connections_and_rejected_key_can_retry；[test_mock_runtime_api.py](../../tests/test_mock_runtime_api.py)：test_api_admission_429_has_no_receipt_and_exact_request_retries_when_capacity_frees | Mock 延迟、资源上限、取消晚到结果与队列拒绝。 |
| P1-A08 | [test_mock_runtime_api.py](../../tests/test_mock_runtime_api.py)：test_api_disabled_gate_preserves_metadata_and_cancel_then_reopen_stales_old_proposal；[test_identity_api.py](../../tests/test_identity_api.py)：test_agent_gate_replay_and_backend_disable_revision_scope | 本地 Agent 关闭/重开、读取与取消边界；不是生产开关系统验证。 |
| P1-A09 | [test_auth_verifier.py](../../tests/test_auth_verifier.py)：test_remote_http_statuses_are_sanitized_and_http_errors_are_closed；test_network_failures_are_dependency_errors_not_invalid_identity；[test_backup_restore.py](../../tests/test_backup_restore.py)：test_cli_has_documented_exit_codes_and_sanitized_diagnostics；容器 helper exercise.py 的 scan-database 与 scan-text | 单测验证诊断脱敏；容器数据和日志哨兵扫描已编码为真实容器步骤。Docker engine 不可用时，不把脚本或 pytest 结果记作容器日志扫描通过。 |
| P1-A10 | deploy/scripts/Test-Agent.ps1；deploy/acceptance/exercise.py 的 before-restart、offline-recovery、after-restart；[test_backup_restore.py](../../tests/test_backup_restore.py)：test_online_wal_backup_restores_real_store_and_concurrent_commits、test_large_valid_database_uses_volume_tmp_for_verify | 2026-10-10 真实 Compose build、普通生产入口、health/Auth关闭门、在线备份、stop/start、干净新卷恢复、recreate 和 DB/日志哨兵扫描均 PASS；仅本地模拟身份、无真实 Supabase/model/business writes。详见实际验收证据。 |
| P1-A11 | [test_protocol_contracts.py](../../tests/test_protocol_contracts.py)：test_all_mock_trajectories_pass_json_schema_and_source_protocol；test_semantic_boundary_is_closed_and_money_is_decimal_text；test_capability_registry_and_openapi_are_complete_and_interoperable；python -m agent.app.export_contracts --check | P1-01 离线契约、Mock 轨迹与快照漂移检查；不包括旧业务服务或真实运行时验收。 |

本表及原 P1-06 验收记录只覆盖本地模拟身份；在该验收范围内，真实 Supabase positive Auth 未验证。已知本机 seed 登录的上游结果为 HTTP 500 且 `confirmation_token` 为 NULL；这是历史上游观察，不是 Agent AuthVerifier 的失败结论，也未在后续 smoke 中修复。2026-10-10 另以两个新建的本地 Auth 测试用户完成了正向身份与 A/B session owner 隔离补验收，详见[真实 Auth 报告](REAL_AUTH_SMOKE.md)。该补验收不改变生产 Scope、模型推理或业务写入的关闭状态。

## Docker 交付与静态检查

普通 Compose 服务使用 deploy/Dockerfile，构建 context 为 agent/，通过 agent/.dockerignore allowlist 排除虚拟环境、配置、数据库、测试和 acceptance fixture。Dockerfile 使用 python:3.12-slim-bookworm 与 uv 0.10.8 标签，并执行 uv sync --frozen --no-dev --no-install-project。初始静态记录时 Docker Engine 未启动，未产生镜像；2026-10-10 的实际 build、image ID 与本地 RepoDigest 已记录在实际验收证据中。

Compose 默认启动 python -m agent.app.main --workers 1，容器以 UID/GID 10001 运行，SQLite 写入独立 named volume；宿主只绑定 127.0.0.1，默认端口 8765 可通过 AGENT_HOST_PORT 调整。默认 provider disabled、Agent disabled。镜像提供合同漂移检查所需的 requirements-contracts.txt 与 toolchain-contracts.json，且真实验收 runner 会在镜像启动后运行 python -m agent.app.export_contracts --check。容器根文件系统只读；运行数据卷、/tmp tmpfs 和数据卷私有 .p1-06-tmp 是写入位置。在线备份、归档校验和恢复暂存使用磁盘支持的私有卷目录，不受 8/16 MiB tmpfs 限制。恢复 helper 通过 --network none 运行，并拒绝覆盖现有数据库或 SQLite sidecar。

静态校验记录：

- Docker CLI：29.8.2；Compose CLI：5.5.1。
- PowerShell AST parser 对 deploy/scripts/*.ps1 全部通过。
- PowerShell 输出边界的临时 stub 测试验证 Invoke-P1Docker 的空、单行、多行结果分别得到 0、1、2 个元素。该临时测试文件和临时目录已按精确路径删除。
- docker compose config --format json 对普通 Compose、simulation overlay 和 offline-recovery overlay 均通过。配置确认 context 为 agent/、Dockerfile 为 deploy/Dockerfile、宿主绑定 127.0.0.1、UID 非 root、单 worker、helper 使用只读 bind mount、offline provider 与 Agent disabled。
- 2026-10-09 当时的只读主机观察：未发现 Docker Desktop/backend 进程，`com.docker.service` 为 Stopped，`dockerDesktopLinuxEngine` pipe 不存在；截至该次观察，没有执行 compose build/up、容器 health、卷创建、容器内 SQLite 备份/恢复或 Docker 日志扫描。这是历史状态，不表示当前 Docker Engine 状态。

2026-10-09 的 Docker Desktop 启动尝试与同期诊断记录如下：当日曾尝试启动 Desktop/launcher，但由于缺失日志父目录等问题未能启动引擎；该次尝试的精确时间未保留。随后仅按精确路径创建缺失的 junction 目标/日志目录：D:\computer\Docker\data\host\Local-Docker、D:\computer\Docker\data\host\Local-Docker\log\host、D:\computer\Docker\data\host\Roaming-Docker 和 D:\computer\Docker\data\host\Roaming-Docker-Desktop。目录元数据显示 Roaming-Docker、Roaming-Docker-Desktop 与 Local-Docker 创建于 2026-10-09 11:17:56+08，Local-Docker\log\host 创建于 11:19:17+08；这些是目录修复时间，不是启动尝试时间。settings-store 与既有数据盘布局诊断后，截至当时没有再次启动 Desktop/launcher，也没有写入猜测配置。2026-10-09 检查时 Windows settings-store 不存在；当时确认 Desktop 二进制含 vm.resources.wslDataFolder 设置键，但完整 settings 序列化和安全复用第二个 VHDX 的方式未验证。本段关于进程、settings-store 和磁盘布局的内容均为 2026-10-09 历史观察，不反映当前状态。

只读日志中的 backend-state pipe 查询失败记录发生于 2026-10-09 03:35:17Z（11:35:17+08）；Test-Agent 预检证据的 `recorded_at` 为 2026-10-09 11:44:23+08。这些是各自记录的观测/记录时间，不代表早期启动尝试、settings-store 诊断或当前状态的时间。2026-10-09 检查记录显示当时 WSL distro `docker-desktop` 指向 D:\computer\DockerData\DockerDesktopWSL\main\ext4.vhdx（约 100,663,296 bytes），另一个已存在的 D:\computer\DockerData\DockerDesktopWSL\disk\docker_data.vhdx 约 16,670,261,248 bytes；这不声明当前注册或磁盘状态。任务没有重置、迁移、覆盖、注销或重指任一磁盘。

真实验收入口为 deploy/scripts/Test-Agent.ps1。2026-10-09 11:44:23+08 从独立 PowerShell 进程尝试运行其预检；当时 Docker CLI/Compose 版本可读，但 Docker Server 不可达，`dockerDesktopLinuxEngine` named pipe 不存在。该次预检在读取既有资源基线前停止，`phases` 为空、Docker Server 为 unavailable、宿主临时目录已移除且调用进程环境已恢复；当时没有执行 build/up、创建容器或卷、备份/恢复或容器验收。由于当时 Docker API 不可达，未能枚举容器和卷。A10 在这份 2026-10-09 预检中的结论是“未运行 / 阻塞”，不是 PASS；完整脱敏历史记录见 [Docker 预检证据](evidence/P1-06-Docker-20261009-114423-637306fb1414.json)，其脚本哈希对应预检当时版本，早于后续 PowerShell 5.1 参数兼容修复。[宿主与静态检查证据](evidence/P1-06-HostStatic-20261009.json)记录当时的 126 项 Python 测试、manifest/lock 检查、双 PowerShell 原生命令参数 stub 和静态 Compose 配置结果；它不是 Docker 通过证据。该段只说明 2026-10-09 的状态；其中“真实 Supabase Auth 未验证”也只是当时观察，2026-10-10 的后续状态见开头的真实 Auth 补验收报告和下文 Docker 实测。当时 P1 整体待证据汇总终审（历史状态）。

上述内容保留了 2026-10-09 预检当时的事实；2026-10-10 Docker Engine 启动后的实际结果如下。

## 2026-10-10 真实容器验收

最终证据 JSON 的 `recorded_at` 字段为 `2026-10-10T00:47:31.8495212+08:00`，是运行记录时间，不是完成时间；JSON 未记录结束时间。证据结果为 PASS。完整脱敏步骤、双端资源清单、HTTP 结果、镜像信息与 96 项部署/运行时源码 SHA-256 见[最终 Docker 验收证据](evidence/P1-06-Docker-20261010-004731-c10d607729c2.json)。该证据对应的实现包括精确 Docker inventory 比较、基线自动重启状态的有界例外、普通生产入口检查和隔离 fixture 恢复流水线；[部署脚本](../../deploy/scripts/Test-Agent.ps1)及[通用 Docker 操作](../../deploy/scripts/Deploy.Common.ps1)哈希均在证据的 `deployment_hashes` 中。

验收主机为 Docker CLI/Server `29.8.2`、Compose `5.5.1`。`agent/.dockerignore` 精确 allowlist 检出 80 个允许文件、排除 3,429 个本地文件；tests、acceptance fixture、宿主 `.venv` 和本地环境/数据路径不在普通镜像中。普通 Compose 真实启动了 `python -m agent.app.main --workers 1`；实际容器 UID/GID 为 `10001:10001`，root filesystem 为只读，并挂载独立可写 named storage volume。`/health/live` 与 `/health/ready` 为 live/ready，storage/schema ready；provider、runtime、business API 和 inference 均 disabled/unavailable。未配置 Auth 时对 `/v1/sessions` 发送 dummy bearer 值得到 HTTP `503`，没有创建服务数据。

同一隔离 project 随后 force-recreate 为 simulation fixture。镜像内 `python -m agent.app.export_contracts --check` 报告 contract snapshot matches manifest。在线 SQLite 备份为 `131,830` bytes，已校验，SHA-256 为 `0aea493b61edc2d3acc1bc63fc660966160bab3952b9d953bf37ab093cfcc87a`；在任何模拟确认之前恢复到第二个全新 project/volume。禁用 provider 与 Agent 的恢复实例成功读取持久 session、Turn、events 和待确认 proposal；Auth resume 只把等待项重新排入 `QUEUED`，取消到 `CANCELLED`，首次 confirm 返回 `409 agent_disabled` 且 proposal 投影无变化、没有 execution result。普通模拟实例的 stop/start 后需要补认证，恢复后任务完成；proposal 仍为 `WAIT_CONFIRM`，确认路由返回 `501 execution_capability_unavailable`，记录 `business_write_performed=false`。强制重建后 session、events、proposal ID 和 revision `1` 保持不变。

恢复库哨兵扫描检查了 5 张表、30 行；模拟运行库在重启后及 recreate 后各检查 5 张表、36 行，均未发现凭据哨兵。恢复实例日志和模拟实例 recreate 后日志各扫描 362 bytes，recreate 前日志扫描 1,045 bytes，均无哨兵。验收开始/结束的既有资源分别为 20 个容器、17 个卷和 7 个网络；全部 ID、卷与网络元数据未变，其他既有容器状态字段逐项完全一致。基线已处于 `restarting` 且 `unless-stopped` 的 `/supabase_vector_shared-ledger` 仍在重启，Docker 29.8.2 同时报告 `State.Running=true`；其 `RestartCount` 从 23 增至 25，`StartedAt`/`FinishedAt` 观测值变化。比较器完整保存该容器前后快照，将 `preexisting_state_unchanged` 记为 `false`，并因容器 ID/name/policy 不变、重启次数不倒退、前后状态均属于允许的 `restarting|running` 集合而将 `preexisting_resources_preserved` 记为 `true`。这些时间戳只作为观测值记录，不推断单调性或不变性。

两个随机验收 project 的容器、卷和网络在 cleanup 后均为空；GUID 宿主临时目录已移除，调用进程环境已恢复。镜像按验收约定保留。此前在 2026-10-09 Docker Engine 不可达时形成的预检文件继续作为历史证据保留，不再代表当前 A10 状态。

## 操作脚本

- [deploy/README.md](../../deploy/README.md)：PowerShell 启停、状态、备份、恢复与隔离验收操作。
- [Start-Agent.ps1](../../deploy/scripts/Start-Agent.ps1)：仅启动所选 Compose project 的 Agent 服务。
- [Stop-Agent.ps1](../../deploy/scripts/Stop-Agent.ps1)：只停止服务，不删除卷。
- [Get-AgentStatus.ps1](../../deploy/scripts/Get-AgentStatus.ps1)：分别展示 Docker 容器/健康状态及 loopback API live、ready、provider。
- [Backup-Agent.ps1](../../deploy/scripts/Backup-Agent.ps1) 与 [Restore-Agent.ps1](../../deploy/scripts/Restore-Agent.ps1)：在线备份校验和不覆盖恢复。
- [Test-Agent.ps1](../../deploy/scripts/Test-Agent.ps1)：隔离容器验收、前后资源状态比对、脱敏证据生成和精确 project 清理。
- [acceptance/README.md](../../deploy/acceptance/README.md)：专用 DI fixture 与真实 HTTP exercise 的边界和命令。

## 整体 P1 终审状态

主会话已批准 P1 限定工程范围通过：Agent 可恢复骨架、Mock Runtime、身份隔离（含本地真实 Auth 正向证据）、Docker 部署和备份恢复均已满足本阶段条件，A01–A11 无阻塞项。真实 Auth-issued 自然过期 JWT 仍为 `NOT_TESTED`；Vector 基线容器的 RestartCount 23→25 且 `preexisting_state_unchanged=false`，仅记为有界例外，不表述为全部既有状态未变。

用户确认 T0 六步已完成并推送 `1a80a0f`；Agent 本地 HEAD 和 `origin/agent` tracking ref 均为 `1a80a0f29e1ea432a60b95e7437af23d51182938`。提交含 16 个 T0/shared 文档路径，未包含 P1；未做实时 `ls-remote`。P1-01 所冻结的 API/语义/工具/轨迹协议及版本 manifest 属于 T1 已完成的协议切片；train/validation/sealed 数据集冻结、旧标签重标、Teacher availability 及模型/业务质量仍待单独验收。具体矩阵、测试命令、未测限制和证据 SHA 见[整体终审报告](FINAL_REVIEW.md)。
