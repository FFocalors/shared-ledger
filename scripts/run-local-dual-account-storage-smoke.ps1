<#
.SYNOPSIS
    Runs a local two-account Storage/RLS attachment smoke.

.DESCRIPTION
    Exercises the frozen create_attachment -> Storage upload ->
    complete_attachment flow with an authenticated Creator (A), member (B),
    and outsider (C). Only the local loopback API is used. Credentials,
    signed URLs, raw objects, and response bodies are never printed.
    Records remain in local Supabase until the local project is reset.
#>

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$localPropertiesPath = Join-Path $repoRoot "local.properties"
$script:baseUrl = $null; $script:publishableKey = $null; $script:httpClient = $null
$script:passCount = 0; $script:failCount = 0; $script:stepCount = 0; $script:failureReported = $false

function Get-LocalProperty {
    param([Parameter(Mandatory)][string]$Name)
    $line = Get-Content -LiteralPath $localPropertiesPath | Where-Object { $_ -match ("^" + [regex]::Escape($Name) + "=") } | Select-Object -First 1
    if ($null -eq $line) { return $null }
    return (($line -split "=", 2)[1].Trim() -replace "\\:", ":" -replace "\\/", "/" -replace "\\\\", "\")
}

function Get-StatusClass {
    param([int]$StatusCode)
    if ($StatusCode -ge 200 -and $StatusCode -lt 300) { return "2xx" }
    if ($StatusCode -ge 400 -and $StatusCode -lt 500) { return "4xx" }
    if ($StatusCode -ge 500 -and $StatusCode -lt 600) { return "5xx" }
    return "HTTP-$StatusCode"
}

function Add-Pass {
    param([string]$Name, [int]$StatusCode, [string]$Uuid)
    $script:stepCount++; $script:passCount++
    $suffix = if ($Uuid) { " UUID=$Uuid" } else { "" }
    Write-Output "PASS $Name HTTP=$(Get-StatusClass $StatusCode)$suffix"
}

function Add-Fail {
    param([string]$Name, [int]$StatusCode, [string]$Class)
    $script:stepCount++; $script:failCount++; $script:failureReported = $true
    Write-Output "FAIL $Name HTTP=$(Get-StatusClass $StatusCode) CLASS=$Class"
    throw [System.InvalidOperationException]::new("local storage smoke failed")
}

function Invoke-LocalApi {
    param([ValidateSet("GET", "POST")][string]$Method, [string]$Path, [string]$AccessToken, [object]$Body, [byte[]]$Bytes, [string]$ContentType, [switch]$ResponseBytes)
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::$Method, ($script:baseUrl + $Path))
    [void]$request.Headers.TryAddWithoutValidation("apikey", $script:publishableKey)
    if ($AccessToken) { $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $AccessToken) }
    if ($null -ne $Bytes) {
        $request.Content = [System.Net.Http.ByteArrayContent]::new($Bytes)
        [void]$request.Content.Headers.TryAddWithoutValidation("Content-Type", $ContentType)
    } elseif ($null -ne $Body) {
        $request.Content = [System.Net.Http.StringContent]::new(($Body | ConvertTo-Json -Depth 20 -Compress), [System.Text.Encoding]::UTF8, "application/json")
    }
    try {
        $response = $script:httpClient.SendAsync($request).GetAwaiter().GetResult()
        if ($ResponseBytes) { $payload = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult() }
        else { $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() }
        return [pscustomobject]@{ StatusCode = [int]$response.StatusCode; Body = $payload }
    } finally { $request.Dispose() }
}

function Convert-JsonBody {
    param($Response, [string]$Name)
    try { return ($Response.Body | ConvertFrom-Json) } catch { Add-Fail -Name $Name -StatusCode $Response.StatusCode -Class "INVALID_JSON" }
}

function Invoke-Rpc {
    param([string]$Name, [string]$Token, [hashtable]$Body)
    $response = Invoke-LocalApi -Method POST -Path "/rest/v1/rpc/$Name" -AccessToken $Token -Body $Body
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) { Add-Fail -Name $Name -StatusCode $response.StatusCode -Class "HTTP_$($response.StatusCode)" }
    return $response
}

function New-Session {
    param([string]$Role, [string]$Email, [string]$Password)
    $response = Invoke-LocalApi -Method POST -Path "/auth/v1/signup" -Body @{ email = $Email; password = $Password }
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        $class = if ($response.Body -match "(?i)confirm|confirmation|email") { "AUTH_CONFIRMATION_REQUIRED" } else { "AUTH_SIGNUP_HTTP_$($response.StatusCode)" }
        Add-Fail -Name "$Role signup" -StatusCode $response.StatusCode -Class $class
    }
    $parsed = Convert-JsonBody -Response $response -Name "$Role signup"
    $token = [string]$parsed.access_token; $userId = [string]$parsed.user.id
    if ([string]::IsNullOrWhiteSpace($token) -or [string]::IsNullOrWhiteSpace($userId)) { Add-Fail -Name "$Role signup" -StatusCode $response.StatusCode -Class "AUTH_CONFIRMATION_REQUIRED" }
    Add-Pass -Name "$Role signup" -StatusCode $response.StatusCode | Out-Host
    return [pscustomobject]@{ AccessToken = $token; UserId = $userId }
}

function Get-FirstRow {
    param($Response, [string]$Name)
    $rows = @(Convert-JsonBody -Response $Response -Name $Name)
    if ($rows.Count -lt 1) { Add-Fail -Name $Name -StatusCode $Response.StatusCode -Class "EMPTY_RESULT" }
    return $rows[0]
}

function Encode-StoragePath {
    param([string]$Path)
    return (($Path -split "/") | ForEach-Object { [Uri]::EscapeDataString($_) }) -join "/"
}

try {
    if (-not (Test-Path -LiteralPath $localPropertiesPath -PathType Leaf)) { Add-Fail -Name "local configuration" -StatusCode 0 -Class "LOCAL_PROPERTIES_MISSING" }
    $configuredUrl = Get-LocalProperty -Name "SUPABASE_URL"; $script:publishableKey = Get-LocalProperty -Name "SUPABASE_PUBLISHABLE_KEY"
    $normalizedUrl = if ($configuredUrl) { $configuredUrl.TrimEnd("/") } else { "" }
    if ($normalizedUrl -notmatch "^http://(127\.0\.0\.1|localhost):54321$") { Add-Fail -Name "local URL configuration" -StatusCode 0 -Class "LOOPBACK_54321_REQUIRED" }
    if ([string]::IsNullOrWhiteSpace($script:publishableKey)) { Add-Fail -Name "publishable key configuration" -StatusCode 0 -Class "PUBLISHABLE_KEY_MISSING" }
    if ($script:publishableKey -match "(?i)service[_-]?role|sb_secret|secret") { Add-Fail -Name "publishable key configuration" -StatusCode 0 -Class "SECRET_KEY_REJECTED" }
    $script:baseUrl = $normalizedUrl
    $handler = [System.Net.Http.HttpClientHandler]::new(); $handler.UseProxy = $false; $script:httpClient = [System.Net.Http.HttpClient]::new($handler)
    $runId = [guid]::NewGuid().ToString("N")
    $a = New-Session -Role "A" -Email "p6-storage-a-$runId@example.invalid" -Password (([guid]::NewGuid().ToString("N") + "A9!z" + [guid]::NewGuid().ToString("N")))
    $b = New-Session -Role "B" -Email "p6-storage-b-$runId@example.invalid" -Password (([guid]::NewGuid().ToString("N") + "B8!y" + [guid]::NewGuid().ToString("N")))
    $c = New-Session -Role "C" -Email "p6-storage-c-$runId@example.invalid" -Password (([guid]::NewGuid().ToString("N") + "C7!x" + [guid]::NewGuid().ToString("N")))
    $created = Invoke-Rpc -Name "create_activity" -Token $a.AccessToken -Body @{ name = "P6 Storage smoke $runId"; type = "normal"; base_currency = "CNY"; multi_currency_enabled = $false }
    $activity = Get-FirstRow -Response $created -Name "A create activity"; $activityId = [string]$activity.activity_id; $joinCode = [string]$activity.join_code
    if ($activityId -notmatch "^[0-9a-fA-F-]{36}$" -or [string]::IsNullOrWhiteSpace($joinCode)) { Add-Fail -Name "A create activity" -StatusCode $created.StatusCode -Class "INVALID_ACTIVITY_RESULT" }
    Add-Pass -Name "A create activity" -StatusCode $created.StatusCode -Uuid $activityId
    $unitRead = Invoke-LocalApi -Method GET -Path "/rest/v1/ledger_units?activity_id=eq.$activityId&select=id" -AccessToken $a.AccessToken
    if ($unitRead.StatusCode -lt 200 -or $unitRead.StatusCode -ge 300) { Add-Fail -Name "A read ledger unit" -StatusCode $unitRead.StatusCode -Class "HTTP_$($unitRead.StatusCode)" }
    $unit = Get-FirstRow -Response $unitRead -Name "A read ledger unit"; $ledgerUnitId = [string]$unit.id
    if ($ledgerUnitId -notmatch "^[0-9a-fA-F-]{36}$") { Add-Fail -Name "A read ledger unit" -StatusCode $unitRead.StatusCode -Class "INVALID_LEDGER_UNIT_RESULT" }
    Add-Pass -Name "A read ledger unit" -StatusCode $unitRead.StatusCode -Uuid $ledgerUnitId
    $p = Invoke-Rpc -Name "create_participant" -Token $a.AccessToken -Body @{ activity_id = $activityId; name = "P6 Storage B $runId"; participant_order = 0 }
    $participant = Get-FirstRow -Response $p -Name "A create participant"; $participantId = [string]$participant.participant_id
    Add-Pass -Name "A create participant" -StatusCode $p.StatusCode -Uuid $participantId
    $join = Invoke-Rpc -Name "join_activity_by_code" -Token $b.AccessToken -Body @{ join_code = $joinCode }; Add-Pass -Name "B join activity" -StatusCode $join.StatusCode
    $claim = Invoke-Rpc -Name "claim_participant" -Token $b.AccessToken -Body @{ activity_id = $activityId; participant_id = $participantId }; Add-Pass -Name "B claim participant" -StatusCode $claim.StatusCode
    $png = [byte[]](0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A,0x00,0x00,0x00,0x0D,0x49,0x48,0x44,0x52,0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,0x08,0x06,0x00,0x00,0x00,0x1F,0x15,0xC4,0x89,0x00,0x00,0x00,0x0D,0x49,0x44,0x41,0x54,0x78,0x9C,0x63,0xF8,0xCF,0xC0,0xF0,0x1F,0x00,0x05,0x00,0x01,0xFF,0x89,0x99,0x3D,0x1D,0x00,0x00,0x00,0x00,0x49,0x45,0x4E,0x44,0xAE,0x42,0x60,0x82)
    $meta = Invoke-Rpc -Name "create_attachment" -Token $a.AccessToken -Body @{ activity_id = $activityId; ledger_unit_id = $ledgerUnitId; expense_id = $null; filename = "p6-$runId.png"; mime_type = "image/png"; size_bytes = $png.Length }
    $allocation = Get-FirstRow -Response $meta -Name "A create pending attachment"; $attachmentId = [string]$allocation.attachment_id; $bucket = [string]$allocation.bucket; $path = [string]$allocation.path; $status = [string]$allocation.status
    if ($attachmentId -notmatch "^[0-9a-fA-F-]{36}$" -or $bucket -ne "activity-attachments" -or $status -ne "pending" -or $path -notmatch "^$activityId/$ledgerUnitId/$attachmentId\.png$") { Add-Fail -Name "A create pending attachment" -StatusCode $meta.StatusCode -Class "STORAGE_CONTRACT_MISMATCH" }
    Add-Pass -Name "A create pending attachment" -StatusCode $meta.StatusCode -Uuid $attachmentId
    $encodedPath = Encode-StoragePath -Path $path
    $upload = Invoke-LocalApi -Method POST -Path "/storage/v1/object/$bucket/$encodedPath" -AccessToken $a.AccessToken -Bytes $png -ContentType "image/png"
    if ($upload.StatusCode -lt 200 -or $upload.StatusCode -ge 300) { Add-Fail -Name "A upload attachment object" -StatusCode $upload.StatusCode -Class "HTTP_$($upload.StatusCode)" }
    Add-Pass -Name "A upload attachment object" -StatusCode $upload.StatusCode
    $complete = Invoke-Rpc -Name "complete_attachment" -Token $a.AccessToken -Body @{ attachment_id = $attachmentId }; $completeValue = Convert-JsonBody -Response $complete -Name "A complete attachment"
    if ($completeValue -ne $true) { Add-Fail -Name "A complete attachment" -StatusCode $complete.StatusCode -Class "COMPLETE_FALSE" }
    Add-Pass -Name "A complete attachment" -StatusCode $complete.StatusCode
    foreach ($account in @(@{ Role = "A"; Session = $a }, @{ Role = "B"; Session = $b })) {
        $read = Invoke-LocalApi -Method GET -Path "/rest/v1/attachments?id=eq.$attachmentId&activity_id=eq.$activityId&select=id,activity_id,ledger_unit_id,storage_bucket,storage_path,status,mime_type,size_bytes" -AccessToken $account.Session.AccessToken
        if ($read.StatusCode -lt 200 -or $read.StatusCode -ge 300) { Add-Fail -Name "$($account.Role) read attachment metadata" -StatusCode $read.StatusCode -Class "HTTP_$($read.StatusCode)" }
        $rows = @(Convert-JsonBody -Response $read -Name "$($account.Role) read attachment metadata")
        if ($rows.Count -ne 1 -or [string]$rows[0].id -ne $attachmentId -or [string]$rows[0].status -ne "ready") { Add-Fail -Name "$($account.Role) read attachment metadata" -StatusCode $read.StatusCode -Class "ATTACHMENT_METADATA_MISMATCH" }
        Add-Pass -Name "$($account.Role) read attachment metadata" -StatusCode $read.StatusCode
        $download = Invoke-LocalApi -Method GET -Path "/storage/v1/object/authenticated/$bucket/$encodedPath" -AccessToken $account.Session.AccessToken -ResponseBytes
        $downloadMatches = if ($download.StatusCode -ge 200 -and $download.StatusCode -lt 300) {
            [Convert]::ToBase64String([byte[]]$download.Body) -ceq [Convert]::ToBase64String($png)
        } else { $false }
        if (-not $downloadMatches) { Add-Fail -Name "$($account.Role) download attachment object" -StatusCode $download.StatusCode -Class "OBJECT_READ_MISMATCH" }
        Add-Pass -Name "$($account.Role) download attachment object" -StatusCode $download.StatusCode
    }
    $outsiderMeta = Invoke-LocalApi -Method GET -Path "/rest/v1/attachments?id=eq.$attachmentId&activity_id=eq.$activityId&select=id" -AccessToken $c.AccessToken
    if ($outsiderMeta.StatusCode -ge 200 -and $outsiderMeta.StatusCode -lt 300) {
        $outsiderRows = @(Convert-JsonBody -Response $outsiderMeta -Name "C attachment metadata denied")
        if ($outsiderRows.Count -ne 0) { Add-Fail -Name "C attachment metadata denied" -StatusCode $outsiderMeta.StatusCode -Class "RLS_VISIBILITY_LEAK" }
    } elseif ($outsiderMeta.StatusCode -lt 400 -or $outsiderMeta.StatusCode -ge 500) { Add-Fail -Name "C attachment metadata denied" -StatusCode $outsiderMeta.StatusCode -Class "RLS_DENIAL_UNCONFIRMED" }
    Add-Pass -Name "C attachment metadata denied" -StatusCode $outsiderMeta.StatusCode
    $outsiderDownload = Invoke-LocalApi -Method GET -Path "/storage/v1/object/authenticated/$bucket/$encodedPath" -AccessToken $c.AccessToken
    if ($outsiderDownload.StatusCode -lt 400 -or $outsiderDownload.StatusCode -ge 500) { Add-Fail -Name "C attachment object denied" -StatusCode $outsiderDownload.StatusCode -Class "RLS_OBJECT_LEAK" }
    Add-Pass -Name "C attachment object denied" -StatusCode $outsiderDownload.StatusCode
    Write-Output "SUMMARY PASS=$script:passCount FAIL=$script:failCount TOTAL=$script:stepCount"
} catch {
    if (-not $script:failureReported) { $script:stepCount++; $script:failCount++; Write-Output "FAIL storage smoke HTTP=HTTP-0 CLASS=SCRIPT_ERROR" }
    Write-Output "SUMMARY PASS=$script:passCount FAIL=$script:failCount TOTAL=$script:stepCount"; exit 1
} finally { if ($null -ne $script:httpClient) { $script:httpClient.Dispose() } }
