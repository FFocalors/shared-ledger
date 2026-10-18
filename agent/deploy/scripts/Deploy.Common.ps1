Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:DeployRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:RepoRoot = (Resolve-Path (Join-Path $script:DeployRoot '..\..')).Path
$script:ComposeFile = Join-Path $script:DeployRoot 'compose.yaml'
$script:AcceptanceComposeFile = Join-Path $script:DeployRoot 'compose.acceptance.yaml'
$script:OfflineComposeFile = Join-Path $script:DeployRoot 'compose.offline.yaml'
$script:ImageName = 'shared-ledger-agent:p1-06'
$script:StoragePathInContainer = '/var/lib/shared-ledger-agent/agent.sqlite3'

function Get-P1DockerExecutable {
    $command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $candidates = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'),
        'D:\computer\Docker\resources\bin\docker.exe'
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw 'Docker CLI was not found. Install Docker Desktop or add docker.exe to PATH.'
}

$script:DockerExecutable = Get-P1DockerExecutable

function Assert-P1ProjectName {
    param([Parameter(Mandatory)][string]$ProjectName)
    if ($ProjectName -notmatch '^(shared-ledger-agent-p1-06|p1-06-[a-z0-9][a-z0-9-]{0,54})$') {
        throw 'ProjectName must be shared-ledger-agent-p1-06 or a unique p1-06-* name.'
    }
}

function Resolve-P1EnvFile {
    param([string]$EnvFile)
    if ([string]::IsNullOrWhiteSpace($EnvFile)) {
        $candidate = Join-Path $script:DeployRoot 'deploy.env'
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $candidate = Join-Path $script:DeployRoot 'deploy.env.example'
        }
        return (Resolve-Path -LiteralPath $candidate).Path
    }

    $resolved = Resolve-Path -LiteralPath $EnvFile -ErrorAction Stop
    if ((Get-Item -LiteralPath $resolved.Path).PSIsContainer) {
        throw 'EnvFile must be a file.'
    }
    return $resolved.Path
}

function Get-P1ComposePrefix {
    param(
        [Parameter(Mandatory)][string]$ProjectName,
        [string]$EnvFile,
        [switch]$Acceptance,
        [switch]$Offline
    )
    if ($Offline -and -not $Acceptance) { throw 'Offline mode requires the isolated Acceptance fixture overlay.' }
    Assert-P1ProjectName -ProjectName $ProjectName
    $resolvedEnvFile = Resolve-P1EnvFile -EnvFile $EnvFile
    $arguments = @(
        'compose', '--project-name', $ProjectName,
        '--project-directory', $script:DeployRoot,
        '--env-file', $resolvedEnvFile,
        '--file', $script:ComposeFile
    )
    if ($Acceptance) {
        if (-not (Test-Path -LiteralPath $script:AcceptanceComposeFile -PathType Leaf)) {
            throw 'Acceptance Compose overlay is missing.'
        }
        $arguments += @('--file', $script:AcceptanceComposeFile)
    }
    if ($Offline) {
        if (-not (Test-Path -LiteralPath $script:OfflineComposeFile -PathType Leaf)) {
            throw 'Offline recovery Compose overlay is missing.'
        }
        $arguments += @('--file', $script:OfflineComposeFile)
    }
    return ,$arguments
}

function Invoke-P1Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)
    # Compose interpolation must come only from the explicit --env-file. Shell
    # AGENT_/fixture vars could otherwise silently override that file.
    $savedEnvironment = @{}
    $overrides = @(Get-ChildItem Env: | Where-Object { $_.Name -match '^(AGENT_|P1_06_)' })
    foreach ($item in $overrides) {
        $savedEnvironment[$item.Name] = $item.Value
        [Environment]::SetEnvironmentVariable($item.Name, $null, 'Process')
    }
    try {
        $output = @(& $script:DockerExecutable --context desktop-linux @Arguments)
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            throw "Docker operation failed with exit code $exitCode. Check Docker Desktop and the command's scoped resources."
        }
        return $output
    }
    finally {
        foreach ($name in $savedEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($name, [string]$savedEnvironment[$name], 'Process')
        }
    }
}

function Invoke-P1Compose {
    param(
        [Parameter(Mandatory)][string]$ProjectName,
        [Parameter(Mandatory)][string[]]$Command,
        [string]$EnvFile,
        [switch]$Acceptance,
        [switch]$Offline
    )
    $prefix = Get-P1ComposePrefix -ProjectName $ProjectName -EnvFile $EnvFile -Acceptance:$Acceptance -Offline:$Offline
    $arguments = @($prefix) + @($Command)
    return Invoke-P1Docker -Arguments $arguments
}

function Assert-P1ProjectUnused {
    param([Parameter(Mandatory)][string]$ProjectName)
    Assert-P1ProjectName -ProjectName $ProjectName
    $containers = @(Invoke-P1Docker -Arguments @(
        'ps', '--all', '--quiet', '--filter', "label=com.docker.compose.project=$ProjectName"
    ))
    $volumes = @(Invoke-P1Docker -Arguments @(
        'volume', 'ls', '--quiet', '--filter', "label=com.docker.compose.project=$ProjectName"
    ))
    $networks = @(Invoke-P1Docker -Arguments @(
        'network', 'ls', '--quiet', '--filter', "label=com.docker.compose.project=$ProjectName"
    ))
    if (@($containers | Where-Object { $_.Trim() }).Count -gt 0 -or
        @($volumes | Where-Object { $_.Trim() }).Count -gt 0 -or
        @($networks | Where-Object { $_.Trim() }).Count -gt 0) {
        throw "Project '$ProjectName' already owns Docker resources; choose a new unique p1-06-* project name."
    }
}

function Get-P1ProjectAgentContainer {
    param([Parameter(Mandatory)][string]$ProjectName, [string]$EnvFile, [switch]$Acceptance, [switch]$Offline)
    $lines = @(Invoke-P1Compose -ProjectName $ProjectName -EnvFile $EnvFile -Acceptance:$Acceptance -Offline:$Offline -Command @('ps', '--quiet', 'agent'))
    $ids = @($lines | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if ($ids.Count -ne 1) { throw "Project '$ProjectName' does not have exactly one Agent container." }

    # Parse inspect JSON in memory. Avoid nested quotes inside Docker's Go
    # template arguments, which Windows PowerShell 5.1 can strip before native
    # argument binding. The captured JSON is never written to output or logs.
    $inspectionLines = @(Invoke-P1Docker -Arguments @('inspect', $ids[0]))
    if ($inspectionLines.Count -eq 0) { throw 'Docker inspect returned no container metadata.' }
    try {
        $inspection = ($inspectionLines -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw 'Docker inspect returned invalid container metadata.'
    }
    $inspectedContainers = @($inspection)
    if ($inspectedContainers.Count -ne 1) { throw 'Docker inspect did not return exactly one container.' }

    $container = $inspectedContainers[0]
    $labels = $container.Config.Labels
    $projectProperty = if ($labels) { $labels.PSObject.Properties['com.docker.compose.project'] } else { $null }
    $serviceProperty = if ($labels) { $labels.PSObject.Properties['com.docker.compose.service'] } else { $null }
    $projectLabel = if ($projectProperty) { [string]$projectProperty.Value } else { '' }
    $serviceLabel = if ($serviceProperty) { [string]$serviceProperty.Value } else { '' }
    $containerState = [string]$container.State.Status
    if ($projectLabel -ne $ProjectName -or $serviceLabel -ne 'agent') {
        throw 'Refusing to operate on a container outside this Compose project and service.'
    }
    if ($containerState -ne 'running') { throw "Agent container is '$containerState', not running." }
    return $ids[0]
}

function Get-P1HostPython {
    $candidate = Join-Path $script:RepoRoot 'agent\.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw 'The host Python runtime is missing; provision agent/.venv using the locked project instructions first.'
    }
    return $candidate
}

function Get-P1DockerInventory {
    $containerIds = @(Invoke-P1Docker -Arguments @('ps', '--all', '--no-trunc', '--quiet'))
    $containers = @()
    foreach ($id in $containerIds) {
        if (-not $id.Trim()) { continue }
        $inspection = @(Invoke-P1Docker -Arguments @(
            'inspect', '--format', '{{.Id}}|{{.Name}}|{{.State.Status}}|{{.State.Running}}|{{.State.StartedAt}}|{{.State.FinishedAt}}|{{.State.ExitCode}}|{{.RestartCount}}|{{.HostConfig.RestartPolicy.Name}}', $id.Trim()
        ))
        if ($inspection.Count -ne 1) { throw 'Docker inventory did not return exactly one container snapshot.' }
        $parts = $inspection[0] -split '\|', 9
        if ($parts.Count -ne 9) { throw 'Docker inventory returned a malformed container snapshot.' }
        $containers += [pscustomobject]@{
            id = $parts[0].ToLowerInvariant()
            name = $parts[1]
            state_status = $parts[2]
            state_running = [System.Convert]::ToBoolean($parts[3])
            started_at = $parts[4]
            finished_at = $parts[5]
            exit_code = [int]$parts[6]
            restart_count = [int]$parts[7]
            restart_policy = $parts[8]
        }
    }
    $volumeLines = @(Invoke-P1Docker -Arguments @('volume', 'ls', '--format', '{{.Name}}|{{.Driver}}'))
    $volumes = foreach ($line in $volumeLines) {
        if (-not $line.Trim()) { continue }
        $parts = $line -split '\|', 2
        if ($parts.Count -ne 2) { throw 'Docker inventory returned a malformed volume snapshot.' }
        [pscustomobject]@{ id = $parts[0]; name = $parts[0]; driver = $parts[1] }
    }
    $networkLines = @(Invoke-P1Docker -Arguments @('network', 'ls', '--no-trunc', '--format', '{{.ID}}|{{.Name}}|{{.Driver}}'))
    $networks = foreach ($line in $networkLines) {
        if (-not $line.Trim()) { continue }
        $parts = $line -split '\|', 3
        if ($parts.Count -ne 3) { throw 'Docker inventory returned a malformed network snapshot.' }
        [pscustomobject]@{ id = $parts[0].ToLowerInvariant(); name = $parts[1]; driver = $parts[2] }
    }
    return [pscustomobject]@{
        containers = @($containers | Sort-Object id)
        volumes = @($volumes | Sort-Object id)
        networks = @($networks | Sort-Object id)
    }
}

function Compare-P1DockerInventory {
    param([Parameter(Mandatory)]$Before, [Parameter(Mandatory)]$After)

    $beforeContainers = @($Before.containers)
    $afterContainers = @($After.containers)
    $beforeVolumes = @($Before.volumes)
    $afterVolumes = @($After.volumes)
    $beforeNetworks = @($Before.networks)
    $afterNetworks = @($After.networks)
    $beforeContainerIds = @($beforeContainers | ForEach-Object { [string]$_.id } | Sort-Object)
    $afterContainerIds = @($afterContainers | ForEach-Object { [string]$_.id } | Sort-Object)
    $beforeVolumeIds = @($beforeVolumes | ForEach-Object { [string]$_.id } | Sort-Object)
    $afterVolumeIds = @($afterVolumes | ForEach-Object { [string]$_.id } | Sort-Object)
    $beforeNetworkIds = @($beforeNetworks | ForEach-Object { [string]$_.id } | Sort-Object)
    $afterNetworkIds = @($afterNetworks | ForEach-Object { [string]$_.id } | Sort-Object)
    $containerIdsUnchanged = (($beforeContainerIds -join "`n") -eq ($afterContainerIds -join "`n"))
    $volumeIdsUnchanged = (($beforeVolumeIds -join "`n") -eq ($afterVolumeIds -join "`n"))
    $networkIdsUnchanged = (($beforeNetworkIds -join "`n") -eq ($afterNetworkIds -join "`n"))

    $afterById = @{}
    foreach ($container in $afterContainers) { $afterById[[string]$container.id] = $container }
    $stableStatesUnchanged = $true
    $restartExceptionConstraintsPass = $true
    $allContainerSnapshotsExact = $containerIdsUnchanged
    $comparisons = @()
    $restartObservations = @()
    $stateFields = @('name', 'state_status', 'state_running', 'started_at', 'finished_at', 'exit_code', 'restart_count', 'restart_policy')
    $autoRestartPolicies = @('always', 'unless-stopped', 'on-failure')

    foreach ($beforeContainer in $beforeContainers) {
        $id = [string]$beforeContainer.id
        if (-not $afterById.ContainsKey($id)) {
            $allContainerSnapshotsExact = $false
            $stableStatesUnchanged = $false
            $comparisons += [pscustomobject]@{
                id = $id
                classification = 'missing_container'
                exact_state_unchanged = $false
                preservation_check_passed = $false
                changed_fields = @('missing')
                before = $beforeContainer
                after = $null
            }
            continue
        }

        $afterContainer = $afterById[$id]
        $changedFields = @()
        foreach ($field in $stateFields) {
            if ([string]$beforeContainer.$field -cne [string]$afterContainer.$field) { $changedFields += $field }
        }
        $isBaselineAutoRestarting = ([string]$beforeContainer.state_status -eq 'restarting' -and
            $autoRestartPolicies -contains [string]$beforeContainer.restart_policy)
        if ($isBaselineAutoRestarting) {
            $stateAllowed = @('running', 'restarting') -contains [string]$afterContainer.state_status
            $runningFlagConsistent = ([string]$afterContainer.state_status -ne 'running' -or [bool]$afterContainer.state_running)
            $identityAndPolicyStable = ([string]$beforeContainer.name -ceq [string]$afterContainer.name -and
                [string]$beforeContainer.restart_policy -ceq [string]$afterContainer.restart_policy)
            $restartCountDidNotRegress = [int]$afterContainer.restart_count -ge [int]$beforeContainer.restart_count
            $restartExceptionPassed = ($stateAllowed -and $runningFlagConsistent -and $identityAndPolicyStable -and $restartCountDidNotRegress)
            if (-not $restartExceptionPassed) { $restartExceptionConstraintsPass = $false }
            if ($changedFields.Count -gt 0) { $allContainerSnapshotsExact = $false }
            $classification = if ($restartExceptionPassed -and $changedFields.Count -gt 0) {
                'baseline_auto_restarting_bounded_state_drift'
            }
            elseif ($restartExceptionPassed) {
                'baseline_auto_restarting_exact'
            }
            else {
                'baseline_auto_restarting_constraint_failed'
            }
            $comparison = [pscustomobject]@{
                id = $id
                classification = $classification
                exact_state_unchanged = ($changedFields.Count -eq 0)
                preservation_check_passed = $restartExceptionPassed
                changed_fields = $changedFields
                before = $beforeContainer
                after = $afterContainer
            }
            $comparisons += $comparison
            if ($changedFields.Count -gt 0 -or -not $restartExceptionPassed) { $restartObservations += $comparison }
            continue
        }

        $exact = ($changedFields.Count -eq 0)
        if (-not $exact) {
            $allContainerSnapshotsExact = $false
            $stableStatesUnchanged = $false
        }
        $comparisons += [pscustomobject]@{
            id = $id
            classification = if ($exact) { 'stable_exact' } else { 'unexpected_stable_container_change' }
            exact_state_unchanged = $exact
            preservation_check_passed = $exact
            changed_fields = $changedFields
            before = $beforeContainer
            after = $afterContainer
        }
    }
    foreach ($afterContainer in $afterContainers) {
        if (-not ($beforeContainerIds -contains [string]$afterContainer.id)) {
            $allContainerSnapshotsExact = $false
            $stableStatesUnchanged = $false
            $comparisons += [pscustomobject]@{
                id = [string]$afterContainer.id
                classification = 'new_container'
                exact_state_unchanged = $false
                preservation_check_passed = $false
                changed_fields = @('new')
                before = $null
                after = $afterContainer
            }
        }
    }

    $volumeMetadataUnchanged = (($beforeVolumes | ConvertTo-Json -Depth 4 -Compress) -ceq ($afterVolumes | ConvertTo-Json -Depth 4 -Compress))
    $networkMetadataUnchanged = (($beforeNetworks | ConvertTo-Json -Depth 4 -Compress) -ceq ($afterNetworks | ConvertTo-Json -Depth 4 -Compress))
    $preserved = ($containerIdsUnchanged -and $volumeIdsUnchanged -and $networkIdsUnchanged -and
        $volumeMetadataUnchanged -and $networkMetadataUnchanged -and $stableStatesUnchanged -and
        $restartExceptionConstraintsPass)
    return [pscustomobject]@{
        passed = $preserved
        preexisting_resources_preserved = $preserved
        preexisting_state_unchanged = $allContainerSnapshotsExact
        container_ids_unchanged = $containerIdsUnchanged
        volume_ids_unchanged = $volumeIdsUnchanged
        network_ids_unchanged = $networkIdsUnchanged
        volume_metadata_unchanged = $volumeMetadataUnchanged
        network_metadata_unchanged = $networkMetadataUnchanged
        stable_container_states_unchanged = $stableStatesUnchanged
        restart_exception_constraints_passed = $restartExceptionConstraintsPass
        container_comparisons = @($comparisons)
        auto_restart_observations = @($restartObservations)
    }
}

function Invoke-P1HostPython {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $python = Get-P1HostPython
    Push-Location $script:RepoRoot
    try {
        $output = @(& $python @Arguments)
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) { throw "Host Python check failed with exit code $exitCode." }
        return $output
    }
    finally {
        Pop-Location
    }
}

function Save-P1EvidenceJson {
    param([Parameter(Mandatory)]$Value, [Parameter(Mandatory)][string]$Path)
    $json = ConvertTo-Json -InputObject $Value -Depth 12
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, $encoding)
}
