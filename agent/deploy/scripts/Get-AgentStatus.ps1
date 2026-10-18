param(
    [string]$ProjectName = 'shared-ledger-agent-p1-06',
    [string]$EnvFile,
    [switch]$Acceptance,
    [switch]$Offline,
    [ValidateRange(0, 65535)][int]$HostPort = 0
)

. (Join-Path $PSScriptRoot 'Deploy.Common.ps1')
try {
    $status = Invoke-P1Compose -ProjectName $ProjectName -EnvFile $EnvFile -Acceptance:$Acceptance -Offline:$Offline -Command @('ps', '--all')
    $prefix = Get-P1ComposePrefix -ProjectName $ProjectName -EnvFile $EnvFile -Acceptance:$Acceptance -Offline:$Offline
    $configLines = Invoke-P1Docker -Arguments ($prefix + @('config', '--format', 'json'))
    $config = ($configLines -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
    $status
}
catch {
    Write-Output 'Docker service status: unavailable; API health was not probed.'
    return
}

$ids = Invoke-P1Compose -ProjectName $ProjectName -EnvFile $EnvFile -Acceptance:$Acceptance -Offline:$Offline -Command @('ps', '--all', '--quiet', 'agent')
$ids = @($ids | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($ids.Count -ne 1) {
    Write-Output 'Docker Agent service: not running or not uniquely present; API health was not probed.'
    return
}
$inspect = @(Invoke-P1Docker -Arguments @(
    'inspect', '--format', '{{.State.Status}}|{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}', $ids[0]
))
$parts = $inspect[0].Split('|')
Write-Output "Docker Agent service: state=$($parts[0]) running=$($parts[1]) health=$($parts[2])"
if ($parts[1] -ne 'true') {
    Write-Output 'API live/ready/provider: unavailable; container is stopped.'
    return
}

if ($HostPort -eq 0) {
    $port = $config.services.agent.ports | Select-Object -First 1
    if (-not $port -or -not $port.published) {
        Write-Output 'API live/ready/provider: unavailable; no published host port was found.'
        return
    }
    $HostPort = [int]$port.published
}
$baseUrl = "http://127.0.0.1:$HostPort"
foreach ($endpoint in @('live', 'ready', 'provider')) {
    try {
        $payload = Invoke-RestMethod -Uri ($baseUrl + '/health/' + $endpoint) -Method Get -TimeoutSec 3
        $safe = [ordered]@{ status = $payload.status; inference_available = $payload.inference_available }
        foreach ($key in @('storage_substrate_ready', 'schema_initialized', 'business_api_available', 'runtime_available', 'provider_status', 'reason')) {
            if ($payload.PSObject.Properties.Name -contains $key) { $safe[$key] = $payload.$key }
        }
        Write-Output ("API health /health/$endpoint on loopback: " + (ConvertTo-Json -InputObject $safe -Compress))
    }
    catch {
        Write-Output "API health /health/$endpoint on loopback port ${HostPort}: unavailable."
    }
}
