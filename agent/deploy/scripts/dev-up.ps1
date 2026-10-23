<#
.SYNOPSIS
Prepare the development Agent and USB adb reverse workflow.
.PARAMETER Lan
EXPERIMENTAL, NOT CURRENTLY IN USE. Opt-in trusted-LAN testing only.
Binds to all IPv4 interfaces and skips adb. Default USB behavior is unchanged.
Never use this option for production or public networks.
.PARAMETER AgentRoot
Explicit Agent directory containing app/main.py and the local virtual environment.
#>
param([switch]$Lan,[string]$AgentRoot,[string]$Lms="$env:USERPROFILE\.lmstudio\bin\lms.exe",[string]$Adb='adb',[string]$LogRoot='D:\AI\runtime\shared-ledger-agent')
$ErrorActionPreference='Stop'
# Explicit parameters are authoritative; defaults are tried in priority order.
$candidates = if ($PSBoundParameters.ContainsKey('AgentRoot')) {
    @($AgentRoot)
} else {
    @($env:AGENT_DEV_ROOT, 'D:\project\Android\shared-ledger-agent\agent', [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..')))
}
$checked = @()
$resolvedRoot = $null
foreach ($candidate in $candidates) {
    if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
    $candidate = [IO.Path]::GetFullPath($candidate)
    $checked += $candidate
    if ((Test-Path -LiteralPath (Join-Path $candidate '.venv/Scripts/python.exe') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $candidate 'app/main.py') -PathType Leaf)) {
        $resolvedRoot = $candidate
        break
    }
}
if (!$resolvedRoot) {
    throw ('AgentRoot not found. Checked: ' + ($checked -join '; ') + '. Each root must contain .venv/Scripts/python.exe and app/main.py. Set -AgentRoot explicitly.')
}
$AgentRoot = $resolvedRoot
$python=Join-Path $AgentRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $Lms -PathType Leaf)) { throw ('LM Studio CLI not found. Checked: ' + $Lms + '. Set -Lms explicitly.') }
if ([IO.Path]::GetPathRoot($LogRoot) -ne 'D:\') { throw 'Logs must be on D:.' }
if (!$Lan) { $null=Get-Command $Adb }
$mutex=New-Object Threading.Mutex($false,'Local\SharedLedgerDevUp8765')
if (!$mutex.WaitOne(0)) { throw 'Another dev-up is running. Retry later.' }
try {
 $s=& $Lms server status --json
 if ($LASTEXITCODE) { throw 'Cannot inspect LM Studio. Open LM Studio and retry.' }
 if (!(($s | ConvertFrom-Json).running)) { & $Lms server start; if ($LASTEXITCODE) { throw 'LM Studio start failed.' } }
 $models=& $Lms ps --json
 if ($LASTEXITCODE) { throw 'Cannot inspect loaded models.' }
 if (($models -join "`n") -notmatch 't0-cp36-20261007') { & $Lms load t0-cp36-20261007 --context-length 8192 --parallel 1 --yes; if ($LASTEXITCODE) { throw 'Model load failed.' } }
 $live=$false
 try { $live=(Invoke-WebRequest http://127.0.0.1:8765/health/live -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch {}
 if (!$live) {
  if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) { throw 'Port occupied with failed health. Inspect owner; no process stopped.' }
  $null=New-Item -ItemType Directory -Force $LogRoot
  $stamp=Get-Date -Format yyyyMMdd-HHmmss-ffff
  $old=$env:AGENT_LISTEN_HOST
  try {
   $env:AGENT_LISTEN_HOST=if ($Lan) {'0.0.0.0'} else {'127.0.0.1'}
   $p=Start-Process $python -ArgumentList '-m app.main' -WorkingDirectory $AgentRoot -WindowStyle Hidden -RedirectStandardOutput "$LogRoot/dev-up-$stamp.log" -RedirectStandardError "$LogRoot/dev-up-$stamp-error.log" -PassThru
   Write-Output "Started Agent PID=$($p.Id). Logs: $LogRoot"
  } finally { $env:AGENT_LISTEN_HOST=$old }
 }
 $ready=$false; $end=(Get-Date).AddSeconds(60)
 do { try { $ready=(Invoke-WebRequest http://127.0.0.1:8765/health/ready -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch {}; if (!$ready) { Start-Sleep 1 } } until ($ready -or (Get-Date) -ge $end)
 if (!$ready) { throw "Readiness timeout. Inspect $LogRoot and LM Studio model/server status." }
 if ($Lan) {
  if (!(Get-NetTCPConnection -LocalPort 8765 -State Listen | Where-Object LocalAddress -eq '0.0.0.0')) { throw 'Existing Agent is not LAN-bound. Stop it explicitly, then rerun -Lan.' }
  Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -Match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' | ForEach-Object { Write-Output "LAN endpoint: http://$($_.IPAddress):8765" }
 } else { & "$PSScriptRoot/dev-agent-watch.ps1" -Once -Adb $Adb -LogRoot $LogRoot }
} finally { $mutex.ReleaseMutex(); $mutex.Dispose() }

