param(
    [string]$ProjectName = 'shared-ledger-agent-p1-06',
    [string]$EnvFile,
    [switch]$Acceptance,
    [switch]$Offline
)

. (Join-Path $PSScriptRoot 'Deploy.Common.ps1')
$null = Invoke-P1Compose -ProjectName $ProjectName -EnvFile $EnvFile -Acceptance:$Acceptance -Offline:$Offline -Command @('stop', 'agent')
Write-Output "Stopped only the Agent service in Compose project '$ProjectName'; its volume remains attached and intact."
