# P1-06 container acceptance fixture

This directory is excluded from the production image. The Docker acceptance override may mount `fixture_app.py` and `exercise.py` read-only; it launches only `fixture_app.py` as the service entry point. The production command stays `python -m agent.app.main --workers 1`. `fixture_app.py` requires `P1_06_TEST_FIXTURE=1` and an explicit mode. It uses an in-process fixture verifier with two dummy owners and a one-shot owner-A credential; it never calls Supabase or an external model provider.

The default `simulation` mode requires `AGENT_PROVIDER_MODE=mock` and `AGENT_AGENT_ENABLED=true`, and uses the deterministic mock backend/model with one Runtime worker. The separate `offline-recovery` mode requires `AGENT_PROVIDER_MODE=disabled` and `AGENT_AGENT_ENABLED=false`; it uses the disabled provider and an unimplemented, non-scheduling Runtime while retaining fixture-only owner/scope checks so existing persisted data remains readable. The production app does not import or reference this fixture.

With the image's service root (currently `/srv`), use this acceptance-only command:

```text
python /opt/p1-06-acceptance/fixture_app.py --workers 1
```

Set these acceptance-only values in the override:

```text
P1_06_TEST_FIXTURE=1
P1_06_FIXTURE_MODE=simulation
P1_06_APP_ROOT=/srv
P1_06_HOLD_SECONDS=8
AGENT_STORAGE_PATH=/var/lib/shared-ledger-agent/agent.sqlite3
AGENT_LISTEN_HOST=0.0.0.0
AGENT_LISTEN_PORT=8765
AGENT_PROVIDER_MODE=mock
AGENT_AGENT_ENABLED=true
AGENT_MOCK_MODEL_TIMEOUT_SECONDS=10
```

Publish port 8765 on host loopback. The short delay applies only to the exact request `P1-06 restart auth hold`, giving the deployment runner time to recreate the container while that turn is `RUNNING`. Keep the acceptance service at one Uvicorn worker and access logging disabled.

The host `.venv` can exercise the published HTTP endpoint. `P1_06_BASE_URL` defaults to `http://127.0.0.1:8765` and is restricted to loopback. First capture the single JSON line from `before-restart`, then recreate the container or restore the database onto a new volume and pass that JSON to `after-restart`. Both commands exit 0 on success and nonzero on a failed assertion:

```powershell
$env:P1_06_BASE_URL = 'http://127.0.0.1:8765'
$evidence = python .\agent\deploy\acceptance\exercise.py before-restart
python .\agent\deploy\acceptance\exercise.py after-restart --evidence-json $evidence
```

The `before-restart` evidence contains only opaque session, turn, and proposal IDs; event sequence/type/state projections; and counts. It includes a dedicated `auth_wait_turn_id` at `WAIT_INPUT/auth_required`, created with the fixture's one-shot dummy credential. It omits bearer and refresh credentials, request bodies, proposal nonce, digest, and prompt text. Set `P1_06_EVIDENCE_PATH` to a separate host temp path if the runner prefers a file artifact; do not place it in the database volume.

For the offline recovery check, restore/copy the captured pre-restart database to a separate new volume/project, then launch the fixture in `offline-recovery` mode with `AGENT_PROVIDER_MODE=disabled` and `AGENT_AGENT_ENABLED=false`. Do this on a fresh copy before the mock project's `after-restart` confirmation, which intentionally records the frozen 501/unavailable receipt. The offline exercise verifies provider-disabled health, session/turn/event reads, no automatic proposal advancement, owner auth-resume accepted as `QUEUED` without a worker, cancellation, and first confirmation rejected with `409 agent_disabled` while the proposal/event projection remains unchanged.

```powershell
$env:P1_06_FIXTURE_MODE = 'offline-recovery'
$env:AGENT_PROVIDER_MODE = 'disabled'
$env:AGENT_AGENT_ENABLED = 'false'
python .\agent\deploy\acceptance\exercise.py offline-recovery --evidence-json $evidence
```

`offline-recovery` uses the same redacted before snapshot. Its successful evidence reports only opaque IDs, states, event sequences, provider status, and fixed control assertions. Keep the simulation project separate so its existing `after-restart` flow remains unchanged.

If the snapshot was written through `P1_06_EVIDENCE_PATH`, the helper can read it directly without passing a JSON string on the command line:

```powershell
$env:P1_06_EVIDENCE_PATH = 'C:\temp\p1-06\before.json'
python .\agent\deploy\acceptance\exercise.py offline-recovery
```

`scan-database` performs a read-only scan of all SQLite table values, including persisted model context, for the fixed dummy credentials and confirmation placeholders. Run it inside the acceptance container after exercising:

```text
python /opt/p1-06-acceptance/exercise.py scan-database
```

The runner should capture container logs to a separate temporary file and scan that file without printing its contents:

```powershell
python .\agent\deploy\acceptance\exercise.py scan-text --path $logPath
```

These dummy credentials prove only the controlled HTTP fixture path. They are not Supabase credentials or evidence about a production Auth project. A default production container must still fail closed for missing Auth configuration and report the provider disabled; the fixture app is not used for that check.
