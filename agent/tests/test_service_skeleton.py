from __future__ import annotations

import sqlite3
import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.app.components import AppComponents
from agent.app.main import ServiceStartupError, _SanitizedLifespanASGI, create_app, main, run_server
from agent.app.ports import ComponentHealth, ProviderHealth
from agent.app.settings import ConfigurationError, Settings, load_settings
from agent.app.store import SQLiteAgentStore, StorageStartupError


def _settings(path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "storage_path": path,
        "listen_host": "127.0.0.1",
        "listen_port": 18765,
        "provider_mode": "disabled",
        "model_concurrency": 1,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_config_is_explicit_sanitized_and_has_no_file_side_effects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    intended = tmp_path / "not-created" / "agent.sqlite3"
    monkeypatch.setenv("AGENT_STORAGE_PATH", "")
    with pytest.raises(ConfigurationError, match="AGENT_STORAGE_PATH"):
        load_settings()
    assert not intended.parent.exists()

    settings = _settings(Path("relative") / "agent.sqlite3")
    assert settings.storage_path == (Path(__file__).resolve().parents[1] / "relative" / "agent.sqlite3").resolve()
    assert not settings.storage_path.parent.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("listen_port", 0),
        ("listen_port", 65536),
        ("provider_mode", "lmstudio"),
        ("model_concurrency", 2),
    ],
)
def test_invalid_config_is_rejected(field: str, value: Any, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _settings(tmp_path / "agent.sqlite3", **{field: value})


def test_sqlite_start_probes_configured_disk_and_rolls_back_without_schema(tmp_path: Path) -> None:
    database = tmp_path / "nested" / "agent.sqlite3"
    store = SQLiteAgentStore(database)
    assert not database.parent.exists()
    store.start()
    assert database.is_file()
    assert store.probe_ready()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"schema_migrations", "sessions", "turns", "events", "proposals"}
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]
    store.close()
    assert database.exists()


def test_storage_failure_is_sanitized_and_keeps_existing_directory(tmp_path: Path) -> None:
    configured_directory = tmp_path / "is-a-directory.sqlite3"
    configured_directory.mkdir()
    store = SQLiteAgentStore(configured_directory)
    with pytest.raises(StorageStartupError) as error:
        store.start()
    assert str(configured_directory) not in str(error.value)
    assert list(configured_directory.iterdir()) == []


def test_app_factory_and_lifespan_manage_resources_and_health(tmp_path: Path) -> None:
    database = tmp_path / "service.sqlite3"
    app = create_app(_settings(database))
    assert not database.exists()  # App construction does not acquire resources.
    unopened_client = TestClient(app)
    assert unopened_client.get("/health/live").status_code == 200
    assert unopened_client.get("/health/ready").status_code == 503
    unopened_client.close()
    assert not database.exists()

    with TestClient(app) as client:
        live = client.get("/health/live")
        assert live.status_code == 200
        assert live.json() == {
            "status": "live",
            "service": "shared-ledger-agent",
            "storage_substrate_ready": None,
            "schema_initialized": True,
            "business_api_available": False,
            "runtime_available": False,
            "inference_available": False,
        }

        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json() == {
            "status": "ready",
            "service": "shared-ledger-agent",
            "storage_substrate_ready": True,
            "schema_initialized": True,
            "business_api_available": False,
            "runtime_available": False,
            "provider_status": "disabled",
            "inference_available": False,
        }
        assert client.get("/health/provider").json() == {
            "status": "disabled",
            "inference_available": False,
            "reason": "provider_disabled",
        }
        schema = client.get("/health/openapi.json").json()
        assert schema["info"]["version"] == "1.0.0"
        assert set(schema["paths"]) == {
            "/v1/proposals/{proposal_id}/confirm", "/v1/sessions",
            "/v1/sessions/{session_id}", "/v1/sessions/{session_id}/turns",
            "/v1/turns/{turn_id}/cancel", "/v1/turns/{turn_id}/events",
            "/v1/turns/{turn_id}/resume/auth", "/v1/turns/{turn_id}/resume/clarification",
            "/v1/turns/{turn_id}/resume/proposal-adjust",
        }
        assert client.get("/sessions").status_code == 404

    assert not app.state.components
    assert database.exists()  # Normal shutdown closes resources and preserves storage.


class _UnavailableProvider:
    def start(self) -> None:
        pass

    def health(self) -> ProviderHealth:
        return ProviderHealth(status="unavailable")

    def close(self) -> None:
        pass


def test_provider_unavailable_does_not_block_storage_readiness(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "service.sqlite3")

    def factory(config: Settings) -> AppComponents:
        from agent.app.backend import UnimplementedBackendAdapter
        from agent.app.gateway import UnimplementedGateway
        from agent.app.runtime import UnimplementedRuntime
        from agent.app.store import SQLiteAgentStore

        return AppComponents(
            store=SQLiteAgentStore(config.storage_path),
            provider=_UnavailableProvider(),
            backend=UnimplementedBackendAdapter(),
            runtime=UnimplementedRuntime(),
            gateway=UnimplementedGateway(),
        )

    app = create_app(settings, components_factory=factory)
    with TestClient(app) as client:
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["provider_status"] == "unavailable"
        assert ready.json()["inference_available"] is False
        assert client.get("/health/provider").json()["status"] == "unavailable"


def test_slow_storage_probe_does_not_block_process_liveness(tmp_path: Path) -> None:
    probe_started = threading.Event()
    release_probe = threading.Event()

    class SlowStore:
        def start(self) -> None:
            pass

        def probe_ready(self) -> bool:
            probe_started.set()
            release_probe.wait(timeout=3)
            return True

        def close(self) -> None:
            pass

    def factory(_: Settings) -> AppComponents:
        from agent.app.backend import UnimplementedBackendAdapter
        from agent.app.gateway import UnimplementedGateway
        from agent.app.runtime import UnimplementedRuntime

        return AppComponents(
            store=SlowStore(),  # type: ignore[arg-type]
            provider=_UnavailableProvider(),
            backend=UnimplementedBackendAdapter(),
            runtime=UnimplementedRuntime(),
            gateway=UnimplementedGateway(),
        )

    app = create_app(_settings(tmp_path / "unused.sqlite3"), components_factory=factory)
    live_response: list[Any] = []
    with TestClient(app) as client:
        probe_thread = threading.Thread(target=lambda: client.get("/health/ready"), daemon=True)
        probe_thread.start()
        assert probe_started.wait(timeout=1)
        live_thread = threading.Thread(target=lambda: live_response.append(client.get("/health/live")), daemon=True)
        live_thread.start()
        live_thread.join(timeout=0.5)
        was_responsive = bool(live_response)
        release_probe.set()
        live_thread.join(timeout=2)
        probe_thread.join(timeout=2)
    assert was_responsive
    assert live_response[0].status_code == 200


def test_failed_lifespan_closes_every_created_component_without_leaking_error(tmp_path: Path) -> None:
    events: list[str] = []

    class Resource:
        def __init__(self, name: str, fail_start: bool = False) -> None:
            self.name = name
            self.fail_start = fail_start

        def start(self) -> None:
            events.append("start:" + self.name)
            if self.fail_start:
                raise OSError("sensitive local path and secret")

        def close(self) -> None:
            events.append("close:" + self.name)

    class Provider(_UnavailableProvider):
        def close(self) -> None:
            events.append("close:provider")

    def factory(_: Settings) -> AppComponents:
        return AppComponents(
            store=Resource("store", fail_start=True),  # type: ignore[arg-type]
            provider=Provider(),
            backend=Resource("backend"),  # type: ignore[arg-type]
            runtime=Resource("runtime"),  # type: ignore[arg-type]
            gateway=object(),  # type: ignore[arg-type]
        )

    app = create_app(_settings(tmp_path / "private.sqlite3"), components_factory=factory)
    with pytest.raises(ServiceStartupError) as error:
        with TestClient(app):
            pass
    assert "sensitive" not in str(error.value)
    assert str(tmp_path) not in str(error.value)
    assert events == [
        "start:store",
        "close:runtime",
        "close:backend",
        "close:provider",
        "close:store",
    ]
    assert app.state.components is None


def test_cancelled_startup_closes_resources_and_propagates_cancellation(tmp_path: Path) -> None:
    started = asyncio.Event()
    closed = asyncio.Event()

    class AsyncLifecycle:
        async def start(self) -> None:
            started.set()
            await asyncio.Event().wait()

        async def close(self) -> None:
            closed.set()

    class Noop:
        def start(self) -> None:
            pass

        def close(self) -> None:
            pass

        def health(self) -> ComponentHealth:
            return ComponentHealth(status="not_implemented", available=False)

    def factory(_: Settings) -> AppComponents:
        return AppComponents(
            store=AsyncLifecycle(),  # type: ignore[arg-type]
            provider=Noop(),  # type: ignore[arg-type]
            backend=Noop(),  # type: ignore[arg-type]
            runtime=Noop(),  # type: ignore[arg-type]
            gateway=Noop(),  # type: ignore[arg-type]
        )

    async def exercise() -> None:
        app = create_app(_settings(tmp_path / "unused.sqlite3"), components_factory=factory)
        startup = asyncio.create_task(app.router.lifespan_context(app).__aenter__())
        await started.wait()
        startup.cancel()
        with pytest.raises(asyncio.CancelledError):
            await startup
        assert closed.is_set()
        assert app.state.components is None

    asyncio.run(exercise())


def test_host_lifespan_wrapper_replaces_framework_traceback_message() -> None:
    async def exercise() -> list[dict[str, Any]]:
        sent: list[dict[str, Any]] = []

        async def failing_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            await send({"type": "lifespan.startup.failed", "message": "secret path and traceback"})

        async def receive() -> dict[str, Any]:
            return {"type": "lifespan.startup"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        wrapper = _SanitizedLifespanASGI(failing_app)
        await wrapper({"type": "lifespan"}, receive, send)
        return sent

    messages = asyncio.run(exercise())
    assert messages == [
        {
            "type": "lifespan.startup.failed",
            "message": "service dependency startup failed; check local configuration and storage access",
        }
    ]


def test_worker_count_is_fixed_and_cli_rejects_multiple(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import uvicorn

    observed: dict[str, Any] = {}

    def fake_run(app: Any, **kwargs: Any) -> None:
        observed.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setenv("WEB_CONCURRENCY", "8")
    run_server(_settings(tmp_path / "service.sqlite3"), workers=1)
    assert observed["workers"] == 1
    assert observed["lifespan"] == "on"
    assert observed["access_log"] is False
    with pytest.raises(ValueError, match="exactly one worker"):
        run_server(_settings(tmp_path / "service.sqlite3"), workers=2)
    with pytest.raises(SystemExit) as error:
        main(["--workers", "2"])
    assert error.value.code == 2
