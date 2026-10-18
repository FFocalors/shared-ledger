param(
    [string]$ProjectName = 'shared-ledger-agent-p1-06',
    [string]$EnvFile,
    [switch]$Acceptance,
    [switch]$Offline
)

. (Join-Path $PSScriptRoot 'Deploy.Common.ps1')
$null = Invoke-P1Compose -ProjectName $ProjectName -EnvFile $EnvFile -Acceptance:$Acceptance -Offline:$Offline -Command @('up', '--detach', '--build', 'agent')
Write-Output "Agent Compose project '$ProjectName' is starting. Use Get-AgentStatus.ps1 to inspect readiness."
