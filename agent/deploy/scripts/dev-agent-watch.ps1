param([switch]$Once,[string]$Adb='adb',[string]$LogRoot='D:\AI\runtime\shared-ledger-agent')
$ErrorActionPreference='Stop'
$null=Get-Command $Adb
if ([IO.Path]::GetPathRoot($LogRoot) -ne 'D:\') { throw 'Logs must be on D:.' }
$null=New-Item -ItemType Directory -Force $LogRoot
do {
 try {
  $p=Start-Process $Adb -ArgumentList 'wait-for-device' -WindowStyle Hidden -PassThru
  if (!$p.WaitForExit(30000)) { $p.Kill(); throw 'Device timeout. Connect and authorize one device.' }
  if ($p.ExitCode) { throw 'adb wait failed. Check adb server.' }
  $null=& $Adb reverse tcp:8765 tcp:8765 2>&1
  if ($LASTEXITCODE) { throw 'adb reverse failed. Check device authorization.' }
  $mapping=& $Adb reverse --list
  if ($LASTEXITCODE -or ($mapping -join "`n") -notmatch 'tcp:8765\s+tcp:8765') { throw 'Reverse verification failed.' }
  Add-Content (Join-Path $LogRoot 'dev-watch.log') "$(Get-Date -Format o) Reverse ready."
 } catch { Add-Content (Join-Path $LogRoot 'dev-watch.log') "$(Get-Date -Format o) $($_.Exception.Message)"; if ($Once) { throw } }
 if (!$Once) { Start-Sleep 5 }
} until ($Once)
