# P1-06 deployment and recovery

This directory contains a single-worker Docker Compose deployment for the P1 Agent service, plus bounded PowerShell operations for status, stop/start, backup, restore, and isolated acceptance. The build context is the `agent/` directory. Its root `.dockerignore` is an allowlist; local virtual environments, tests, acceptance helpers, environment files, databases, and unrelated checkout data are excluded from the image.

The regular image starts `python -m agent.app.main --workers 1` as UID/GID `10001`. Compose publishes the service only at host `127.0.0.1`, defaults to host port `8765`, and stores SQLite under the named `agent-data` volume. Inside the container Uvicorn listens on `0.0.0.0:8765`. The provider and Agent are disabled by default. Model inference is always unavailable in this P1 build, and proposal confirmation has no business-write adapter.

## Start and inspect

Run the commands from PowerShell. The scripts resolve paths relative to themselves and use the Docker Desktop Linux context explicitly.

```powershell
Copy-Item .\agent\deploy\deploy.env.example .\agent\deploy\deploy.env
.\agent\deploy\scripts\Start-Agent.ps1
.\agent\deploy\scripts\Get-AgentStatus.ps1
```

Edit only the ignored `deploy.env` for local Compose inputs. Keep real credentials out of source control and shell history. Leave `AGENT_PROVIDER_MODE=disabled` and `AGENT_AGENT_ENABLED=false` unless a separately reviewed phase explicitly authorizes a change. A configured-but-disabled provider is expected; `/health/ready` reports storage readiness separately from provider state, and all health responses report `inference_available=false`.

`AGENT_HOST_PORT` changes the published host port without changing the container port. The default bind is `127.0.0.1`; the service is not published on LAN interfaces. `Get-AgentStatus.ps1` reports Compose container state and health, then separately queries `/health/live`, `/health/ready`, and `/health/provider` on loopback. It prints only selected status fields, not environment values or credentials. Use `-HostPort <port>` when probing an explicitly selected port, and `-Acceptance` / `-Offline` only with the isolated test overlays.

```powershell
.\agent\deploy\scripts\Stop-Agent.ps1
.\agent\deploy\scripts\Start-Agent.ps1
```

Stopping the service leaves its named volume in place. The configured 15-second stop grace period exceeds the service's bounded two-second runtime shutdown setting and leaves time for Uvicorn and SQLite lifecycle cleanup. Docker health checks call the local readiness endpoint after a 15-second startup allowance, every 10 seconds, with a three-second timeout and six retries.

## Back up and restore

Choose an existing host directory and a new, absolute archive path. `Backup-Agent.ps1` runs SQLite's online backup from the live container, writes its staged database and single-file ZIP into the private data-volume temp directory, copies the ZIP to the host, verifies it with the locked host Python runtime, and reports its SHA-256. It refuses to overwrite an existing host file. Backups contain the Agent SQLite database only; they do not include environment configuration, credentials, model assets, or other checkout data.

```powershell
.\agent\deploy\scripts\Backup-Agent.ps1 `
  -OutputPath 'D:\agent-backups\shared-ledger-agent-2026-10-09.zip'
```

Restore always targets a fresh Compose project and a new, empty named volume. It verifies the archive in an isolated `--network none` helper using a unique disk-backed scratch volume, then restores to an absent database path without overwriting any database or SQLite sidecar. The app remains stopped until explicitly started. A successful restore leaves the new project volume available for inspection and startup.

```powershell
.\agent\deploy\scripts\Restore-Agent.ps1 `
  -BackupPath 'D:\agent-backups\shared-ledger-agent-2026-10-09.zip' `
  -ProjectName 'p1-06-restore-manual-20261009'
.\agent\deploy\scripts\Start-Agent.ps1 `
  -ProjectName 'p1-06-restore-manual-20261009'
.\agent\deploy\scripts\Get-AgentStatus.ps1 `
  -ProjectName 'p1-06-restore-manual-20261009'
```

Restore refuses a project that already has labeled Compose resources. It does not prune Docker resources or remove an existing volume. Keep the archive hash with the operational record and store the archive separately from the Docker volume.

## Isolated container acceptance

With Docker Desktop's Linux engine ready and `agent/.venv/Scripts/python.exe` provisioned from the checked-in lock, run:

```powershell
.\agent\deploy\scripts\Test-Agent.ps1
```

The script chooses two fresh `p1-06-*` Compose projects and two free loopback ports. It records complete pre-existing container snapshots plus volume and network identifiers before the run, checks the normal Compose fail-closed defaults and exact build-context allowlist, then builds the image. All pre-existing IDs and volume/network IDs must remain unchanged, and stable containers must retain every captured state field. Any container that was already `restarting` under an automatic restart policy at baseline may move between `restarting` and `running`; its ID, name and policy must stay fixed, its restart count cannot decrease, and the comparison records full before/after snapshots and changed fields. StartedAt/FinishedAt remain exact observation fields; changes are recorded without a monotonic-time assertion. In that case `preexisting_state_unchanged` is false while `preexisting_resources_preserved` records the scoped preservation check. The regular production entrypoint starts first with Agent and provider disabled; the runner checks live/readiness/provider health, unavailable inference/runtime/Auth, rejection of a dummy credential, and the actual non-root, read-only root filesystem and writable named storage volume before force-recreating the project with the fixture overlay. The simulation then exercises real HTTP state persistence, online backup, stop/start, process-local auth recovery, simulation proposal behavior, recreate, and database/log sentinel scans. The pre-mutation backup is restored into a separate empty project before any mock confirmation call; that project runs with the provider disabled and Agent disabled and verifies session/Turn/event reads, auth resume to a queued state without a worker, cancellation, and the first confirmation request rejected with `409 agent_disabled` without changing the proposal or creating an execution result.

The two projects are removed by exact Compose project name with `down --volumes --remove-orphans`; no global cleanup is used. The built image is retained. A redacted JSON result, with no raw logs or fixture credentials, is written under `agent/docs/p1/evidence/`. On failure the script reports the evidence path and removes only its GUID-named host temp directory after attempting scoped project cleanup.

The acceptance runner checks that local tests, acceptance fixture files, environment files, checkout data, and the host virtual environment are excluded from the production image. The runtime volume and locked image virtual environment remain present. The acceptance fixture lives in `acceptance/` and is excluded from the image build context. Its two fake owner tokens are test-only values; the fixture does not call Supabase, contact a model, or write to a business adapter. Passing that fixture does not establish real Supabase authentication or production authorization.

## Contract check

The image contains only the frozen contract inputs needed to run the deterministic snapshot check:

```powershell
docker --context desktop-linux exec <running-container-id> python -m agent.app.export_contracts --check
```

The check reads the copied `contracts/`, source modules, `requirements-contracts.txt`, and `toolchain-contracts.json`. It does not write the snapshot.
