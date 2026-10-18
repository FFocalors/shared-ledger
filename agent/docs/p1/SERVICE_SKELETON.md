# P1-02 服务骨架交接

验收日期：2026-10-08（Asia/Shanghai）  
状态：实现、本地验收和主会话终审已通过（2026-10-08）。  
范围：独立服务依赖、显式配置、FastAPI app factory/lifespan、最小组件装配、health-only HTTP surface 和单 worker 宿主入口。此交接不代表身份认证、业务会话、业务 schema 或推理能力已实现。

## 文件和版本

本批新增服务代码位于 `agent/app/`：`settings.py` 负责显式配置；`ports.py` 定义 Store、ModelProvider、BackendAdapter、Runtime 和 Gateway 的窄接口；`components.py` 装配默认组件；`store.py` 提供仅用于 substrate readiness 的 SQLite 文件打开与可回滚写探测；`model_provider.py`、`backend.py`、`runtime.py`、`gateway.py` 均显式 disabled/unimplemented；`api.py` 只注册 health 路由；`main.py` 提供 app factory、lifespan 和单 worker CLI。`agent/app/__init__.py` 保持空初始化，避免导入时读取配置或启动资源。

工程与本地配置文件为 `agent/pyproject.toml`、`agent/uv.lock`、`agent/.env.example` 和 `agent/.gitignore`。依赖固定为 Python `>=3.12,<3.13`，构建环境为 Python `3.12.0`、uv `0.10.8`。直接运行依赖锁定 FastAPI `0.142.2`、Pydantic `2.13.4`、pydantic-settings `2.15.0`、Uvicorn `0.54.0`；dev 组锁定 httpx2 `2.13.0`、jsonschema `4.25.1`、pytest `8.4.2`。`uv.lock` 锁住 32 个解析包；Windows Python 3.12 同步安装/审计 30 个适用包。httpx2 用于当前 Starlette TestClient；[Starlette 官方 TestClient 文档](https://www.starlette.io/testclient/)说明普通 httpx 虽仍受支持但已弃用，并推荐 httpx2。

`agent/requirements-contracts.txt`、`agent/toolchain-contracts.json`、P1-01 协议源、`contracts/v1.0.0/` 快照和 manifest 未修改。健康 API 的 OpenAPI 独立导出于 `/health/openapi.json`，版本为 `p1-02-health-only`，不会覆盖冻结的业务协议快照。

## 配置、资源与健康语义

`AGENT_STORAGE_PATH` 是必填项，进程环境变量优先于 `agent/.env`；`.env.example` 将其设为 `./data/agent.sqlite3`。相对路径固定以 `agent/` 目录为基准，而不受服务从仓库根或 `agent/` 子目录启动的影响。解析配置和 import 不创建目录、数据库、网络连接或模型客户端。配置缺失或非法时，CLI 只输出脱敏设置名/说明。`.env`、SQLite `data/`、`.venv/` 和 `.cache/` 均由 `agent/.gitignore` 忽略。

lifespan 顺序创建组件并按相反顺序关闭。SQLite 只打开配置的磁盘文件，在短事务内写入并回滚 `PRAGMA user_version`，用来检验真实文件/目录可写；它不创建表、索引或迁移记录。启动失败和启动取消会清理已创建资源；取消原样传播。Uvicorn 宿主入口包装 lifespan 失败消息，避免框架把异常 traceback、原始错误或本地路径输出到启动日志。HTTP 请求异常没有被全局捕获或静默处理。正常关闭保留数据库文件。

| 路由 | 成功/失败含义 |
|---|---|
| `GET /health/live` | 只表示当前正在处理请求的 HTTP 进程响应，不依赖 storage/provider；live 不代表依赖 ready。宿主仍须成功完成 lifespan startup 才会开始监听；启动失败时 Uvicorn 不接收 HTTP 请求。 |
| `GET /health/ready` | 200 只表示本批 service/storage substrate 的磁盘 SQLite 可写探测成功；未启动、目录/文件不可用或锁定超时返回 503。响应始终明确 `schema_initialized=false`、`business_api_available=false`、`runtime_available=false`、`inference_available=false`。provider disabled/unavailable 不阻止 ready。 |
| `GET /health/provider` | 只返回 `disabled` 或 `unavailable` 和 `inference_available=false`；没有 LM Studio 网络探测或推理。 |
| `GET /health/openapi.json` | 仅包含上列 health 路由，版本 `p1-02-health-only`。 |

健康响应不包含本地路径、凭据或异常详情。当前未安装 AuthVerifier/owner scope；没有 session、turn、event 或 proposal API；backend 与 runtime 返回 not implemented。`model_concurrency` 固定为 1；launcher 和 `run_server()` 拒绝多 worker，且显式给 Uvicorn `workers=1`，不接受 `WEB_CONCURRENCY` 覆盖。

FastAPI 用 [官方 lifespan 机制](https://fastapi.tiangolo.com/advanced/events/)在 ASGI 进程边界获取和释放资源；[Uvicorn settings 文档](https://www.uvicorn.org/settings/)说明 worker 配置。本批入口显式配置单 worker。

## 重建和运行

以下 PowerShell 命令从仓库根目录 `D:\project\Android\shared-ledger-agent` 执行。需要可用的 Python 3.12 与 uv；服务环境独立放在 `agent/.venv`，uv 下载缓存放在 `agent/.cache/uv`，不改系统 Python、T0 环境或 P1-01 的合同依赖。

```powershell
uv --cache-dir agent/.cache/uv venv --python 3.12 agent/.venv
uv --cache-dir agent/.cache/uv sync --project agent --frozen --all-groups --python agent/.venv/Scripts/python.exe
uv --cache-dir agent/.cache/uv lock --check --project agent
```

新机器从仓库复制 `agent/uv.lock` 后只用 `--frozen` 同步，不重新解析依赖。只有维护者有意修改 `pyproject.toml` 依赖时，才从 `agent/` 目录运行 `uv lock --python 3.12 --cache-dir .cache/uv` 并审查 lock diff。`uv sync` 会安装运行和测试依赖。运行服务前复制 `agent/.env.example` 为 `agent/.env` 并按本机持久路径调整，或在进程环境设置 `AGENT_STORAGE_PATH`：

```powershell
$env:AGENT_STORAGE_PATH = '.\data\agent.sqlite3' # 相对 agent/ 目录
uv run --project agent --frozen --all-groups --python agent/.venv/Scripts/python.exe python -m agent.app.main
```

该命令只启动一个本机 health-only 服务，不连接 LM Studio。要临时指定端口，可设置 `AGENT_LISTEN_PORT`；`--workers 2` 会在启动前拒绝。

## 离线与宿主验证

从仓库根目录使用已冻结的 Python 3.12 环境：

```powershell
uv lock --check --project agent --cache-dir agent/.cache/uv
uv sync --project agent --frozen --all-groups --python agent/.venv/Scripts/python.exe --cache-dir agent/.cache/uv
uv run --project agent --frozen --all-groups --python agent/.venv/Scripts/python.exe python -m pytest agent/tests -q -p no:cacheprovider
uv run --project agent --frozen --all-groups --python agent/.venv/Scripts/python.exe python -m py_compile agent/app/settings.py agent/app/ports.py agent/app/store.py agent/app/model_provider.py agent/app/backend.py agent/app/runtime.py agent/app/gateway.py agent/app/components.py agent/app/api.py agent/app/main.py agent/tests/test_service_skeleton.py agent/app/contracts.py agent/app/mock_fixtures.py agent/app/export_contracts.py agent/tests/test_protocol_contracts.py
uv run --project agent --frozen --all-groups --python agent/.venv/Scripts/python.exe python -m agent.app.export_contracts --check
```

本次从干净 `agent/.venv` 按冻结锁重建后安装 30 个适用包；uv lock check 显示 `Resolved 32 packages`；pytest 为 `25 passed in 8.08s`；`py_compile` 成功；协议导出检查显示 `contract snapshot matches manifest: .../agent/contracts/v1.0.0`。套件包括 P1-01 的 11 项协议检查和 14 项服务检查，覆盖配置拒绝/路径无创建、SQLite 磁盘回滚且无表、未进入 lifespan 的 ASGI 测试中 ready 503 与 live 200、正常 start/close、provider disabled/unavailable、启动失败清理、启动取消、慢存储不阻塞 live、health-only OpenAPI 和单 worker。Starlette TestClient 使用锁定的 httpx2，无弃用 warning。

宿主 HTTP smoke 由真实 Uvicorn 进程运行，命令在终端 A（仓库根）执行；这个复跑使用 `WEB_CONCURRENCY=8`：

```powershell
$env:AGENT_STORAGE_PATH = '.\data\p1-02-http-smoke.sqlite3'
$env:AGENT_LISTEN_PORT = '58784'
$env:WEB_CONCURRENCY = '8'
uv run --project agent --frozen --all-groups --python agent/.venv/Scripts/python.exe python -m agent.app.main
```

Uvicorn 日志显示单个 server process。另一终端执行以下请求，服务停机后 smoke 数据库已删除：

```powershell
Invoke-RestMethod http://127.0.0.1:58784/health/live
Invoke-RestMethod http://127.0.0.1:58784/health/ready
Invoke-RestMethod http://127.0.0.1:58784/health/provider
Invoke-RestMethod http://127.0.0.1:58784/health/openapi.json
Invoke-WebRequest http://127.0.0.1:58784/sessions -SkipHttpErrorCheck
```

实际结果依次为 live 200、ready 200（`storage_substrate_ready=true`）、provider `disabled`、health OpenAPI `p1-02-health-only`、未实现的 `/sessions` 404。另以第二个 SQLite 连接持有 `BEGIN IMMEDIATE` 锁：live 仍在 80 ms 内返回 200；ready 因 2 秒磁盘 busy timeout 返回 503（本次 2289 ms）；释放锁后 ready 返回 200。`user_version` 写探测回滚后仍为原值，数据库无应用表。启动配置指向目录的失败复测以非零退出，日志只有 `service dependency startup failed; check local configuration and storage access` 与 Uvicorn 的退出提示，不含 traceback、本机路径或原始异常。主会话于 2026-10-08 独立复核：25 项测试无 warning、lock check 与协议快照 check 通过；再测 SQLite 外部锁下 live 200/ready 503/解锁后 ready 200，且无业务表或 `user_version` 变化；启动失败 CLI 退出码为 3，日志不含配置路径、原异常、`StorageStartupError` 或 traceback，临时进程和缓存已清理。主会话对源码终审通过。

## 边界与 P1-03 续接

此批不实现四表、schema migration、CRUD、请求队列、业务路由、身份认证/归属授权、模型推理、真实 BackendAdapter、真实业务写入或部署容器。readiness 不代表数据库业务 schema 可用，provider 路由不代表推理可用；没有运行 API 安全或真实业务验收。P1-01 固定 OpenAPI 不被运行时 health schema 覆盖。

下一批 P1-03 实现四表持久化、事务/唯一约束、事件、请求回执和条件状态更新。P1-03 应复用本批 Settings/lifespan/AgentStore 接口，在迁移前明确验证已有 SQLite substrate；身份与 owner scope 仍属 P1-04，不随 store 骨架提前开放。P1-02 通过不代表 P1-03 至 P1-06 或其他 P1 运行验收已完成。
