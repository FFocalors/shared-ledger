# P1 整体证据汇总终审

**状态：主会话已于 2026-10-10 批准按已定义范围通过（`PASSED_LIMITED_P1_ENGINEERING`）。** A01–A11 均无阻塞性缺口；本结论仅覆盖可恢复 Agent 骨架、Mock Runtime、身份隔离（含本地真实 Auth 正向证据）、Docker 部署与备份恢复。下文保留未测限制与有界例外。

本次核对已冻结源码、历史证据并编制本报告与汇总 JSON。既有业务文件未修改；首次汇总文件误落业务 checkout，已经确认仅本次两个候选文件并精确移至 Agent checkout；最终 main 为 clean。P1 源码仍为 HEAD 之外的未跟踪/未暂存文件；未修实现、历史 JSON、共享 README/dev-status/指南/T0 文件。未执行 Supabase、模型、训练、重标或 P2/P3/P4 工作。

## 快照与最终复核

用户确认 T0 六步完成并推送 `1a80a0f`；Agent checkout 本地 HEAD 与 `origin/agent` tracking ref 均为 `1a80a0f29e1ea432a60b95e7437af23d51182938`。`git show` 与 `git ls-tree` 确认该提交仅有 16 个 T0/shared 文档路径且不包含 P1；本地 tracking 状态核验不代表实时远端查询，未执行 `ls-remote`。业务 checkout `D:/project/Android/shared-ledger` 为 `main@3f938ee6114b763e6cd3dbd10792a78c691eb526`，目前 clean；首次候选文件路径错误的两个文件已移到 Agent checkout。

| 检查 | 实际结果 | 时间（Asia/Shanghai） |
|---|---|---|
| 全量 pytest | exit 0；126 passed in 34.25s；wall 36.04s | 01:45:32.234–01:46:08.287 |
| export_contracts --check | exit 0；contract snapshot matches manifest | 01:45:32.565–01:45:34.099 |
| uv lock --check --offline --project agent | exit 0；Resolved 32 packages | 01:45:33.044–01:45:33.133 |

三项当前快照检查均在工作目录 `D:/project/Android/shared-ledger-agent` 实际运行；下列命令使用锁定的工具路径：

- `& 'D:\project\Android\shared-ledger-agent\agent\.venv\Scripts\python.exe' -m pytest agent\tests -q -p no:cacheprovider`
- `& 'D:\project\Android\shared-ledger-agent\agent\.venv\Scripts\python.exe' -m agent.app.export_contracts --check`
- `D:\computer\Hermes\uv\bin\uv.exe lock --check --offline --project agent`

第一轮已启动但 wrapper 未留存 nested exec output/session metadata，标为 ATTEMPTED_NO_RESULT：不计 PASS，也不作为最终失败。第二轮是唯一补跑，记录了 exit code、summary 与实际时间；未做第三次。历史 126 passed/26.48s 和 P1-05 的 115 passed/23.52s 保留为历史，不能与本轮 126/34.25s 混写。

## A01–A11 追溯矩阵

每项完整测试函数、历史命令、证据路径与 SHA-256、类型、范围和限制见 FINAL_REVIEW_SUMMARY.json。

| 门 | 期望 | 核心测试函数 | 类型 | 结论 |
|---|---|---|---|---|
| A01 | A/B owner隔离，伪造actor/role/scope无效 | test_routes_are_authenticated_owner_scoped_and_errors_are_frozen; test_api_owner_boundary_covers_events_cards_and_all_mutations | pytest, Mock API, 真实Supabase Auth/Agent HTTP | 满足 |
| A02 | 幂等原回执；同键不同正文/context冲突；resume去重 | test_idempotency_hashes_context_and_replays_original_typed_response; test_different_store_connections_serialize_global_submit_idempotency | pytest, SQLite多连接, Mock API | 满足 |
| A03 | 中断后状态/事件恢复，待确认不执行 | test_process_exit_before_and_after_commit_recovers_atomic_turn_and_event; test_api_auth_required_survives_restart_then_http_auth_resume_requeues_turn | SQLite故障注入pytest, MockRuntime restart/close, Docker simulation fixture stop/start/recreate | 满足 |
| A04 | 过期/缺失凭证暂停并恢复原checkpoint；execution key保持 | test_auth_resume_restores_planning_confirmation_and_same_execution_checkpoint; test_unknown_execution_recovery_keeps_key_and_does_not_starve_queued_turn | 模拟exp claim pytest, Mock AuthWait/resume, 真实正向Auth | 满足（披露限制） |
| A05 | typed refs跨重排/澄清/重启保持绑定，跨Turn不复用 | test_model_context_refs_and_evidence_resolve_to_persisted_turn_bindings; test_checkpoint_reference_and_read_result_bindings_are_append_only_across_restart | pytest, Pydantic contract, SQLite | 满足 |
| A06 | pending proposal不被查询覆盖；CAS单赢家；关闭确认无成功回执 | test_api_adjustment_auth_pause_resumes_and_retries_the_same_reserved_input; test_injected_adjust_preparer_rotates_nonce_and_confirm_gates_expiry_and_disable_revision | pytest Mock API/SQLite CAS, Docker simulation HTTP | 满足 |
| A07 | 超时/迟到输出/资源限制/取消结果有界 | test_model_timeout_keeps_gate_until_provider_finishes_and_discards_late_output; test_global_queue_limit_is_atomic_across_connections_and_rejected_key_can_retry | pytest deterministic Mock Provider/SQLite | 满足 |
| A08 | 关闭后可读/补认证/取消，拒绝新规划/确认，重开使旧提案失效 | test_api_disabled_gate_preserves_metadata_and_cancel_then_reopen_stales_old_proposal; test_agent_gate_replay_and_backend_disable_revision_scope | pytest Mock gate, Docker disabled simulation recovery | 满足 |
| A09 | 凭证/nonce不进events/model inputs/logs/receipt body；诊断脱敏 | test_remote_http_statuses_are_sanitized_and_http_errors_are_closed; test_network_failures_are_dependency_errors_not_invalid_identity | pytest, Docker simulation DB/log scan, Auth临时SQLite scan | 满足（边界披露） |
| A10 | Docker lifecycle/online backup/新卷restore；disabled下可恢复取消且无真实写 | Test-Agent.ps1; exercise.py before-restart/offline-recovery/after-restart | PowerShell AST/Compose static, pytest SQLite backup, 真实Docker | 满足（有界例外） |
| A11 | 离线协议、四语义、轨迹及非法输入拒绝 | test_all_mock_trajectories_pass_json_schema_and_source_protocol; test_semantic_boundary_is_closed_and_money_is_decimal_text | JSON Schema/OpenAPI static, pytest Pydantic+fixtures | 满足 |

边界：A03 包含 SQLite 故障注入、MockRuntime restart/close 与 simulation fixture 的真实 Docker stop/start/recreate；没有声称每个 checkpoint 都真实断电或硬杀。A09 nonce 允许存在 proposals 行；禁区是 events、logs、model inputs 和 receipt body。Docker 哨兵扫描为 simulation fixture 数据；真实 Auth helper 只报告临时 SQLite credential scan，没有 runtime log scan。

## 阶段证据及历史状态

P1-01 至 P1-06 的各自限定范围均记录完成：P1-01 11项协议测试；P1-02 累计25 passed；P1-03 39 passed；P1-04 84累计/45 focused；P1-05 115 passed/23.52s（21 core、10 API、84 prior）；P1-06 HostStatic 和 Docker 证据。当前126项复跑与完整文件manifest绑定。

- 10/09 Docker precheck 是 FAIL：Engine不可达、未进入验收phases，保留为历史而不计PASS。
- HostStatic 只证明静态项通过、容器验收blocked；28个旧source hash中25个匹配当前，deploy/README.md、Deploy.Common.ps1、Test-Agent.ps1 被10/10 Docker版本取代。
- Docker 004200 是较早PASS；采用最新004731。96/96部署源码SHA匹配。recorded_at只是记录时间，JSON没有结束时间。
- Auth 013024 是较早PASS；采用最新013323的29/29 PASS。source digest before/after/current相同；helper当前SHA为 a2fbfdc785f4d96e3ef428e46ec2464fa0d590ad89c084b7a0811f2253dacf87。

真实 Auth smoke 新建两个本地用户并验证 signup/password login/Auth /user；A创建并读取session，B list空、跨owner get 404；缺失/无效token 401；Agent disabled时 planning 409 且未落Turn。测试用户已logout/delete，临时服务和SQLite已清理。seed用户的历史 NULL confirmation_token/HTTP 500未修复。自然过期Auth-issued token是NOT_TESTED，exp=1为模拟claim。P1要求过期处理逻辑测试，不要求等待真实Auth token自然过期；该限制已披露且不阻塞定义内P1门。

Docker最终运行普通生产入口（单worker、UID/GID 10001、只读rootfs、独立卷），Provider/Agent默认关闭。在线备份131,830 bytes恢复到新卷；stop/start、offline resume/cancel、recreate保留状态，没有真实业务写。恢复库扫描5表/30行，运行库两次各5表/36行；Docker logs扫描362/1045/362 bytes无哨兵。Auth临时SQLite credential scan单独通过，没有Auth runtime log scan。

Vector基线容器原本restarting；RestartCount 23→25。证据记录 preexisting_state_unchanged=false、preexisting_resources_preserved=true，是有界例外，不能写成所有既有状态完全不变。

## T0、T1 与源码清单

T0旁线索引：agent/docs/t0/README.md记录六步完成并经根主审；4B host/Docker smoke及生命周期复核通过、模型已卸载；HF merge与F16/Q4固定输入对照完成；D盘日志归档与C盘临时hold清理完成。根复核cleanup-verification.json SHA-256 25e315f94c53414c57cafa0a493f5a6335a37e4f446616a40beabc90b0e92146。本次未重跑T0或重哈希大权重。

T1仅完成P1-01冻结的API/语义/工具/轨迹协议与版本manifest。train/validation/sealed冻结、旧标签重标和Teacher availability尚未完成/验收，不能称整个T1完成。真实Scope、模型推理和业务写入属于后续P2/P3/P4。

FINAL_REVIEW_SUMMARY.json 包含 app/tests/contracts/migrations/deploy 全部非缓存/bytecode文件单SHA（含 real_auth_smoke.py），以及 .dockerignore、.env.example、.gitignore、pyproject.toml、uv.lock、requirements-contracts.txt、toolchain-contracts.json。共 107 个文件；aggregate SHA-256 294238ae26508634226b5cc7e732ab9c06aac2574cc96bde9bc979d21fa6fd54。算法按相对路径排序后拼接 path、NUL、单文件SHA-256 hex、LF，再整体SHA-256。aggregate不含本报告、汇总JSON、docs/evidence、cache和bytecode，避免自哈希循环。P1源码未提交，快照应理解为HEAD加清单中的未跟踪文件。

交接文档与原始证据的SHA-256：

- agent/docs/p1/P1_DEVELOPMENT_PLAN.md — SHA-256 fa0685c0fcc6b4c8618bf1449e341015fec5ff5d0ec49638a631569334d901dd
- agent/docs/p1/PROTOCOL_FREEZE.md — SHA-256 eedc8203f023da0806bfbe4403be9205bb13217d7d7c387eddc1a0c189a2cbb3
- agent/docs/p1/SERVICE_SKELETON.md — SHA-256 e6d38bb56048832877d283e2c5743fc2f725137f802e67c202868a7080b77499
- agent/docs/p1/PERSISTENCE.md — SHA-256 7e63543758b972e35a78467a4f42c8f6e51969e0c9d95a5165598d5c3381899d
- agent/docs/p1/IDENTITY_API.md — SHA-256 33446fde39dcd388b926b22f8ba011abb0a995c095b902362222aa960166d935
- agent/docs/p1/MOCK_RUNTIME.md — SHA-256 6bb83c57e4b1604123a5defb9335c0d4a912022c80424eea7308fb35e32b4356
- agent/docs/p1/DEPLOYMENT_RECOVERY.md — SHA-256 ef498160f127b39cd84b9e5300e58bcd6b606e3209244e2e912acaef3e5d1203
- agent/docs/p1/REAL_AUTH_SMOKE.md — SHA-256 4272d4ba2c59d7a380efbea7f455b50102e8aa7447dd14444438e34757f4ad01
- agent/docs/p1/evidence/P1-06-HostStatic-20261009.json — SHA-256 ced37b7c45302239986e74dca57640ca4c82687c267eccff03ec1cdbde50d0d2
- agent/docs/p1/evidence/P1-06-Docker-20261009-114423-637306fb1414.json — SHA-256 51731b9be49333acda74bc93431522e3c1838eb0766c353f5a210703931f30c6
- agent/docs/p1/evidence/P1-06-Docker-20261010-004200-2131f17081c9.json — SHA-256 fe3be27183291537975243916c6065c7aeacd2554729be21244e3ef4cda70871
- agent/docs/p1/evidence/P1-06-Docker-20261010-004731-c10d607729c2.json — SHA-256 af89de2432ab102c40002043fa69342ba3c60ec483266214665e510ce97c79a0
- agent/docs/p1/evidence/P1-04-RealAuthSmoke-20261010-013024.json — SHA-256 60ee89933d8f85a85a96f50b9f2544938e3a5466bc33c10a0d3dee19d53ee60a
- agent/docs/p1/evidence/P1-04-RealAuthSmoke-20261010-013323.json — SHA-256 1846cb701837e51ad0a71aec5882b07aa717756124748e37eca9194ab9658142

## 主会话终审结论

主会话于 2026-10-10 已批准 P1 限定工程范围通过（`PASSED_LIMITED_P1_ENGINEERING`）：可恢复 Agent 骨架、Mock Runtime、身份隔离（包括本地真实 Auth 正向证据）与 Docker 部署/备份恢复；A01–A11 无阻塞性缺口。真实 Auth-issued 自然过期 JWT `NOT_TESTED`，既有 exp=1 模拟测试与 AuthWait/resume 覆盖属于本阶段已声明的限制。Vector RestartCount 23→25，`preexisting_state_unchanged=false`，`preexisting_resources_preserved=true`，是有界例外。A03 不表述为所有 checkpoint 都通过真实断电/硬杀验证；A09 nonce 可存在 proposals 行，不得进 events/logs/model inputs/receipt body。

本轮 pytest 为 126 passed in 34.25s；独立 contract export check 和 offline lock check 均 exit 0。首轮测试仅为 `ATTEMPTED_NO_RESULT`，不计 PASS；历史 126/26.48s 与本轮分开。用户确认 T0 六步完成、4B host/Docker 通过并卸载、HF/F16/Q4 固定输入对照完成、D 盘归档与 C 盘临时清理完成；用户确认 `1a80a0f` 已提交并推送，本地 tracking ref 一致，且 commit 不含 P1。P1-01 的 API/语义/工具/轨迹协议与版本 manifest 已冻结；整个 T1 的 train/validation/sealed 数据冻结、旧标签重标、Teacher availability 及模型/业务质量仍待独立验收。业务 checkout 仅有本次两个文档错路径的短暂落点；它们已移出，既有业务文件未改动，最终 main clean。
