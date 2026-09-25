"""Deterministic local FX fixture for the multi_currency focus.

The server resolves a foreign-currency expense's rate from
``public.exchange_rate_cache`` (section 15: "新外币 Expense 只有在 Activity
允许外币且有可用服务端 FX snapshot 时才能创建").  The cache is populated in
production by a sync job that talks to an external provider, which the
verification workflow must never depend on: a test that reaches the network is
neither reproducible nor safe to run unattended.

This module writes a fixed set of rates into the *local* cache, so every
foreign-currency case converts at a known rate and the whole batch is
reproducible.  It touches only the local development database: no migration, RPC
or business rule is changed, and the Runner keeps using the anon key plus the
published client RPCs as before.

Run it before a multi_currency batch:

    py -3.12 -m shared_ledger_verifier fx-fixture
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

# Fixed rates, both directions, so whichever way the server asks the answer is
# known.  The reciprocal pairs are consistent to ten decimal places.
FIXTURE_RATES: tuple[tuple[str, str, str], ...] = (
    ("EUR", "CNY", "7.8500000000"),
    ("CNY", "EUR", "0.1273885350"),
    ("USD", "CNY", "7.1200000000"),
    ("CNY", "USD", "0.1404494382"),
    ("JPY", "CNY", "0.0480000000"),
    ("CNY", "JPY", "20.8333333333"),
    ("GBP", "CNY", "9.1500000000"),
    ("CNY", "GBP", "0.1092896175"),
)
FIXTURE_OBSERVED_AT = "2026-01-02 00:00:00+00"
# ``private.resolve_fx_snapshot`` only accepts rows whose source is
# ``ECB_REFERENCE``, so the fixture stands in for the production sync job rather
# than adding a new source it would ignore.  The rates below are fixed test
# values, NOT real ECB reference rates: they exist so a case converts at a known
# rate and the batch is reproducible offline.
FIXTURE_SOURCE = "ECB_REFERENCE"
DEFAULT_CONTAINER = "supabase_db_shared-ledger"
_LOCAL_CURRENCIES = frozenset({"CNY", "EUR", "USD", "JPY", "GBP"})


class FxFixtureError(RuntimeError):
    """The local FX cache could not be seeded or read."""


def container_name() -> str:
    return os.environ.get("SUPABASE_DB_CONTAINER", "").strip() or DEFAULT_CONTAINER


def _psql(sql: str, *, container: str | None = None, timeout: float = 30.0) -> str:
    command = [
        "docker", "exec", "-i", container or container_name(),
        "psql", "-U", "postgres", "-d", "postgres",
        "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", sql,
    ]
    try:
        completed = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise FxFixtureError("docker is not available on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise FxFixtureError("the local database did not answer in time") from exc
    except subprocess.CalledProcessError as exc:
        raise FxFixtureError(
            f"the local database rejected the fixture statement: {exc.stderr.strip()[:300]}"
        ) from exc
    return completed.stdout.strip()


def _upsert_statement() -> str:
    values = ", ".join(
        f"('{base}', '{quote}', {rate}::numeric, '{FIXTURE_OBSERVED_AT}'::timestamptz, "
        f"'{FIXTURE_SOURCE}', now())"
        for base, quote, rate in FIXTURE_RATES
    )
    return (
        "insert into public.exchange_rate_cache "
        "(base_currency, quote_currency, rate, observed_at, source, updated_at) values "
        f"{values} "
        "on conflict (base_currency, quote_currency) do update set "
        "rate = excluded.rate, observed_at = excluded.observed_at, "
        "source = excluded.source, updated_at = now();"
    )


def ensure_fx_fixture(*, container: str | None = None) -> dict[str, Any]:
    """Write the fixture rates into the local cache.  Idempotent."""
    _psql(_upsert_statement(), container=container)
    return fx_fixture_status(container=container)


def fx_fixture_status(*, container: str | None = None) -> dict[str, Any]:
    """Report which fixture pairs are present in the local cache."""
    rows = _psql(
        "select base_currency || '/' || quote_currency || '=' || rate::text "
        "from public.exchange_rate_cache "
        f"where observed_at = '{FIXTURE_OBSERVED_AT}'::timestamptz order by 1;",
        container=container,
    )
    present = [row for row in rows.splitlines() if row.strip()]
    expected = {f"{base}/{quote}" for base, quote, _ in FIXTURE_RATES}
    found = {row.split("=", 1)[0] for row in present}
    return {
        "source": FIXTURE_SOURCE,
        "note": "fixed local test rates, not real ECB reference rates",
        "observed_at": FIXTURE_OBSERVED_AT,
        "expected_pairs": len(expected),
        "present_pairs": len(found),
        "rates": present,
        "ready": expected <= found,
    }


def requires_fx_fixture(focus: str) -> bool:
    """True when a focus needs a foreign-currency snapshot to be resolvable."""
    from .focus_contract import focus_spec

    spec = focus_spec(focus)
    return spec.multi_currency or spec.plan_currency != spec.base_currency


__all__ = [
    "DEFAULT_CONTAINER",
    "FIXTURE_RATES",
    "FxFixtureError",
    "container_name",
    "ensure_fx_fixture",
    "fx_fixture_status",
    "requires_fx_fixture",
]
