"""Opt-in P1-06 container acceptance app; this file is mounted only by the test override.

The production entry point never imports this module. It accepts only an explicit,
non-Supabase fixture identity and deterministic mock components.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import threading
import uuid
from typing import Sequence


OWNER_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
OWNER_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
OWNER_A_TOKEN = "fixture-owner-a-v1"
OWNER_B_TOKEN = "fixture-owner-b-v1"
OWNER_A_ONE_SHOT_TOKEN = "fixture-owner-a-once-v1"
RESTART_HOLD_PROMPT = "P1-06 restart auth hold"


def _require_opt_in() -> None:
    if os.environ.get("P1_06_TEST_FIXTURE") != "1":
        raise RuntimeError("acceptance fixture requires P1_06_TEST_FIXTURE=1")


def _service_root() -> Path:
    raw = os.environ.get("P1_06_APP_ROOT")
    root = Path(raw).expanduser() if raw else Path.cwd()
    root = root.resolve()
    if not (root / "agent" / "app" / "main.py").is_file():
        raise RuntimeError("acceptance fixture cannot locate the service package")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def _hold_seconds(timeout_seconds: float) -> float:
    raw = os.environ.get("P1_06_HOLD_SECONDS")
    try:
        value = float(raw) if raw is not None else min(1.0, timeout_seconds / 2)
    except (TypeError, ValueError):
        raise RuntimeError("acceptance hold duration is invalid") from None
    if value <= 0 or value >= timeout_seconds - 0.1:
        raise RuntimeError("acceptance hold must be positive and shorter than the mock timeout")
    return value


class _FixtureAuth:
    """Identity simulation with stable owners and a dynamically fresh expiry."""

    configured = True

    def __init__(self) -> None:
        self._owners = {
            OWNER_A_TOKEN: OWNER_A,
            OWNER_A_ONE_SHOT_TOKEN: OWNER_A,
            OWNER_B_TOKEN: OWNER_B,
        }
        self._one_shot = frozenset({OWNER_A_ONE_SHOT_TOKEN})
        self._calls: Counter[str] = Counter()
        self._lock = threading.Lock()

    def verify_bearer(self, token: str):
        from agent.app.auth import Unauthenticated
        from agent.app.ports import Principal

        with self._lock:
            self._calls[token] += 1
            call_count = self._calls[token]
            owner = self._owners.get(token)
        if owner is None or token in self._one_shot and call_count > 1:
            raise Unauthenticated("simulated invalid or expired credential")
        return Principal(owner, datetime.now(timezone.utc) + timedelta(hours=1))


class _FixtureControl:
    def __init__(self, enabled: bool, disable_revision: int, source: str) -> None:
        self._enabled = enabled
        self._disable_revision = disable_revision
        self._source = source

    def snapshot(self):
        from agent.app.ports import AgentControlSnapshot

        return AgentControlSnapshot(
            enabled=self._enabled,
            disable_revision=self._disable_revision,
            source=self._source,
        )


class _AcceptanceMockProvider:
    """Mock-only provider with one bounded, deterministic restart hold input."""

    def __init__(self, hold_seconds: float) -> None:
        from agent.app.harness import MockModelProvider

        self._mock = MockModelProvider()
        self._hold_seconds = hold_seconds

    def start(self) -> None:
        self._mock.start()

    def health(self):
        return self._mock.health()

    async def generate(self, prompt):
        if prompt.context.input_text == RESTART_HOLD_PROMPT:
            await asyncio.sleep(self._hold_seconds)
        return await self._mock.generate(prompt)

    def close(self) -> None:
        self._mock.close()


def create_acceptance_app():
    """Build the regular API over explicitly selected fixture-only components."""
    _require_opt_in()
    _service_root()

    from agent.app.backend import MockBackendAdapter, MockScopeAuthorizer
    from agent.app.components import AppComponents
    from agent.app.gateway import UnimplementedGateway
    from agent.app.main import create_app
    from agent.app.runtime import MockRuntime, UnimplementedRuntime
    from agent.app.settings import load_settings
    from agent.app.store import SQLiteAgentStore

    settings = load_settings()
    fixture_mode = os.environ.get("P1_06_FIXTURE_MODE", "simulation")
    if fixture_mode not in {"simulation", "offline-recovery"}:
        raise RuntimeError("acceptance fixture mode is unsupported")

    auth = _FixtureAuth()
    scope = MockScopeAuthorizer()
    gateway = UnimplementedGateway()

    if fixture_mode == "simulation":
        if settings.provider_mode != "mock" or not settings.agent_enabled:
            raise RuntimeError("simulation fixture requires enabled mock settings")
        control = _FixtureControl(enabled=True, disable_revision=0, source="simulation")
        backend = MockBackendAdapter()
        provider = _AcceptanceMockProvider(_hold_seconds(settings.mock_model_timeout_seconds))

        def runtime_factory(store):
            return MockRuntime(
                store,
                provider,
                backend,
                auth,
                scope,
                control,
                task_concurrency=1,
                model_timeout_seconds=settings.mock_model_timeout_seconds,
                shutdown_timeout_seconds=settings.runtime_shutdown_timeout_seconds,
            )
    else:
        if settings.provider_mode != "disabled" or settings.agent_enabled:
            raise RuntimeError("offline-recovery fixture requires disabled provider and Agent settings")
        from agent.app.backend import UnimplementedBackendAdapter
        from agent.app.model_provider import DisabledModelProvider

        control = _FixtureControl(
            enabled=False,
            disable_revision=settings.disable_revision,
            source="acceptance_offline_recovery",
        )
        backend = UnimplementedBackendAdapter()
        provider = DisabledModelProvider()

        def runtime_factory(_store):
            return UnimplementedRuntime()

    def components_factory(_settings):
        store = SQLiteAgentStore(settings.storage_path, admission_enabled=True)
        runtime = runtime_factory(store)
        return AppComponents(
            store=store,
            provider=provider,
            backend=backend,
            runtime=runtime,
            gateway=gateway,
            auth_verifier=auth,
            scope_authorizer=scope,
            agent_control=control,
        )

    return create_app(settings, components_factory=components_factory)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the opt-in P1-06 acceptance fixture")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    if args.workers != 1:
        parser.error("the acceptance fixture supports exactly one worker")

    try:
        _require_opt_in()
        _service_root()
        from agent.app.main import _SanitizedLifespanASGI
        from agent.app.settings import load_settings
        import uvicorn

        settings = load_settings()
        app = create_acceptance_app()
        uvicorn.run(
            _SanitizedLifespanASGI(app),
            host=settings.listen_host,
            port=settings.listen_port,
            workers=1,
            lifespan="on",
            access_log=False,
        )
    except Exception:
        # Startup failures are deliberately generic; neither request credentials nor
        # the storage path belongs in container logs.
        print("P1-06 acceptance fixture startup failed; check acceptance configuration", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
