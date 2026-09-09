param(
    [string]$DeviceSerial,
    [string]$SupabaseCliPath = "D:\computer\Hermes\tools\supabase\2.116.0\supabase.exe",
    [string]$JavaHome = "D:\computer\Configuration\.jdks\ms-21.0.7",
    [switch]$SkipBuild,
    [switch]$SkipInstall,
    [switch]$SkipLaunch
)

$ErrorActionPreference = "Stop"

$packageName = "com.ffocalors.sharedledger"
$repoRoot = Split-Path -Parent $PSScriptRoot
$localPropertiesPath = Join-Path $repoRoot "local.properties"

function Get-LocalProperty {
    param([string]$Name)

    $line = Get-Content -LiteralPath $localPropertiesPath |
        Where-Object { $_ -match ("^" + [regex]::Escape($Name) + "=") } |
        Select-Object -First 1
    if ($line) {
        return (($line -split "=", 2)[1].Trim() -replace "\\:", ":" -replace "\\/", "/" -replace "\\\\", "\")
    }
    return $null
}

if (-not (Test-Path -LiteralPath $localPropertiesPath)) {
    throw "local.properties is missing; cannot validate local Supabase configuration."
}
if (-not (Test-Path -LiteralPath $SupabaseCliPath -PathType Leaf)) {
    throw "Supabase CLI not found at the configured path."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is unavailable; start Docker Desktop and retry."
}
& docker version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker engine is unavailable; start Docker Desktop and retry."
}

$requiredContainers = @(
    "supabase_db_shared-ledger",
    "supabase_kong_shared-ledger",
    "supabase_auth_shared-ledger",
    "supabase_rest_shared-ledger",
    "supabase_storage_shared-ledger",
    "supabase_realtime_shared-ledger"
)

function Get-ContainerStates {
    $states = @{}
    $rows = @(& docker ps --format "{{.Names}}|{{.Status}}")
    foreach ($row in $rows) {
        $parts = $row -split "\|", 2
        if ($parts.Count -eq 2) {
            $states[$parts[0]] = $parts[1]
        }
    }
    return $states
}

function Get-MissingCoreContainers {
    param([hashtable]$States)
    return @($requiredContainers | Where-Object { -not $States.ContainsKey($_) })
}

function Get-UnhealthyCoreContainers {
    param([hashtable]$States)
    return @($requiredContainers | Where-Object {
            $status = $States[$_]
            $status -notmatch "^(?i)Up\b" -or $status -match "(?i)\(unhealthy\)|\(health:\s*starting\)"
        })
}

$containerStates = Get-ContainerStates
$missingContainers = Get-MissingCoreContainers -States $containerStates
if ($missingContainers.Count -gt 0) {
    $supabaseStartExit = $null
    $startLogId = [guid]::NewGuid().ToString("N")
    $startStdout = Join-Path $env:TEMP ("shared-ledger-supabase-start-$startLogId.stdout.log")
    $startStderr = Join-Path $env:TEMP ("shared-ledger-supabase-start-$startLogId.stderr.log")
    $locationPushed = $false
    try {
        try {
            Push-Location $repoRoot
            $locationPushed = $true
            & $SupabaseCliPath start > $startStdout 2> $startStderr
            $supabaseStartExit = $LASTEXITCODE
        } catch {
            $supabaseStartExit = -1
        }
    } finally {
        if ($locationPushed) {
            Pop-Location
        }
        Remove-Item -LiteralPath $startStdout, $startStderr -Force -ErrorAction SilentlyContinue
    }

    $containerStates = Get-ContainerStates
    $missingContainers = Get-MissingCoreContainers -States $containerStates
    if ($missingContainers.Count -gt 0) {
        if ($null -eq $supabaseStartExit) {
            throw "Local Supabase core containers are missing or stopped; automatic local stack start did not complete."
        }
        throw "Local Supabase core containers remain missing or stopped after CLI start (exit code $supabaseStartExit)."
    }
}
$unhealthyContainers = Get-UnhealthyCoreContainers -States $containerStates
if ($unhealthyContainers.Count -gt 0) {
    throw "Local Supabase core containers are not Running/healthy: $($unhealthyContainers -join ', ')."
}

$supabaseUrl = Get-LocalProperty -Name "SUPABASE_URL"
$normalizedUrl = if ($null -eq $supabaseUrl) { "" } else { $supabaseUrl.Trim().TrimEnd("/") }
if ($normalizedUrl -notmatch "^(?i)http://(127\.0\.0\.1|localhost):54321$") {
    throw "SUPABASE_URL must be local http://127.0.0.1:54321 or http://localhost:54321 for USB adb reverse."
}
$publishableKey = Get-LocalProperty -Name "SUPABASE_PUBLISHABLE_KEY"
if ([string]::IsNullOrWhiteSpace($publishableKey)) {
    throw "SUPABASE_PUBLISHABLE_KEY is missing or empty in local.properties."
}
if ($publishableKey -match "(?i)(service_role|secret)") {
    throw "SUPABASE_PUBLISHABLE_KEY must not contain a service_role or secret key."
}

$sdkDir = Get-LocalProperty -Name "sdk.dir"
if ([string]::IsNullOrWhiteSpace($sdkDir)) {
    throw "sdk.dir is missing from local.properties."
}
$adb = Join-Path $sdkDir "platform-tools\adb.exe"
if (-not (Test-Path -LiteralPath $adb -PathType Leaf)) {
    throw "adb.exe is not available from local.properties sdk.dir."
}

$deviceRows = @(& $adb devices -l)
if ($LASTEXITCODE -ne 0) {
    throw "adb devices failed; check the Android SDK installation."
}
$devices = @(
    foreach ($line in $deviceRows) {
        if ($line -match "^(?<serial>\S+)\s+(?<state>device|offline|unauthorized)\b") {
            [pscustomobject]@{ Serial = $Matches.serial; State = $Matches.state }
        }
    }
)

if ([string]::IsNullOrWhiteSpace($DeviceSerial)) {
    $authorizedDevices = @($devices | Where-Object { $_.State -eq "device" })
    if ($authorizedDevices.Count -eq 0) {
        $offline = @($devices | Where-Object { $_.State -eq "offline" } | Select-Object -ExpandProperty Serial)
        $unauthorized = @($devices | Where-Object { $_.State -eq "unauthorized" } | Select-Object -ExpandProperty Serial)
        if ($offline.Count -gt 0 -or $unauthorized.Count -gt 0) {
            $details = @()
            if ($offline.Count -gt 0) { $details += "offline: $($offline -join ', ')" }
            if ($unauthorized.Count -gt 0) { $details += "unauthorized: $($unauthorized -join ', ')" }
            throw "No authorized Android device is available ($($details -join '; ')); accept USB debugging RSA or reconnect the device."
        }
        throw "No authorized Android device is connected; connect a device with USB debugging enabled."
    }
    if ($authorizedDevices.Count -gt 1) {
        throw "Multiple authorized Android devices are connected; pass -DeviceSerial explicitly."
    }
    $selectedSerial = $authorizedDevices[0].Serial
} else {
    $selected = @($devices | Where-Object { $_.Serial -eq $DeviceSerial } | Select-Object -First 1)
    if ($selected.Count -eq 0) {
        throw "Requested Android device is not connected or authorized."
    }
    if ($selected[0].State -eq "offline") {
        throw "Requested Android device is offline; reconnect it before retrying."
    }
    if ($selected[0].State -eq "unauthorized") {
        throw "Requested Android device is unauthorized; accept the USB debugging RSA prompt."
    }
    $selectedSerial = $selected[0].Serial
}

& $adb -s $selectedSerial reverse tcp:54321 tcp:54321 *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create adb reverse tcp:54321 for the selected device."
}
$reverseList = @(& $adb -s $selectedSerial reverse --list 2> $null)
if ($reverseList -notmatch "tcp:54321\s+tcp:54321") {
    throw "adb reverse did not report tcp:54321 for the selected device."
}
& $adb -s $selectedSerial shell toybox nc -z -w 5 127.0.0.1 54321 *> $null
if ($LASTEXITCODE -ne 0) {
    throw "The selected device cannot reach local Supabase through adb reverse."
}

$apk = Join-Path $repoRoot "app\build\outputs\apk\debug\app-debug.apk"
if (-not $SkipBuild) {
    $java = Join-Path $JavaHome "bin\java.exe"
    if (-not (Test-Path -LiteralPath $java -PathType Leaf)) {
        throw "Configured JDK is unavailable for the Debug build."
    }
    $gradle = Join-Path $repoRoot "gradlew.bat"
    $env:JAVA_HOME = $JavaHome
    $env:PATH = "$(Join-Path $JavaHome 'bin');$env:PATH"
    & $gradle :app:assembleDebug --console=plain *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Debug build failed."
    }
}

if (-not $SkipInstall) {
    if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) {
        throw "Debug APK is missing; build it or omit -SkipBuild."
    }
    & $adb -s $selectedSerial install -r $apk *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Debug APK installation failed."
    }
}

if (-not $SkipLaunch) {
    & $adb -s $selectedSerial shell monkey -p $packageName -c android.intent.category.LAUNCHER 1 *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "SharedLedger launch failed."
    }
}

Write-Output "DeviceSerial=$selectedSerial"
Write-Output "Docker=READY"
Write-Output "LocalSupabaseCore=READY"
Write-Output "AdbReverse54321=READY"
if (-not $SkipBuild) { Write-Output "Build=READY" }
if (-not $SkipInstall) { Write-Output "Install=READY" }
if (-not $SkipLaunch) { Write-Output "Launch=READY" }
if (Test-Path -LiteralPath $apk -PathType Leaf) {
    $hash = (Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash
    Write-Output "ApkSha256=$hash"
}
