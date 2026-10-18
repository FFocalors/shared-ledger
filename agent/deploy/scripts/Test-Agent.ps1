param([switch]$VerifyPreflightOnly)

. (Join-Path $PSScriptRoot 'Deploy.Common.ps1')

function Get-FreeLoopbackPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

function Write-P1EnvFile {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][int]$Port)
    $content = @(
        "AGENT_HOST_PORT=$Port",
        'AGENT_PROVIDER_MODE=disabled',
        'AGENT_AGENT_ENABLED=false',
        'AGENT_DISABLE_REVISION=1',
        'AGENT_SUPABASE_AUTH_BASE_URL=',
        'AGENT_SUPABASE_API_KEY=',
        'AGENT_ALLOW_INSECURE_LOOPBACK_AUTH_HTTP=false',
        'AGENT_CURSOR_SIGNING_SECRET=',
        'AGENT_MAX_REQUEST_BYTES=65536',
        'AGENT_API_REQUESTS_PER_MINUTE=120'
    ) -join [Environment]::NewLine
    [System.IO.File]::WriteAllText($Path, $content + [Environment]::NewLine, [System.Text.Encoding]::ASCII)
}

function Invoke-P1Exercise {
    param(
        [Parameter(Mandatory)][string]$Phase,
        [Parameter(Mandatory)][int]$Port,
        [Parameter(Mandatory)][string]$EvidencePath,
        [string]$Path
    )
    $env:P1_06_BASE_URL = "http://127.0.0.1:$Port"
    $env:P1_06_EVIDENCE_PATH = $EvidencePath
    $arguments = @((Join-Path $script:DeployRoot 'acceptance\exercise.py'), $Phase)
    if ($Path) { $arguments += @('--path', $Path) }
    $output = @(Invoke-P1HostPython -Arguments $arguments)
    if ($output.Count -ne 1) { throw "Acceptance helper '$Phase' did not emit exactly one result line." }
    try { $result = $output[0] | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "Acceptance helper '$Phase' emitted invalid JSON." }
    if ($result.PSObject.Properties.Name -contains 'ok' -and $result.ok -eq $false) {
        $failureCode = if ($result.PSObject.Properties.Name -contains 'failure') { [string]$result.failure } else { 'unspecified' }
        $httpStatus = if ($result.PSObject.Properties.Name -contains 'http_status') { [string]$result.http_status } else { 'none' }
        throw "Acceptance helper '$Phase' failed with code '$failureCode' (HTTP $httpStatus)."
    }
    return $result
}

function Invoke-P1ContainerExercise {
    param(
        [Parameter(Mandatory)][string]$ProjectName,
        [Parameter(Mandatory)][string]$EnvFile,
        [Parameter(Mandatory)][string]$Phase,
        [switch]$Offline
    )
    $container = Get-P1ProjectAgentContainer -ProjectName $ProjectName -EnvFile $EnvFile -Acceptance -Offline:$Offline
    $lines = @(Invoke-P1Docker -Arguments @(
        'exec', $container, 'python', '/opt/p1-06-acceptance/exercise.py', $Phase
    ))
    if ($lines.Count -ne 1) { throw "Container helper '$Phase' did not emit exactly one result line." }
    try { $result = $lines[0] | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "Container helper '$Phase' emitted invalid JSON." }
    if ($result.ok -ne $true) { throw "Container helper '$Phase' failed its redacted assertions." }
    return $result
}

function Wait-P1HttpReady {
    param([Parameter(Mandatory)][int]$Port, [Parameter(Mandatory)][string]$ExpectedProvider)
    $base = "http://127.0.0.1:$Port"
    $deadline = [DateTimeOffset]::UtcNow.AddMinutes(3)
    $delay = 1
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        try {
            $live = Invoke-RestMethod -Uri ($base + '/health/live') -Method Get -TimeoutSec 3
            $ready = Invoke-RestMethod -Uri ($base + '/health/ready') -Method Get -TimeoutSec 3
            $provider = Invoke-RestMethod -Uri ($base + '/health/provider') -Method Get -TimeoutSec 3
            if ($live.status -eq 'live' -and $live.inference_available -eq $false -and
                $ready.status -eq 'ready' -and $ready.storage_substrate_ready -eq $true -and
                $ready.schema_initialized -eq $true -and $ready.provider_status -eq $ExpectedProvider -and
                $provider.status -eq $ExpectedProvider -and $provider.inference_available -eq $false) {
                return [pscustomobject]@{
                    live = $live.status
                    ready = $ready.status
                    storage_substrate_ready = $ready.storage_substrate_ready
                    schema_initialized = $ready.schema_initialized
                    business_api_available = $ready.business_api_available
                    runtime_available = $ready.runtime_available
                    provider = $provider.status
                    inference_available = $provider.inference_available
                }
            }
        }
        catch { }
        Start-Sleep -Seconds $delay
        $delay = [Math]::Min(8, $delay * 2)
    }
    throw "HTTP readiness did not reach provider='$ExpectedProvider' on loopback port $Port within 3 minutes."
}

function Wait-P1HttpDown {
    param([Parameter(Mandatory)][int]$Port)
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/live" -Method Get -TimeoutSec 2
        }
        catch { return }
        Start-Sleep -Milliseconds 250
    }
    throw 'The isolated service endpoint remained reachable after Compose stop.'
}

function Get-P1HttpStatus {
    param([Parameter(Mandatory)][string]$Uri, [hashtable]$Headers = @{})
    try {
        $response = Invoke-WebRequest -Uri $Uri -Method Get -Headers $Headers -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        return [int]$response.StatusCode
    }
    catch {
        $httpResponse = $_.Exception.Response
        if ($null -ne $httpResponse -and $null -ne $httpResponse.StatusCode) {
            return [int]$httpResponse.StatusCode
        }
        throw 'The fail-closed HTTP probe did not receive an HTTP response.'
    }
}

function Save-P1ContainerLogsAndScan {
    param(
        [Parameter(Mandatory)][string]$ProjectName,
        [Parameter(Mandatory)][string]$EnvFile,
        [Parameter(Mandatory)][string]$OutputPath,
        [switch]$Offline
    )
    $lines = Invoke-P1Compose -ProjectName $ProjectName -EnvFile $EnvFile -Acceptance -Offline:$Offline -Command @('logs', '--no-color', '--timestamps', 'agent')
    [System.IO.File]::WriteAllText($OutputPath, ($lines -join [Environment]::NewLine), (New-Object System.Text.UTF8Encoding($false)))
    return Invoke-P1Exercise -Phase 'scan-text' -Port 0 -EvidencePath (Join-Path (Split-Path -Parent $OutputPath) 'unused-evidence.json') -Path $OutputPath
}

function Test-P1PersistedReadOnly {
    param([Parameter(Mandatory)][int]$Port, [Parameter(Mandatory)]$Evidence)
    $base = "http://127.0.0.1:$Port"
    # These fixture-only credentials stay in process memory and are never emitted.
    $headers = @{ Authorization = 'Bearer fixture-owner-a-v1' }
    $session = Invoke-RestMethod -Uri ($base + '/v1/sessions/' + $Evidence.session_id) -Headers $headers -TimeoutSec 5
    if ($session.session.session_id -ne $Evidence.session_id) { throw 'Recreated container did not read the durable session ID.' }
    $read = Invoke-RestMethod -Uri ($base + '/v1/turns/' + $Evidence.read_turn_id + '/events?after_seq=0&limit=100') -Headers $headers -TimeoutSec 5
    if ($read.turn.state -ne 'COMPLETED' -or $read.events.Count -lt 1) { throw 'Recreated container did not read durable Turn events.' }
    $expectedReadSeq = @($Evidence.before.read.eventseq)
    $actualReadSeq = @($read.events | ForEach-Object { $_.seq })
    if (($actualReadSeq -join ',') -ne ($expectedReadSeq -join ',')) { throw 'Recreated read event sequence differs from the captured durable prefix.' }
    $proposal = Invoke-RestMethod -Uri ($base + '/v1/turns/' + $Evidence.proposal_turn_id + '/events?after_seq=0&limit=100') -Headers $headers -TimeoutSec 5
    if ($proposal.turn.state -ne 'WAIT_CONFIRM' -or $proposal.events.Count -lt 1) { throw 'Recreated container did not read the pending simulation proposal.' }
    $expectedProposalSeq = @($Evidence.before.proposal.eventseq)
    $actualProposalSeq = @($proposal.events | ForEach-Object { $_.seq })
    if (($actualProposalSeq -join ',') -ne ($expectedProposalSeq -join ',')) { throw 'Recreated proposal event sequence differs from the captured durable prefix.' }
    if (@($proposal.events | Where-Object { $_.type -eq 'execution_result' }).Count -gt 0) { throw 'Recreated pending proposal contains an execution result.' }
    $cards = @($proposal.proposal_cards | Where-Object { $_.proposal_id -eq $Evidence.proposal_id })
    if ($cards.Count -ne 1 -or $cards[0].revision -ne $Evidence.proposal_revision -or
        $cards[0].status -ne 'pending' -or $cards[0].confirmation_enabled -ne $false -or
        ($cards[0].PSObject.Properties.Name -contains 'confirmation_nonce') -or
        ($cards[0].PSObject.Properties.Name -contains 'command_digest')) {
        throw 'Recreated simulation proposal ID/revision or execution-disabled card changed.'
    }
    return [pscustomobject]@{
        session_id_read = $true
        read_turn_state = $read.turn.state
        read_turn_events = $read.events.Count
        proposal_turn_state = $proposal.turn.state
        proposal_turn_events = $proposal.events.Count
        proposal_id = $cards[0].proposal_id
        proposal_revision = $cards[0].revision
        execution_result_present = $false
    }
}

function Get-ProjectResourceSummary {
    param([Parameter(Mandatory)][string]$ProjectName)
    return [pscustomobject]@{
        containers = @(Invoke-P1Docker -Arguments @('ps', '--all', '--quiet', '--filter', "label=com.docker.compose.project=$ProjectName"))
        volumes = @(Invoke-P1Docker -Arguments @('volume', 'ls', '--quiet', '--filter', "label=com.docker.compose.project=$ProjectName"))
        networks = @(Invoke-P1Docker -Arguments @('network', 'ls', '--quiet', '--filter', "label=com.docker.compose.project=$ProjectName"))
    }
}

function Test-P1ProductionImageContents {
    param([Parameter(Mandatory)][string]$ContainerId)
    $code = "import json,os,sys; absent=['/srv/agent/tests','/srv/agent/deploy/acceptance','/opt/p1-06-acceptance','/srv/agent/deploy/deploy.env','/srv/agent/.env','/srv/agent/.venv','/srv/agent/data','/srv/agent/agent.sqlite','/srv/agent/agent.sqlite3','/srv/agent/agent.db']; present=['/srv/agent/app/main.py','/srv/agent/contracts','/srv/agent/migrations','/srv/agent/.env.example','/opt/venv/bin/python']; result={'forbidden_paths_absent':all(not os.path.exists(p) for p in absent),'runtime_inputs_present':all(os.path.exists(p) for p in present),'forbidden_path_count':sum(1 for p in absent if os.path.exists(p)),'runtime_input_count':sum(1 for p in present if os.path.exists(p))}; print(json.dumps(result,separators=(',',':'))); sys.exit(0 if result['forbidden_paths_absent'] and result['runtime_inputs_present'] else 1)"
    $lines = @(Invoke-P1Docker -Arguments @('exec', $ContainerId, 'python', '-c', $code))
    if ($lines.Count -ne 1) { throw 'Production image contents probe did not emit exactly one summary line.' }
    try { $result = $lines[0] | ConvertFrom-Json -ErrorAction Stop }
    catch { throw 'Production image contents probe emitted invalid JSON.' }
    if ($result.forbidden_paths_absent -ne $true -or $result.runtime_inputs_present -ne $true) {
        throw 'The production image contains a local fixture/data path or is missing a required runtime input.'
    }
    return $result
}

function Test-P1ProductionContainerControls {
    param([Parameter(Mandatory)][string]$ContainerId)
    $lines = @(Invoke-P1Docker -Arguments @('inspect', $ContainerId))
    if ($lines.Count -eq 0) { throw 'Production container controls probe received no metadata.' }
    try { $inspection = ($lines -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop }
    catch { throw 'Production container controls probe received invalid metadata.' }
    $containers = @($inspection)
    if ($containers.Count -ne 1) { throw 'Production container controls probe did not receive one container.' }
    $container = $containers[0]
    $entrypoint = @($container.Config.Entrypoint | ForEach-Object { [string]$_ })
    $command = @($container.Config.Cmd | ForEach-Object { [string]$_ })
    $storageMounts = @($container.Mounts | Where-Object {
        $_.Destination -eq '/var/lib/shared-ledger-agent' -and $_.Type -eq 'volume' -and $_.RW -eq $true
    })
    $entrypointPassed = (($entrypoint -join ' ') -eq 'python -m agent.app.main')
    $workerPassed = ($command -contains '--workers' -and $command -contains '1')
    $userPassed = ([string]$container.Config.User -eq '10001:10001')
    $readonlyPassed = ([bool]$container.HostConfig.ReadonlyRootfs)
    $storageVolumePassed = ($storageMounts.Count -eq 1)
    if (-not ($entrypointPassed -and $workerPassed -and $userPassed -and $readonlyPassed -and $storageVolumePassed)) {
        throw 'The regular production container did not match the non-root, read-only, single-worker, storage-volume runtime controls.'
    }
    return [pscustomobject]@{
        passed = $true
        production_entrypoint = $entrypoint
        command = $command
        user = [string]$container.Config.User
        readonly_rootfs = $readonlyPassed
        writable_storage_volume_mounted = $storageVolumePassed
    }
}

function Test-P1BuildContextAllowlist {
    $agentRoot = Join-Path $script:RepoRoot 'agent'
    $ignorePath = Join-Path $agentRoot '.dockerignore'
    $expectedPatterns = @(
        '**',
        '!app/',
        '!app/*.py',
        '!contracts/',
        '!contracts/**',
        '!migrations/',
        '!migrations/*.sql',
        '!pyproject.toml',
        '!uv.lock',
        '!requirements-contracts.txt',
        '!toolchain-contracts.json',
        '!.env.example',
        '!deploy/',
        '!deploy/Dockerfile'
    )
    if (-not (Test-Path -LiteralPath $ignorePath -PathType Leaf)) { throw 'The Docker build context allowlist is missing.' }
    $patterns = @([System.IO.File]::ReadAllLines($ignorePath) | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
    if (($patterns -join "`n") -cne ($expectedPatterns -join "`n")) {
        throw 'The Docker build context allowlist no longer matches the reviewed exact pattern set.'
    }

    $allowedPathPattern = '^(app/[^/]+\.py|contracts/.+|migrations/[^/]+\.sql|pyproject\.toml|uv\.lock|requirements-contracts\.txt|toolchain-contracts\.json|\.env\.example|deploy/Dockerfile)$'
    $allFiles = @(Get-ChildItem -LiteralPath $agentRoot -File -Recurse -Force -ErrorAction Stop)
    $includedFiles = @()
    foreach ($file in $allFiles) {
        $relative = $file.FullName.Substring($agentRoot.Length + 1).Replace('\', '/')
        if ($relative -match $allowedPathPattern) { $includedFiles += $relative }
    }
    $knownExclusions = @(
        'tests/test_backup_restore.py',
        'deploy/acceptance/fixture_app.py',
        'deploy/acceptance/exercise.py',
        'deploy/deploy.env',
        '.venv/Scripts/python.exe'
    )
    $exclusionChecks = foreach ($relative in $knownExclusions) {
        [pscustomobject]@{
            path = $relative
            present_in_checkout = (Test-Path -LiteralPath (Join-Path $agentRoot ($relative.Replace('/', '\'))) -PathType Leaf)
            excluded_by_allowlist = ($relative -notmatch $allowedPathPattern)
        }
    }
    if (@($exclusionChecks | Where-Object { -not $_.excluded_by_allowlist }).Count -gt 0) {
        throw 'A test, acceptance fixture, environment file, or local runtime path is permitted by the Docker build context allowlist.'
    }
    return [pscustomobject]@{
        verified = $true
        allowlist_sha256 = (Get-FileHash -LiteralPath $ignorePath -Algorithm SHA256).Hash.ToLowerInvariant()
        approved_patterns = $patterns
        included_file_count = $includedFiles.Count
        included_files = @($includedFiles | Sort-Object)
        excluded_file_count = $allFiles.Count - $includedFiles.Count
        known_exclusions = @($exclusionChecks)
    }
}

function Assert-P1InventoryComparison {
    $stable = [pscustomobject]@{
        id = 'a' * 64; name = '/stable-agent'; state_status = 'running'; state_running = $true
        started_at = '2026-10-09T10:00:00Z'; finished_at = '0001-01-01T00:00:00Z'
        exit_code = 0; restart_count = 0; restart_policy = 'no'
    }
    $restarting = [pscustomobject]@{
        id = 'b' * 64; name = '/supabase_vector_shared-ledger'; state_status = 'restarting'; state_running = $true
        started_at = '2026-10-09T10:00:00Z'; finished_at = '2026-10-09T10:00:01Z'
        exit_code = 0; restart_count = 11; restart_policy = 'unless-stopped'
    }
    $base = [pscustomobject]@{
        containers = @($stable, $restarting)
        volumes = @([pscustomobject]@{ id = 'volume-a'; name = 'volume-a'; driver = 'local' })
        networks = @([pscustomobject]@{ id = 'network-a'; name = 'network-a'; driver = 'bridge' })
    }
    $same = Compare-P1DockerInventory -Before $base -After $base
    if (-not $same.passed -or -not $same.preexisting_state_unchanged) { throw 'Inventory comparison accepted the unchanged-control fixture incorrectly.' }

    $restartDrift = [pscustomobject]@{
        id = $restarting.id; name = $restarting.name; state_status = 'running'; state_running = $true
        started_at = '2026-10-10T00:00:00Z'; finished_at = '0001-01-01T00:00:00Z'
        exit_code = 0; restart_count = 12; restart_policy = 'unless-stopped'
    }
    $autoRestartInventory = [pscustomobject]@{
        containers = @($stable, $restartDrift); volumes = $base.volumes; networks = $base.networks
    }
    $autoRestart = Compare-P1DockerInventory -Before $base -After $autoRestartInventory
    if (-not $autoRestart.passed -or $autoRestart.preexisting_state_unchanged -or
        -not $autoRestart.restart_exception_constraints_passed -or $autoRestart.auto_restart_observations.Count -ne 1) {
        throw 'Inventory comparison did not record the bounded baseline auto-restart state drift.'
    }

    $stableRestart = [pscustomobject]@{
        id = $stable.id; name = $stable.name; state_status = 'running'; state_running = $true
        started_at = '2026-10-10T00:00:00Z'; finished_at = $stable.finished_at
        exit_code = 0; restart_count = 1; restart_policy = 'no'
    }
    $stableChangedInventory = [pscustomobject]@{
        containers = @($stableRestart, $restarting); volumes = $base.volumes; networks = $base.networks
    }
    if ((Compare-P1DockerInventory -Before $base -After $stableChangedInventory).passed) {
        throw 'Inventory comparison accepted a restarted stable container.'
    }

    $newContainer = [pscustomobject]@{
        id = 'c' * 64; name = '/unexpected'; state_status = 'running'; state_running = $true
        started_at = '2026-10-10T00:00:00Z'; finished_at = '0001-01-01T00:00:00Z'
        exit_code = 0; restart_count = 0; restart_policy = 'no'
    }
    $containerAddedInventory = [pscustomobject]@{
        containers = @($stable, $restarting, $newContainer); volumes = $base.volumes; networks = $base.networks
    }
    if ((Compare-P1DockerInventory -Before $base -After $containerAddedInventory).passed) {
        throw 'Inventory comparison accepted an added container.'
    }

    $volumeRemovedInventory = [pscustomobject]@{ containers = $base.containers; volumes = @(); networks = $base.networks }
    $volumeAddedInventory = [pscustomobject]@{
        containers = $base.containers
        volumes = @($base.volumes + [pscustomobject]@{ id = 'volume-b'; name = 'volume-b'; driver = 'local' })
        networks = $base.networks
    }
    $networkAddedInventory = [pscustomobject]@{
        containers = $base.containers; volumes = $base.volumes
        networks = @($base.networks + [pscustomobject]@{ id = 'network-b'; name = 'network-b'; driver = 'bridge' })
    }
    if ((Compare-P1DockerInventory -Before $base -After $volumeRemovedInventory).passed -or
        (Compare-P1DockerInventory -Before $base -After $volumeAddedInventory).passed -or
        (Compare-P1DockerInventory -Before $base -After $networkAddedInventory).passed) {
        throw 'Inventory comparison accepted added or removed pre-existing volumes/networks.'
    }

    $invalidRestartState = [pscustomobject]@{
        id = $restarting.id; name = $restarting.name; state_status = 'exited'; state_running = $false
        started_at = $restarting.started_at; finished_at = '2026-10-10T00:00:00Z'
        exit_code = 1; restart_count = 12; restart_policy = 'unless-stopped'
    }
    $invalidRestartInventory = [pscustomobject]@{
        containers = @($stable, $invalidRestartState); volumes = $base.volumes; networks = $base.networks
    }
    if ((Compare-P1DockerInventory -Before $base -After $invalidRestartInventory).passed) {
        throw 'Inventory comparison accepted an out-of-bounds auto-restarting container state.'
    }

    $invalidRunningFlag = [pscustomobject]@{
        id = $restarting.id; name = $restarting.name; state_status = 'running'; state_running = $false
        started_at = $restarting.started_at; finished_at = $restarting.finished_at
        exit_code = 0; restart_count = 12; restart_policy = 'unless-stopped'
    }
    $invalidRunningInventory = [pscustomobject]@{
        containers = @($stable, $invalidRunningFlag); volumes = $base.volumes; networks = $base.networks
    }
    if ((Compare-P1DockerInventory -Before $base -After $invalidRunningInventory).passed) {
        throw 'Inventory comparison accepted running status with Running=false.'
    }

    $regressedRestartCount = [pscustomobject]@{
        id = $restarting.id; name = $restarting.name; state_status = 'restarting'; state_running = $true
        started_at = $restarting.started_at; finished_at = $restarting.finished_at
        exit_code = 0; restart_count = 10; restart_policy = 'unless-stopped'
    }
    $changedRestartName = [pscustomobject]@{
        id = $restarting.id; name = '/renamed-vector'; state_status = 'restarting'; state_running = $true
        started_at = $restarting.started_at; finished_at = $restarting.finished_at
        exit_code = 0; restart_count = 12; restart_policy = 'unless-stopped'
    }
    $changedRestartPolicy = [pscustomobject]@{
        id = $restarting.id; name = $restarting.name; state_status = 'restarting'; state_running = $true
        started_at = $restarting.started_at; finished_at = $restarting.finished_at
        exit_code = 0; restart_count = 12; restart_policy = 'no'
    }
    foreach ($badRestart in @($regressedRestartCount, $changedRestartName, $changedRestartPolicy)) {
        $badRestartInventory = [pscustomobject]@{
            containers = @($stable, $badRestart); volumes = $base.volumes; networks = $base.networks
        }
        if ((Compare-P1DockerInventory -Before $base -After $badRestartInventory).passed) {
            throw 'Inventory comparison accepted a restart-count, name, or restart-policy regression.'
        }
    }

    return [pscustomobject]@{
        passed = $true
        scenarios = [ordered]@{
            unchanged_control = $true
            baseline_auto_restart_bounded_drift = $true
            stable_container_restart_rejected = $true
            container_addition_rejected = $true
            volume_addition_and_removal_rejected = $true
            network_addition_rejected = $true
            out_of_bounds_restart_state_rejected = $true
            running_status_requires_running_flag = $true
            restart_count_name_and_policy_regressions_rejected = $true
        }
    }
}

function Get-P1DeploymentHashes {
    $relativePaths = @(
        'agent/.dockerignore',
        'agent/.env.example',
        'agent/pyproject.toml',
        'agent/uv.lock',
        'agent/requirements-contracts.txt',
        'agent/toolchain-contracts.json',
        'agent/deploy/.gitignore',
        'agent/deploy/Dockerfile',
        'agent/deploy/compose.yaml',
        'agent/deploy/compose.acceptance.yaml',
        'agent/deploy/compose.offline.yaml',
        'agent/deploy/deploy.env.example',
        'agent/deploy/README.md',
        'agent/deploy/acceptance/fixture_app.py',
        'agent/deploy/acceptance/exercise.py',
        'agent/deploy/scripts/Deploy.Common.ps1',
        'agent/deploy/scripts/Start-Agent.ps1',
        'agent/deploy/scripts/Stop-Agent.ps1',
        'agent/deploy/scripts/Get-AgentStatus.ps1',
        'agent/deploy/scripts/Backup-Agent.ps1',
        'agent/deploy/scripts/Restore-Agent.ps1',
        'agent/deploy/scripts/Test-Agent.ps1'
    )
    foreach ($sourceRoot in @('agent/app', 'agent/contracts', 'agent/migrations')) {
        $rootPath = Join-Path $script:RepoRoot ($sourceRoot.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $rootPath -PathType Container)) { throw "Deployment source directory is missing: $sourceRoot" }
        foreach ($file in Get-ChildItem -LiteralPath $rootPath -File -Recurse -Force) {
            if ($sourceRoot -eq 'agent/app' -and $file.Extension -ne '.py') { continue }
            if ($sourceRoot -eq 'agent/migrations' -and $file.Extension -ne '.sql') { continue }
            $relative = $file.FullName.Substring($script:RepoRoot.Length + 1).Replace('\', '/')
            $relativePaths += $relative
        }
    }
    $hashes = [ordered]@{}
    foreach ($relative in $relativePaths) {
        $fullPath = Join-Path $script:RepoRoot ($relative.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) { throw "Deployment evidence input is missing: $relative" }
        $hashes[$relative] = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $hashes
}

if ($VerifyPreflightOnly) {
    $preflight = [ordered]@{
        inventory_comparison_stub = Assert-P1InventoryComparison
        build_context_allowlist = Test-P1BuildContextAllowlist
    }
    Write-Output (ConvertTo-Json -InputObject $preflight -Depth 8)
    return
}

$oldBaseUrl = $env:P1_06_BASE_URL
$oldEvidenceFile = $env:P1_06_EVIDENCE_PATH
$runId = [guid]::NewGuid().ToString('N')
$shortId = $runId.Substring(0, 12)
$simulationProject = "p1-06-accept-$shortId"
$restoreProject = "p1-06-restore-$shortId"
$simPort = Get-FreeLoopbackPort
$offlinePort = Get-FreeLoopbackPort
while ($offlinePort -eq $simPort) { $offlinePort = Get-FreeLoopbackPort }
$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$tempPath = Join-Path $tempBase ('shared-ledger-p1-06-' + $runId)
$docsEvidenceDir = Join-Path $script:RepoRoot 'agent\docs\p1\evidence'
$evidencePath = Join-Path $docsEvidenceDir ('P1-06-Docker-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $shortId + '.json')
$simEnvFile = Join-Path $tempPath 'simulation.env'
$offlineEnvFile = Join-Path $tempPath 'offline.env'
$helperEvidencePath = Join-Path $tempPath 'before-restart-evidence.json'
$simLogsPath1 = Join-Path $tempPath 'simulation-before-recreate.log'
$simLogsPath2 = Join-Path $tempPath 'simulation-after-recreate.log'
$offlineLogsPath = Join-Path $tempPath 'offline-recovery.log'
$backupPath = Join-Path $tempPath 'online-backup.zip'
$simTouched = $false
$restoreTouched = $false
$baseline = $null
$afterCleanup = $null
$success = $false
$failure = $null
$phases = [ordered]@{}
$runEvidence = [ordered]@{
    run_id = $runId
    recorded_at = [DateTimeOffset]::Now.ToString('o')
    timezone = [TimeZoneInfo]::Local.Id
    host = [ordered]@{
        powershell = $PSVersionTable.PSVersion.ToString()
        python = $null
        docker = $null
        docker_server = $null
        compose = $null
        context = 'desktop-linux'
    }
    projects = [ordered]@{ simulation = $simulationProject; offline_restore = $restoreProject }
    loopback_ports = [ordered]@{ simulation = $simPort; offline_restore = $offlinePort }
    production_defaults = $null
    image = $null
    deployment_hashes = $null
    preflight = $null
    backup = $null
    phases = $phases
    preexisting_resources_before = $null
    preexisting_resources_after_cleanup = $null
    preexisting_inventory_comparison = $null
    preexisting_state_unchanged = $null
    preexisting_resources_preserved = $null
    project_resources_after_cleanup = [ordered]@{}
    result = 'in_progress'
    failure = $null
}

try {
    $null = New-Item -ItemType Directory -Path $tempPath -ErrorAction Stop
    $null = New-Item -ItemType Directory -Path $docsEvidenceDir -Force -ErrorAction Stop
    Write-P1EnvFile -Path $simEnvFile -Port $simPort
    Write-P1EnvFile -Path $offlineEnvFile -Port $offlinePort
    $runEvidence.deployment_hashes = Get-P1DeploymentHashes
    $runEvidence.preflight = [ordered]@{
        inventory_comparison_stub = Assert-P1InventoryComparison
        build_context_allowlist = Test-P1BuildContextAllowlist
    }
    $hostPython = Get-P1HostPython
    $runEvidence.host.python = (& $hostPython --version | Out-String).Trim()
    $dockerVersion = Invoke-P1Docker -Arguments @('--version')
    $composeVersion = Invoke-P1Docker -Arguments @('compose', 'version', '--short')
    $runEvidence.host.docker = ($dockerVersion -join ' ').Trim()
    $runEvidence.host.compose = ($composeVersion -join ' ').Trim()
    try {
        $serverVersion = @(Invoke-P1Docker -Arguments @('version', '--format', '{{.Server.Version}}'))
        if ($serverVersion.Count -eq 1) { $runEvidence.host.docker_server = $serverVersion[0] }
    }
    catch { $runEvidence.host.docker_server = 'unavailable' }
    $engine = @(Invoke-P1Docker -Arguments @('info', '--format', 'server={{.ServerVersion}}'))
    if ($engine.Count -ne 1) { throw 'Docker Engine is unavailable through desktop-linux; no project resources were created.' }

    Assert-P1ProjectUnused -ProjectName $simulationProject
    Assert-P1ProjectUnused -ProjectName $restoreProject
    $baseline = Get-P1DockerInventory
    $runEvidence.preexisting_resources_before = $baseline
    $baselineControl = Compare-P1DockerInventory -Before $baseline -After $baseline
    if (-not $baselineControl.passed -or -not $baselineControl.preexisting_state_unchanged) {
        throw 'The read-only Docker inventory failed its self-comparison control.'
    }
    $baselineRestarting = @($baseline.containers | Where-Object {
        $_.state_status -eq 'restarting' -and @('always', 'unless-stopped', 'on-failure') -contains $_.restart_policy
    })
    $vectorBaseline = @($baselineRestarting | Where-Object { $_.name -eq '/supabase_vector_shared-ledger' })
    $runEvidence.preflight.docker_baseline_control = [ordered]@{
        self_comparison_passed = $true
        baseline_auto_restarting_count = $baselineRestarting.Count
        baseline_auto_restarting_containers = $baselineRestarting
        vector_diagnostic = if ($vectorBaseline.Count -eq 1) { $vectorBaseline[0] } else { $null }
    }

    # Validate the normal service's fail-closed defaults without echoing config.
    $prodPrefix = Get-P1ComposePrefix -ProjectName 'shared-ledger-agent-p1-06' -EnvFile (Join-Path $script:DeployRoot 'deploy.env.example')
    $prodConfigLines = Invoke-P1Docker -Arguments ($prodPrefix + @('config', '--format', 'json'))
    $prodConfig = ($prodConfigLines -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
    $prodService = $prodConfig.services.agent
    $prodEnvironment = $prodService.environment
    $published = $prodService.ports | Select-Object -First 1
    $composeText = [System.IO.File]::ReadAllText($script:ComposeFile)
    $productionDefaults = [ordered]@{
        provider_disabled = ($prodEnvironment.AGENT_PROVIDER_MODE -eq 'disabled')
        agent_disabled = ($prodEnvironment.AGENT_AGENT_ENABLED -eq 'false')
        single_worker = ($prodService.command -contains '--workers' -and $prodService.command -contains '1')
        non_root = ($prodService.user -eq '10001:10001')
        host_loopback_only = ($published.host_ip -eq '127.0.0.1')
        configurable_host_port = ($composeText -match '127\.0\.0\.1:\$\{AGENT_HOST_PORT:-8765\}:8765')
    }
    if ($productionDefaults.Values -contains $false) { throw 'Production Compose defaults failed one or more fail-closed checks.' }
    $runEvidence.production_defaults = $productionDefaults

    $simTouched = $true
    & (Join-Path $script:DeployRoot 'scripts\Start-Agent.ps1') -ProjectName $simulationProject -EnvFile $simEnvFile
    $productionHealth = Wait-P1HttpReady -Port $simPort -ExpectedProvider 'disabled'
    if ($productionHealth.live -ne 'live' -or $productionHealth.ready -ne 'ready' -or
        $productionHealth.business_api_available -ne $false -or $productionHealth.runtime_available -ne $false -or
        $productionHealth.inference_available -ne $false) {
        throw 'The regular production entrypoint did not start with Auth, runtime, and inference unavailable.'
    }
    $authProbeStatus = Get-P1HttpStatus -Uri "http://127.0.0.1:$simPort/v1/sessions" -Headers @{ Authorization = 'Bearer p1-06-disabled-auth-probe' }
    if (@(401, 503) -notcontains $authProbeStatus) {
        throw "The production entrypoint accepted an unconfigured Auth probe with HTTP $authProbeStatus."
    }
    $productionContainer = Get-P1ProjectAgentContainer -ProjectName $simulationProject -EnvFile $simEnvFile
    $productionImageContents = Test-P1ProductionImageContents -ContainerId $productionContainer
    $productionControls = Test-P1ProductionContainerControls -ContainerId $productionContainer
    $runEvidence.phases.production_entrypoint = [ordered]@{
        ordinary_compose = $true
        health = $productionHealth
        agent_disabled_by_environment = $true
        auth_probe_http_status = $authProbeStatus
        auth_probe_rejected = $true
        image_contents = $productionImageContents
        runtime_controls = $productionControls
    }

    $null = Invoke-P1Compose -ProjectName $simulationProject -EnvFile $simEnvFile -Acceptance -Command @('up', '--detach', '--build', '--force-recreate', 'agent')
    $runEvidence.phases.simulation_start = Wait-P1HttpReady -Port $simPort -ExpectedProvider 'simulation'
    $simulationContainer = Get-P1ProjectAgentContainer -ProjectName $simulationProject -EnvFile $simEnvFile -Acceptance
    $contractCheck = @(Invoke-P1Docker -Arguments @(
        'exec', $simulationContainer, 'python', '-m', 'agent.app.export_contracts', '--check'
    ))
    if ($contractCheck.Count -ne 1 -or $contractCheck[0] -notmatch '^contract snapshot matches manifest:') {
        throw 'The built image did not pass its frozen contract snapshot check.'
    }
    $runEvidence.phases.image_contract_check = [ordered]@{
        passed = $true
        result = 'contract snapshot matches manifest'
    }
    $before = Invoke-P1Exercise -Phase 'before-restart' -Port $simPort -EvidencePath $helperEvidencePath
    if (-not $before.session_id -or -not $before.auth_wait_turn_id -or -not $before.proposal_id) {
        throw 'The before-restart helper omitted required redacted persistence identifiers.'
    }
    $runEvidence.phases.before_restart = [ordered]@{
        fixture = $before.fixture
        session_id = $before.session_id
        read_turn_id = $before.read_turn_id
        proposal_turn_id = $before.proposal_turn_id
        proposal_id = $before.proposal_id
        cancel_turn_id = $before.cancel_turn_id
        auth_wait_turn_id = $before.auth_wait_turn_id
        hold_turn_id = $before.hold_turn_id
        proposal_revision = $before.proposal_revision
        proposal_waiting = ($before.before.proposal.state -eq 'WAIT_CONFIRM')
        auth_wait = ($before.before.auth_wait.wait_reason -eq 'auth_required')
        hold_running = ($before.before.hold.state -eq 'RUNNING')
    }

    $backupOutput = @(& (Join-Path $script:DeployRoot 'scripts\Backup-Agent.ps1') -ProjectName $simulationProject -EnvFile $simEnvFile -Acceptance -OutputPath $backupPath)
    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
        throw 'Online SQLite backup did not produce a verified archive.'
    }
    $runEvidence.backup = [ordered]@{
        sha256 = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = (Get-Item -LiteralPath $backupPath).Length
        verified = $true
        source = 'live SQLite connection.backup before any restore exercise'
    }

    & (Join-Path $script:DeployRoot 'scripts\Stop-Agent.ps1') -ProjectName $simulationProject -EnvFile $simEnvFile -Acceptance
    Wait-P1HttpDown -Port $simPort
    $runEvidence.phases.stop = 'stopped; endpoint unavailable; named volume retained'
    & (Join-Path $script:DeployRoot 'scripts\Start-Agent.ps1') -ProjectName $simulationProject -EnvFile $simEnvFile -Acceptance
    $runEvidence.phases.start = Wait-P1HttpReady -Port $simPort -ExpectedProvider 'simulation'

    # Restore the untouched pre-restart archive into a separate empty project before
    # running any simulation confirmation path.
    $restoreTouched = $true
    & (Join-Path $script:DeployRoot 'scripts\Restore-Agent.ps1') -BackupPath $backupPath -ProjectName $restoreProject -EnvFile $offlineEnvFile
    & (Join-Path $script:DeployRoot 'scripts\Start-Agent.ps1') -ProjectName $restoreProject -EnvFile $offlineEnvFile -Acceptance -Offline
    $runEvidence.phases.offline_restore_start = Wait-P1HttpReady -Port $offlinePort -ExpectedProvider 'disabled'
    $runEvidence.phases.offline_recovery = Invoke-P1Exercise -Phase 'offline-recovery' -Port $offlinePort -EvidencePath $helperEvidencePath
    $runEvidence.phases.offline_database_scan = Invoke-P1ContainerExercise -ProjectName $restoreProject -EnvFile $offlineEnvFile -Phase 'scan-database' -Offline
    $runEvidence.phases.offline_logs_scan = Save-P1ContainerLogsAndScan -ProjectName $restoreProject -EnvFile $offlineEnvFile -OutputPath $offlineLogsPath -Offline

    # The normal mock project proves its own durable recovery/auth semantics.
    $runEvidence.phases.simulation_after_restart = Invoke-P1Exercise -Phase 'after-restart' -Port $simPort -EvidencePath $helperEvidencePath
    $runEvidence.phases.simulation_database_scan = Invoke-P1ContainerExercise -ProjectName $simulationProject -EnvFile $simEnvFile -Phase 'scan-database'
    $runEvidence.phases.simulation_logs_scan_before_recreate = Save-P1ContainerLogsAndScan -ProjectName $simulationProject -EnvFile $simEnvFile -OutputPath $simLogsPath1

    $null = Invoke-P1Compose -ProjectName $simulationProject -EnvFile $simEnvFile -Acceptance -Command @('up', '--detach', '--force-recreate', 'agent')
    $runEvidence.phases.simulation_recreate_ready = Wait-P1HttpReady -Port $simPort -ExpectedProvider 'simulation'
    $runEvidence.phases.read_after_recreate = Test-P1PersistedReadOnly -Port $simPort -Evidence $before
    $runEvidence.phases.simulation_database_scan_after_recreate = Invoke-P1ContainerExercise -ProjectName $simulationProject -EnvFile $simEnvFile -Phase 'scan-database'
    $runEvidence.phases.simulation_logs_scan_after_recreate = Save-P1ContainerLogsAndScan -ProjectName $simulationProject -EnvFile $simEnvFile -OutputPath $simLogsPath2
    $runEvidence.image = (Invoke-P1Docker -Arguments @('image', 'inspect', '--format', '{{.Id}}|{{json .RepoDigests}}', $script:ImageName)) -join ' '

    $success = $true
}
catch {
    $failure = $_.Exception.Message
}
finally {
    foreach ($projectInfo in @(
        [pscustomobject]@{ name = $simulationProject; env = $simEnvFile; touched = $simTouched; offline = $false },
        [pscustomobject]@{ name = $restoreProject; env = $offlineEnvFile; touched = $restoreTouched; offline = $true }
    )) {
        if (-not $projectInfo.touched) { continue }
        try {
            $null = Invoke-P1Compose -ProjectName $projectInfo.name -EnvFile $projectInfo.env -Acceptance -Offline:$projectInfo.offline -Command @('down', '--volumes', '--remove-orphans')
            $resources = Get-ProjectResourceSummary -ProjectName $projectInfo.name
            $runEvidence.project_resources_after_cleanup[$projectInfo.name] = $resources
            if ($resources.containers.Count -gt 0 -or $resources.volumes.Count -gt 0 -or $resources.networks.Count -gt 0) {
                $success = $false
                if (-not $failure) { $failure = "Owned project '$($projectInfo.name)' left labeled resources after scoped cleanup." }
            }
        }
        catch {
            $success = $false
            if (-not $failure) { $failure = "Scoped cleanup failed for owned project '$($projectInfo.name)'." }
        }
    }
    if ($baseline) {
        try {
            $afterCleanup = Get-P1DockerInventory
            $runEvidence.preexisting_resources_after_cleanup = $afterCleanup
            $comparison = Compare-P1DockerInventory -Before $baseline -After $afterCleanup
            $runEvidence.preexisting_inventory_comparison = $comparison
            $runEvidence.preexisting_state_unchanged = $comparison.preexisting_state_unchanged
            $runEvidence.preexisting_resources_preserved = $comparison.preexisting_resources_preserved
            if (-not $comparison.preexisting_resources_preserved) {
                $success = $false
                if (-not $failure) { $failure = 'Pre-existing Docker resources changed outside the bounded baseline auto-restart observation.' }
            }
        }
        catch {
            $success = $false
            if (-not $failure) { $failure = 'Could not record pre-existing Docker resources after scoped cleanup.' }
        }
    }

    $tempCleanup = 'not-created'
    try {
        if (Test-Path -LiteralPath $tempPath -PathType Container) {
            $resolvedTemp = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $tempPath).Path)
            $tempPrefix = $tempBase.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
            if (-not $resolvedTemp.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
                $resolvedTemp -ne [System.IO.Path]::GetFullPath($tempPath)) {
                throw 'Refused to remove a temp path outside the generated P1-06 directory.'
            }
            Remove-Item -LiteralPath $resolvedTemp -Recurse -Force -ErrorAction Stop
            $tempCleanup = 'removed'
        }
    }
    catch {
        $tempCleanup = 'failed'
        $success = $false
        if (-not $failure) { $failure = 'Could not safely remove the generated host temp directory.' }
    }

    $environmentRestored = $true
    try {
        if ($null -eq $oldBaseUrl) { Remove-Item Env:P1_06_BASE_URL -ErrorAction SilentlyContinue }
        else { $env:P1_06_BASE_URL = $oldBaseUrl }
        if ($null -eq $oldEvidenceFile) { Remove-Item Env:P1_06_EVIDENCE_PATH -ErrorAction SilentlyContinue }
        else { $env:P1_06_EVIDENCE_PATH = $oldEvidenceFile }
    }
    catch {
        $environmentRestored = $false
        $success = $false
        if (-not $failure) { $failure = 'Could not restore the caller process P1_06 environment variables.' }
    }
    $runEvidence.host_temp_cleanup = $tempCleanup
    $runEvidence.environment_restored = $environmentRestored
    $runEvidence.result = if ($success) { 'PASS' } else { 'FAIL' }
    if ($failure) { $runEvidence.failure = $failure }
    try {
        $json = ConvertTo-Json -InputObject $runEvidence -Depth 16
        [System.IO.File]::WriteAllText($evidencePath, $json + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
    }
    catch {
        $success = $false
        if (-not $failure) { $failure = 'Could not save sanitized acceptance evidence.' }
    }
}

if (-not $success) { throw "P1-06 Docker acceptance failed: $failure; sanitized evidence: $evidencePath" }
Write-Output "P1-06 Docker acceptance PASS. Evidence: $evidencePath"
