param(
    [Parameter(Mandatory)][string]$OutputPath,
    [string]$ProjectName = 'shared-ledger-agent-p1-06',
    [string]$EnvFile,
    [switch]$Acceptance
)

. (Join-Path $PSScriptRoot 'Deploy.Common.ps1')
$outputFullPath = [System.IO.Path]::GetFullPath($OutputPath)
$outputParent = Split-Path -Parent $outputFullPath
if (-not (Test-Path -LiteralPath $outputParent -PathType Container)) { throw 'The backup output directory must already exist.' }
if (Test-Path -LiteralPath $outputFullPath) { throw 'The backup output already exists; choose a new path to avoid overwriting it.' }

$container = Get-P1ProjectAgentContainer -ProjectName $ProjectName -EnvFile $EnvFile -Acceptance:$Acceptance
$temporaryName = '.p1-06-backup-' + [guid]::NewGuid().ToString('N') + '.zip'
$containerPath = $script:StoragePathInContainer.Replace('/agent.sqlite3', '/.p1-06-tmp/' + $temporaryName)
$createdHostFile = $false
try {
    $null = Invoke-P1Docker -Arguments @(
        'exec', $container, 'python', '-m', 'agent.app.backup',
        'backup', '--source', $script:StoragePathInContainer, '--output', $containerPath
    )
    $createdHostFile = $true
    $null = Invoke-P1Docker -Arguments @('cp', ($container + ':' + $containerPath), $outputFullPath)
    if (-not (Test-Path -LiteralPath $outputFullPath -PathType Leaf)) { throw 'Docker did not publish the requested backup artifact.' }

    $verification = @(Invoke-P1HostPython -Arguments @('-m', 'agent.app.backup', 'verify', '--backup', $outputFullPath))
    $hash = (Get-FileHash -LiteralPath $outputFullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Output "Backup created and verified. sha256=$hash path=$outputFullPath"
}
catch {
    if ($createdHostFile -and (Test-Path -LiteralPath $outputFullPath)) {
        Remove-Item -LiteralPath $outputFullPath -Force
    }
    throw
}
finally {
    # This is the only path we created, in the private data-volume temp dir.
    try {
        $null = Invoke-P1Docker -Arguments @(
            'exec', $container, 'python', '-c', "from pathlib import Path; Path('$containerPath').unlink(missing_ok=True)"
        )
    }
    catch { }
}
