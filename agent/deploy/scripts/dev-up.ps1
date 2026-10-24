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
 # Single instance: stop every existing Agent (command line '-m app.main' only; other
 # Python processes are never touched). A venv python.exe is a launcher that spawns the
 # base interpreter with the same command line, so one Agent shows up as two PIDs.
 $agentPattern='(^|\s)-m\s+app\.main(\s|$)'
 $existing=@(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match $agentPattern })
 foreach ($proc in $existing) {
  Write-Output "Stopping existing Agent PID=$($proc.ProcessId) ($($proc.ExecutablePath))"
  Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
 }
 $end=(Get-Date).AddSeconds(15)
 while ((Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) -and (Get-Date) -lt $end) { Start-Sleep -Milliseconds 300 }
 $owner=Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
 if ($owner) {
  $op=Get-CimInstance Win32_Process -Filter "ProcessId=$($owner.OwningProcess)"
  throw "Port 8765 is held by PID=$($owner.OwningProcess) ($($op.Name)), which is not an Agent ('-m app.main'). Stop it manually, then rerun dev-up."
 }
 $null=New-Item -ItemType Directory -Force $LogRoot
 $stamp=Get-Date -Format yyyyMMdd-HHmmss-ffff
 $oldHost=$env:AGENT_LISTEN_HOST; $oldAccess=$env:AGENT_DEV_ACCESS_LOG
 try {
  $env:AGENT_LISTEN_HOST=if ($Lan) {'0.0.0.0'} else {'127.0.0.1'}
  # Development-only: uvicorn access log (query stripped) + app INFO logs to stderr.
  $env:AGENT_DEV_ACCESS_LOG='1'
  $p=Start-Process $python -ArgumentList '-m app.main' -WorkingDirectory $AgentRoot -WindowStyle Hidden -RedirectStandardOutput "$LogRoot/dev-up-$stamp.log" -RedirectStandardError "$LogRoot/dev-up-$stamp-error.log" -PassThru
  Write-Output "Started Agent PID=$($p.Id). Access log: $LogRoot/dev-up-$stamp.log; app/503 log: $LogRoot/dev-up-$stamp-error.log"
 } finally { $env:AGENT_LISTEN_HOST=$oldHost; $env:AGENT_DEV_ACCESS_LOG=$oldAccess }
 $ready=$false; $end=(Get-Date).AddSeconds(60)
 do { try { $ready=(Invoke-WebRequest http://127.0.0.1:8765/health/ready -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch {}; if (!$ready) { Start-Sleep 1 } } until ($ready -or (Get-Date) -ge $end)
 if (!$ready) {
  if ($p.HasExited) { throw "Agent exited with code $($p.ExitCode). Inspect $LogRoot/dev-up-$stamp-error.log (exit 3 = another instance holds the storage lock)." }
  throw "Readiness timeout. Inspect $LogRoot and LM Studio model/server status."
 }
 if ($Lan) {
  if (!(Get-NetTCPConnection -LocalPort 8765 -State Listen | Where-Object LocalAddress -eq '0.0.0.0')) { throw 'Existing Agent is not LAN-bound. Stop it explicitly, then rerun -Lan.' }
  Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -Match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' | ForEach-Object { Write-Output "LAN endpoint: http://$($_.IPAddress):8765" }
 } else { & "$PSScriptRoot/dev-agent-watch.ps1" -Once -Adb $Adb -LogRoot $LogRoot }
} finally { $mutex.ReleaseMutex(); $mutex.Dispose() }

