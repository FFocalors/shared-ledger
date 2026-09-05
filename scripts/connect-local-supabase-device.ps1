param(
    [switch]$SkipBuild,
    [switch]$SkipInstall,
    [switch]$SkipLaunch
)

$ErrorActionPreference = "Stop"

$deviceSerial = "8THEYTQKU8HQGIEY"
$packageName = "com.ffocalors.sharedledger"
$javaHome = "D:\computer\Configuration\.jdks\ms-21.0.7"

$repoRoot = Split-Path -Parent $PSScriptRoot
$localPropertiesPath = Join-Path $repoRoot "local.properties"
if (-not (Test-Path -LiteralPath $localPropertiesPath)) {
    throw "local.properties not found: $localPropertiesPath"
}

$sdkLine = Get-Content -LiteralPath $localPropertiesPath |
    Where-Object { $_ -match '^sdk\.dir=' } |
    Select-Object -First 1
if (-not $sdkLine) {
    throw "sdk.dir is missing from local.properties"
}

$sdkDir = ($sdkLine -replace '^sdk\.dir=', '' -replace '\\:', ':' -replace '\\\\', '\')
$adb = Join-Path $sdkDir "platform-tools\adb.exe"
if (-not (Test-Path -LiteralPath $adb)) {
    throw "adb.exe not found: $adb"
}

$deviceLine = & $adb devices | Where-Object {
    $_ -match "^$([regex]::Escape($deviceSerial))`tdevice$"
} | Select-Object -First 1
if (-not $deviceLine) {
    throw "Target Android device $deviceSerial is not connected and authorized."
}

& $adb -s $deviceSerial reverse tcp:54321 tcp:54321
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create adb reverse for Supabase port 54321."
}

$reverseList = & $adb -s $deviceSerial reverse --list
if ($reverseList -notmatch 'tcp:54321\s+tcp:54321') {
    throw "adb reverse did not report the expected Supabase port mapping."
}

& $adb -s $deviceSerial shell toybox nc -z -w 5 127.0.0.1 54321
if ($LASTEXITCODE -ne 0) {
    throw "The device cannot reach local Supabase through adb reverse."
}

if (-not $SkipBuild) {
    $gradle = Join-Path $repoRoot "gradlew.bat"
    $java = Join-Path $javaHome "bin\java.exe"
    if (-not (Test-Path -LiteralPath $java)) {
        throw "Configured JDK not found: $javaHome"
    }

    $env:JAVA_HOME = $javaHome
    $env:PATH = "$(Join-Path $javaHome 'bin');$env:PATH"
    & $gradle --no-daemon --no-configuration-cache assembleDebug
    if ($LASTEXITCODE -ne 0) {
        throw "Debug build failed."
    }
}

if (-not $SkipInstall) {
    $apk = Join-Path $repoRoot "app\build\outputs\apk\debug\app-debug.apk"
    if (-not (Test-Path -LiteralPath $apk)) {
        throw "Debug APK not found: $apk"
    }
    & $adb -s $deviceSerial install -r $apk
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install the Debug APK."
    }
}

if (-not $SkipLaunch) {
    & $adb -s $deviceSerial shell monkey -p $packageName -c android.intent.category.LAUNCHER 1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to launch $packageName."
    }
}

Write-Output "Device $deviceSerial is ready: Supabase connected, Debug APK installed, and SharedLedger launched."
