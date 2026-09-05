param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"

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

$deviceLines = @(& $adb devices | Where-Object { $_ -match "`tdevice$" })
if ($deviceLines.Count -ne 1) {
    throw "Expected exactly one authorized Android device, found $($deviceLines.Count)."
}
$serial = ($deviceLines[0] -split "`t")[0]

& $adb -s $serial reverse tcp:54321 tcp:54321
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create adb reverse for Supabase port 54321."
}

$reverseList = & $adb -s $serial reverse --list
if ($reverseList -notmatch 'tcp:54321\s+tcp:54321') {
    throw "adb reverse did not report the expected Supabase port mapping."
}

& $adb -s $serial shell toybox nc -z -w 5 127.0.0.1 54321
if ($LASTEXITCODE -ne 0) {
    throw "The device cannot reach local Supabase through adb reverse."
}

if ($Install) {
    $apk = Join-Path $repoRoot "app\build\outputs\apk\debug\app-debug.apk"
    if (-not (Test-Path -LiteralPath $apk)) {
        throw "Debug APK not found. Run .\gradlew.bat assembleDebug first."
    }
    & $adb -s $serial install -r $apk
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install the Debug APK."
    }
}

Write-Output "Local Supabase is available to device $serial at http://127.0.0.1:54321."
