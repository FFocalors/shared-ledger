# P2 container CPU diagnostic status

Status recorded 2026-10-12: `HOST_CPU_SCENARIO_PASS_SYNTHETIC_ONLY`; Linux container execution is `NOT_RUN_STORAGE_UNVERIFIED`.

## Host CPU scenario

The D-only runner exercised the real `P2Runtime`, `P2BackendAdapter`, SQLite store, error-proof journal, and local fixture transport with synthetic Auth and a controlled fake provider. It made no Supabase, LM Studio, or external network requests. The fixture allowed only bounded loopback reads and provider responses.

The phase-one child completed a `read.activities` response/body and grounded activity-list control answer, a separate conversation answer, a persisted cancellation, and an interrupted read after the complete result body had been checkpointed. Phase two started a fresh Runtime over the same SQLite/journal directory. It observed the safe `WAIT_INPUT/MISSING_FIELDS` checkpoint; it made no provider/counter or backend calls, did not reset budgets, and did not treat the old volatile provenance as current. The terminal/cancel control revisions remained unchanged and no memory grants survived. This verifies this synthetic host path only; it does not prove durable Auth or provenance recovery. The child exit code `1` is expected: the parent deliberately terminated its own helper after the phase-one checkpoint. Separate P2 closed-loop expense/debt cases are in CPU integration tests and are outside this runner scenario.

Evidence is under `D:\AI\runs\shared-ledger\p2\container-cpu-plan-20261012T003903Z-55fa00ece0d54accba98c28bb0c3a3a7`. The current source-bound host attempt is `host-self-test-attempt-r2-source-20261012T0921Z` (`attempt.json` and `stdout-stderr.txt`). It exited `0` in 12.462 seconds; the raw output SHA-256 is `b467696a8a8dabb9323ea8ff94f32e043bee36589a5eaa521be77d9731653d54`. It references the 28-file source fingerprint `393fb8c4bfc48ae202c99851fe31885419c358a0f430479114114b7fca06d30e` and runner SHA-256 `01c42f5130ad8b12820fa167a7a0e1584e471a9066e9925696d1b13ca233e5a0`.

## Regression and contract check

The latest full CPU test run executed `python -B -m pytest -q agent/tests` and passed `275 tests in 89.74s` (exit `0`). Its D-only log SHA-256 is `b913b2f43c2a5de99c2500b70b3ebd693ef7f135aff5708262b40b54d099546a`; the run metadata records the exact command, interpreter, `PYTHONPATH`, and D `TEMP`, `TMP`, and pytest basetemp. The test scope excluded `agent/evaluation`, T0, and T1 execution. The read-only contract export check passed with `contract snapshot matches manifest` (exit `0`) under `export-check-r2-20261012T0935Z`.

Two earlier records remain intact. The first corrected full run had `272 passed, 3 failed`: two old MockRuntime tests exceeded their fixed four-second wait, and one token-helper assertion expected exactly five seconds rather than the bounded remaining deadline. The provider corrected only its owned assertion; the focused token suite then passed 22 tests, and the latest complete suite passed. A separate 15-second diagnostic executed the read-four and single-repair test logic without changing P1 tests or runtime. The first case reached its expected five model calls/four reads and failed state in 3.188 seconds. The repair case reached two model calls/one repair and failed state in 4.125 seconds, just beyond the original four-second waiter. This is timing evidence, not a root-cause determination; the full-suite timing risk remains recorded. The original failing logs and diagnostic are preserved under the same D evidence root.

## Docker inventory and container gate

A bounded read-only Docker CLI inventory found Docker Desktop 4.94.0 with CLI/engine 29.8.2 and the cached P1 image `shared-ledger-agent:p1-06` (`sha256:f8cc168597ded966ea53ae75ec4e8690a8098d6f4c358d2c062f729f97cf3504`). The command sequence took 5.187 seconds; version, info, and image listing succeeded, while the container-list command timed out and was terminated. No build, pull, create, start, stop, or cleanup operation was performed.

The checked Docker Desktop settings exposed no allowlisted data-disk path. Installing Docker under `D:\computer\Docker` does not establish where its backing storage resides. Therefore the D-drive bind-mount condition is unverified and no Linux container scenario may run from this evidence. Keep the status `NOT_RUN_STORAGE_UNVERIFIED`; do not infer D-backed storage or use a container until a read-only configuration check can prove it.

## Scope and remaining limits

The host scenario used fake provider and backend responses. R2 real model generation remains `0`; the 13-request SDK token-fit gate had `0/13` successful counts, with all 13 attempts ending in timeout, so fit is `UNKNOWN`. Provider owns counter diagnostics. Model service startup/load authorization does not authorize additional inference. Real Supabase Auth/Data API, RLS, and the complete live path remain `NOT_RUN_USER_DEFERRED`; capacity remains `CAP0` for further model generation until a separately reviewed preregistration.

Durable provenance and Auth restoration, continuation beyond frozen result/context limits, prepayment/refund operations, and base-currency fact rendering remain unimplemented. The facts renderer reports original-currency rows and does not calculate balances. This document does not claim full P2 acceptance, live backend acceptance, model quality, or Docker/container recovery.
