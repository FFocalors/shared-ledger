param([switch]$Uninstall,[switch]$Lan,[string]$AgentRoot=$env:AGENT_DEV_ROOT)
$ErrorActionPreference='Stop'
if (!$AgentRoot) { $AgentRoot=(Resolve-Path "$PSScriptRoot/../..").Path }
$null=Get-Command Register-ScheduledTask
$user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$names=@('SharedLedger-DevUp','SharedLedger-DevWatch')
foreach ($n in $names) { $null=Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue }
if ($Uninstall) { foreach ($n in $names) { if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $n; Unregister-ScheduledTask -TaskName $n -Confirm:$false } }; exit }
foreach ($f in @('dev-up.ps1','dev-agent-watch.ps1')) { if (!(Test-Path "$PSScriptRoot/$f")) { throw "Missing script: $f" } }
try {
 for ($i=0;$i -lt 2;$i++) {
  if ($Lan -and $i -eq 1) { continue }
  $file=@('dev-up.ps1','dev-agent-watch.ps1')[$i]
  $args='-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$PSScriptRoot+'\'+$file+'"'
  if ($i -eq 0) { $args+=' -AgentRoot "'+$AgentRoot+'"'; if ($Lan) { $args+=' -Lan' } }
  $a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $args
  $p=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
  $t=New-ScheduledTaskTrigger -AtLogOn -User $user
  $s=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  $null=Register-ScheduledTask -TaskName $names[$i] -Action $a -Trigger $t -Principal $p -Settings $s -Force
 }
} catch { throw 'Registration failed. Check current-user Task Scheduler rights; policy may require administrator assistance.' }
Write-Output 'Login tasks registered. Run dev-up now for this session.'
