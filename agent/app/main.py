"""Service app factory and one-worker host entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from .api import configure_api
from .components import AppComponents, build_components
from .settings import ConfigurationError, Settings, load_settings


class ServiceStartupError(RuntimeError):
    """Sanitized dependency startup error."""


class InstanceLockError(ServiceStartupError):
    """Another service process already owns the storage directory."""


ComponentsFactory = Callable[[Settings], AppComponents]

# Byte offset of the OS lock region; offset 0.. holds the owner PID for diagnostics.
_LOCK_OFFSET = 4096


class _InstanceLock:
    """Exclusive, process-lifetime lock next to the SQLite store.

    The OS releases the lock automatically when the process exits, so a crashed
    instance never leaves a stale lock behind.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, _LOCK_OFFSET)
        except OSError:
            owner = ""
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                owner = os.read(fd, 32).decode("ascii", "ignore").strip()
            except OSError:
                pass
            os.close(fd)
            raise InstanceLockError(
                "another Agent instance already holds the storage lock"
                + (f" (PID {owner})" if owner.isdigit() else "")
                + "; stop it (command line '-m app.main') before starting a new one"
            ) from None
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"{os.getpid():<32}".encode("ascii"))
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            os.lseek(self._fd, _LOCK_OFFSET, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.lockf(self._fd, fcntl.LOCK_UN, 1, _LOCK_OFFSET)
        except OSError:
            pass
        finally:
            os.close(self._fd)
            self._fd = None


class _StripQueryFilter(logging.Filter):
    """Drop the query string from uvicorn access records (it may carry tokens)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (args[0], args[1], args[2].split("?", 1)[0], *args[3:])
        return True


def _dev_logging_enabled() -> bool:
    return os.environ.get("AGENT_DEV_ACCESS_LOG", "").strip() == "1"


class _SanitizedLifespanASGI:
    """Replace framework-generated lifespan traceback messages before logging."""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "lifespan":
            await self._app(scope, receive, send)
            return

        async def sanitized_send(message: dict[str, Any]) -> None:
            message_type = message.get("type")
            if message_type == "lifespan.startup.failed":
                message = {
                    "type": message_type,
                    "message": "service dependency startup failed; check local configuration and storage access",
                }
            elif message_type == "lifespan.shutdown.failed":
                message = {"type": message_type, "message": "service shutdown failed"}
            await send(message)

        await self._app(scope, receive, sanitized_send)


def create_app(
    settings: Settings | None = None,
    *,
    components_factory: ComponentsFactory = build_components,
) -> FastAPI:
    """Create an ASGI app without acquiring files, network, or model resources."""
    resolved_settings = settings if settings is not None else load_settings()
    created_components: AppComponents | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal created_components
        resources: list[Any] = []
        try:
            created_components = components_factory(resolved_settings)
            resources = [
                created_components.store,
                created_components.provider,
                created_components.backend,
                created_components.runtime,
            ]
            for resource in resources:
                await _call_lifecycle(resource.start)
        except BaseException as exc:
            app.state.components = None
            await _close_resources(resources)
            created_components = None
            if isinstance(exc, Exception):
                raise ServiceStartupError(
                    "service dependency startup failed; check local configuration and storage access"
                ) from None
            raise

        app.state.components = created_components
        try:
            yield
        finally:
            app.state.components = None
            await _close_resources(resources)
            created_components = None

    app = FastAPI(
        title="Shared Ledger Agent API",
        version="1.0.0",
        description=(
            "Frozen v1 identity and durable request APIs. The provider is disabled by default. "
            "When explicitly configured for mock mode, the bounded Runtime performs deterministic "
            "simulation planning; model inference and business execution remain unavailable."
        ),
        openapi_url="/health/openapi.json",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.components = None
    app.state.settings = resolved_settings
    configure_api(app)
    return app


async def _call_lifecycle(operation: Callable[[], Any]) -> None:
    result = operation()
    if asyncio.iscoroutine(result):
        await result


async def _close_resources(resources: Sequence[Any]) -> None:
    for resource in reversed(resources):
        try:
            await _call_lifecycle(resource.close)
        except Exception:
            # Cleanup continues and never emits exception details or local paths.
            continue


def run_server(settings: Settings | None = None, *, workers: int = 1) -> None:
    if workers != 1:
        raise ValueError("P1-02 supports exactly one worker")
    resolved_settings = settings if settings is not None else load_settings()
    import uvicorn

    lock = _InstanceLock(Path(resolved_settings.storage_path).resolve().parent / "agent.lock")
    lock.acquire()
    dev_logging = _dev_logging_enabled()
    if dev_logging:
        # Development only (set by dev-up.ps1): application INFO logs to stderr and
        # uvicorn access logs with the query string stripped.
        logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        logging.getLogger("uvicorn.access").addFilter(_StripQueryFilter())
    try:
        uvicorn.run(
            _SanitizedLifespanASGI(create_app(resolved_settings)),
            host=resolved_settings.listen_host,
            port=resolved_settings.listen_port,
            workers=1,
            lifespan="on",
            # Default access logs include the raw path and query string. A rejected
            # query could contain a bearer/access token, so API access logging stays off
            # unless AGENT_DEV_ACCESS_LOG=1, where a filter strips the query string.
            access_log=dev_logging,
        )
    finally:
        lock.release()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the P1 identity, durable API, and optional mock planning service")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    if args.workers != 1:
        parser.error("P1-02 supports exactly one worker")
    try:
        run_server(workers=1)
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except InstanceLockError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (ServiceStartupError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
