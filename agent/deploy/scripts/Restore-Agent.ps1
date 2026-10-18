param(
    [Parameter(Mandatory)][string]$BackupPath,
    [Parameter(Mandatory)][string]$ProjectName,
    [string]$EnvFile
)

. (Join-Path $PSScriptRoot 'Deploy.Common.ps1')
Assert-P1ProjectName -ProjectName $ProjectName
$archivePath = (Resolve-Path -LiteralPath $BackupPath -ErrorAction Stop).Path
if ((Get-Item -LiteralPath $archivePath).PSIsContainer) { throw 'BackupPath must be a single-file backup archive.' }
Assert-P1ProjectUnused -ProjectName $ProjectName

$prefix = Get-P1ComposePrefix -ProjectName $ProjectName -EnvFile $EnvFile
$null = Invoke-P1Docker -Arguments ($prefix + @('build', 'agent'))
$archiveName = 'agent-backup-' + [guid]::NewGuid().ToString('N') + '.zip'
$volumeName = $ProjectName + '_agent-data'
$scratchVolumeName = 'p1-06-scratch-' + [guid]::NewGuid().ToString('N')
$archiveMount = "type=bind,source=$archivePath,target=/run/$archiveName,readonly"
$volumeMount = "type=volume,source=$volumeName,target=/var/lib/shared-ledger-agent"
$scratchMount = "type=volume,source=$scratchVolumeName,target=/var/lib/shared-ledger-agent/.p1-06-tmp"
$scratchCreated = $false

try {
    # Verify using an isolated, disk-backed scratch volume. The image filesystem
    # remains read-only; no size ceiling is tied to tmpfs or available RAM.
    $null = Invoke-P1Docker -Arguments @(
        'volume', 'create', '--label', "com.docker.compose.project=$ProjectName",
        '--label', 'com.docker.compose.volume=p1-06-scratch', $scratchVolumeName
    )
    $scratchCreated = $true
    $null = Invoke-P1Docker -Arguments @(
        'run', '--rm', '--network', 'none', '--read-only',
        '--user', '10001:10001', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--mount', $scratchMount, '--mount', $archiveMount,
        '--label', "com.docker.compose.project=$ProjectName", '--label', 'com.docker.compose.service=restore-verify',
        '--entrypoint', 'python', $script:ImageName,
        '-m', 'agent.app.backup', 'verify', '--backup', ("/run/" + $archiveName)
    )

    $existingProjectVolume = Invoke-P1Docker -Arguments @(
        'volume', 'ls', '--quiet', '--filter', "name=^$volumeName$"
    )
    if (@($existingProjectVolume | Where-Object { $_.Trim() }).Count -gt 0) {
        throw "Restore volume '$volumeName' already exists; refusing to replace it."
    }
    $null = Invoke-P1Docker -Arguments @(
        'volume', 'create', '--label', "com.docker.compose.project=$ProjectName",
        '--label', 'com.docker.compose.volume=agent-data', $volumeName
    )

    # Restore only into a newly-created, project-labeled empty volume. No rm -v,
    # prune, existing database overwrite, network attachment, or LM Studio access.
    $null = Invoke-P1Docker -Arguments @(
        'run', '--rm', '--network', 'none', '--read-only',
        '--user', '10001:10001', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--mount', $volumeMount, '--mount', $scratchMount, '--mount', $archiveMount,
        '--label', "com.docker.compose.project=$ProjectName", '--label', 'com.docker.compose.service=restore',
        '--entrypoint', 'python', $script:ImageName,
        '-m', 'agent.app.backup', 'restore', '--backup', ("/run/" + $archiveName),
        '--target', $script:StoragePathInContainer
    )

    $digest = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Output "Backup restored into new volume '$volumeName'. sha256=$digest"
    Write-Output "Start the Agent with Start-Agent.ps1 -ProjectName '$ProjectName' after reviewing its Compose environment."
}
finally {
    # This script created this GUID-named scratch volume; delete only that volume.
    if ($scratchCreated) {
        $null = Invoke-P1Docker -Arguments @('volume', 'rm', $scratchVolumeName)
    }
}
