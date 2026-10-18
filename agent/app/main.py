"""Service app factory and one-worker host entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from .api import configure_api
from .components import AppComponents, build_components
from .settings import ConfigurationError, Settings, load_settings


class ServiceStartupError(RuntimeError):
    """Sanitized dependency startup error."""


ComponentsFactory = Callable[[Settings], AppComponents]


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

    uvicorn.run(
        _SanitizedLifespanASGI(create_app(resolved_settings)),
        host=resolved_settings.listen_host,
        port=resolved_settings.listen_port,
        workers=1,
        lifespan="on",
        # Default access logs include the raw path and query string. A rejected
        # query could contain a bearer/access token, so API access logging stays off.
        access_log=False,
    )


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
    except (ServiceStartupError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
