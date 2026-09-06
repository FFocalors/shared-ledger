param(
    [string]$DeviceSerial = "8THEYTQKU8HQGIEY",
    [string]$SupabaseCliPath = "D:\computer\Supabase\supabase.exe",
    [string]$JavaHome = "D:\computer\Configuration\.jdks\ms-21.0.7",
    [switch]$SkipBuild,
    [switch]$SkipInstall,
    [switch]$SkipLaunch
)

$ErrorActionPreference = "Stop"

$packageName = "com.ffocalors.sharedledger"
$repoRoot = Split-Path -Parent $PSScriptRoot
$localPropertiesPath = Join-Path $repoRoot "local.properties"
$hostedPropertiesPath = Join-Path $repoRoot "local.hosted.properties"
$projectRefPath = Join-Path $repoRoot "supabase\.temp\project-ref"

function Fail([string]$Message) {
    throw "Hosted Supabase device setup failed: $Message"
}

if (-not (Test-Path -LiteralPath $localPropertiesPath -PathType Leaf)) {
    Fail "local.properties not found: $localPropertiesPath"
}
if (-not (Test-Path -LiteralPath $SupabaseCliPath -PathType Leaf)) {
    Fail "Supabase CLI not found: $SupabaseCliPath"
}
if (-not (Test-Path -LiteralPath $projectRefPath -PathType Leaf)) {
    Fail "supabase\.temp\project-ref not found. Link the project before running this script."
}

$sdkLine = Get-Content -LiteralPath $localPropertiesPath |
    Where-Object { $_ -match '^sdk\.dir=' } |
    Select-Object -First 1
if (-not $sdkLine) {
    Fail "sdk.dir is missing from local.properties"
}

$sdkDir = ($sdkLine -replace '^sdk\.dir=', '' -replace '\\:', ':' -replace '\\\\', '\')
$adb = Join-Path $sdkDir "platform-tools\adb.exe"
if (-not (Test-Path -LiteralPath $adb -PathType Leaf)) {
    Fail "adb.exe not found: $adb"
}

$javaExecutable = Join-Path $JavaHome "bin\java.exe"
if (-not (Test-Path -LiteralPath $javaExecutable -PathType Leaf)) {
    Fail "Configured JDK not found: $JavaHome"
}
$env:JAVA_HOME = $JavaHome
$env:PATH = "$(Join-Path $JavaHome 'bin');$env:PATH"

$projectRef = (Get-Content -Raw -LiteralPath $projectRefPath).Trim()
if ($projectRef -notmatch '^[A-Za-z0-9-]+$') {
    Fail "The linked project ref is empty or invalid."
}

function Test-UsableClientKey($Key) {
    if ($null -eq $Key) {
        return $false
    }
    if ($Key.PSObject.Properties.Name -contains "disabled" -and [bool]$Key.disabled) {
        return $false
    }
    if ($Key.PSObject.Properties.Name -contains "status" -and
        "$($Key.status)".Trim().ToLowerInvariant() -in @("disabled", "revoked")) {
        return $false
    }
    if ([string]::IsNullOrWhiteSpace("$($Key.api_key)")) {
        return $false
    }

    $name = "$($Key.name)".Trim().ToLowerInvariant()
    $type = "$($Key.type)".Trim().ToLowerInvariant()
    if ($name -in @("service_role", "service-role", "secret")) {
        return $false
    }
    return $type -eq "publishable"
}

function Test-LegacyAnonKey($Key) {
    if ($null -eq $Key) {
        return $false
    }
    if ($Key.PSObject.Properties.Name -contains "disabled" -and [bool]$Key.disabled) {
        return $false
    }
    if ($Key.PSObject.Properties.Name -contains "status" -and
        "$($Key.status)".Trim().ToLowerInvariant() -in @("disabled", "revoked")) {
        return $false
    }
    if ([string]::IsNullOrWhiteSpace("$($Key.api_key)")) {
        return $false
    }
    return "$($Key.name)".Trim().ToLowerInvariant() -eq "anon" -and
        "$($Key.type)".Trim().ToLowerInvariant() -eq "legacy"
}

$apiKeysErrorPath = Join-Path ([System.IO.Path]::GetTempPath()) (
    "sharedledger-supabase-api-keys-{0}.err" -f [guid]::NewGuid().ToString("N")
)
try {
    $apiKeysOutput = & $SupabaseCliPath projects api-keys --project-ref $projectRef --output json 2> $apiKeysErrorPath
    $apiKeysExitCode = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $apiKeysErrorPath -Force -ErrorAction SilentlyContinue
}
if ($apiKeysExitCode -ne 0) {
    Fail "Supabase CLI could not list project API keys (exit code $apiKeysExitCode). Verify CLI authentication and the linked project ref."
}

$apiKeysJson = ($apiKeysOutput -join [Environment]::NewLine).Trim()
if ($apiKeysJson.Length -eq 0) {
    Fail "Supabase CLI returned no API key data."
}
try {
    # Windows PowerShell 5.1 emits a JSON root array as one nested Object[].
    # Pipe the decoded value once more so both 5.1 and PowerShell 7 expose
    # individual key objects to the filters below.
    $decodedApiKeys = $apiKeysJson | ConvertFrom-Json
    $apiKeys = @($decodedApiKeys | ForEach-Object { $_ })
} catch {
    Fail "Supabase CLI returned invalid API key JSON."
}

$clientKey = $apiKeys |
    Where-Object { Test-UsableClientKey $_ } |
    Select-Object -First 1
if ($null -eq $clientKey) {
    $clientKey = $apiKeys |
        Where-Object { Test-LegacyAnonKey $_ } |
        Select-Object -First 1
}
if ($null -eq $clientKey) {
    Fail "No enabled publishable client key (or compatible legacy anon key) was found."
}

$hostedUrl = "https://$projectRef.supabase.co"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$hostedProperties = @(
    "SUPABASE_URL=$hostedUrl",
    "SUPABASE_PUBLISHABLE_KEY=$($clientKey.api_key)"
) -join [Environment]::NewLine
[System.IO.File]::WriteAllText($hostedPropertiesPath, "$hostedProperties$([Environment]::NewLine)", $utf8NoBom)

$deviceLine = & $adb devices | Where-Object {
    $_ -match "^$([regex]::Escape($DeviceSerial))`tdevice$"
} | Select-Object -First 1
if (-not $deviceLine) {
    Fail "Target Android device $DeviceSerial is not connected and authorized."
}

if (-not $SkipBuild) {
    $gradle = Join-Path $repoRoot "gradlew.bat"
    if (-not (Test-Path -LiteralPath $gradle -PathType Leaf)) {
        Fail "gradlew.bat not found: $gradle"
    }
    & $gradle --no-daemon --no-configuration-cache assembleDebug "-PsupabaseEnvironment=hosted"
    if ($LASTEXITCODE -ne 0) {
        Fail "Hosted Supabase Debug build failed."
    }
}

if (-not $SkipInstall) {
    $apk = Join-Path $repoRoot "app\build\outputs\apk\debug\app-debug.apk"
    if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) {
        Fail "Debug APK not found: $apk. Run without -SkipBuild first."
    }
    & $adb -s $DeviceSerial install -r $apk
    if ($LASTEXITCODE -ne 0) {
        Fail "Failed to install the Debug APK on $DeviceSerial."
    }
}

if (-not $SkipLaunch) {
    & $adb -s $DeviceSerial shell monkey -p $packageName -c android.intent.category.LAUNCHER 1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail "Failed to launch $packageName on $DeviceSerial."
    }
}

$buildStatus = if ($SkipBuild) { "skipped" } else { "completed" }
$installStatus = if ($SkipInstall) { "skipped" } else { "completed" }
$launchStatus = if ($SkipLaunch) { "skipped" } else { "completed" }
Write-Output "Hosted Supabase device setup completed for $DeviceSerial."
Write-Output "Hosted Supabase: $hostedUrl"
Write-Output "Debug build: $buildStatus; APK install: $installStatus; app launch: $launchStatus."
Write-Output "Docker was not used. adb reverse was not used."
